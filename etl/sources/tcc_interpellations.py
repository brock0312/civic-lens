"""臺北市議會第 14 屆書面質詢（M4）。來源：電子公報全文檢索系統 gaz.tcc.gov.tw 的「書面質詢」清單。

只收書面質詢：每份質詢稿有明確的提案議員（偶有聯名），可以乾淨歸屬到個人。
市政總質詢、部門業務質詢在公報裡是「第 N 組」的整組速記錄，不收（見 docs/validation/M4-interpellations.md）。
"""
import html
import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request

from etl.db import upsert, upsert_fact
from etl.fetch import UA, now_utc
from etl.sources.tcc_councilors import load_identity

BASE = "https://gaz.tcc.gov.tw"
LIST_PATH = "/search/dq/deptID/result.html"
LIST_PARAMS = {"sort": "desc", "sortField": "date", "cst": "S", "se": "14", "pageSize": "40"}
MIN_INTERVAL = 1.0  # 秒；禮貌爬取

ITEM = re.compile(r'<li>\s*<div class="item checkGrp">(.*?)</li>', re.S)
VIEWER_ID = re.compile(r'<iframe id="doc-ifr"[^>]*src="/pdf/viewer\.html\?id=([0-9A-F]+)"')
DOC_NO = re.compile(r'書面質詢稿編號：\s*<ul>\s*<li><a href="javascript:doDoc\(\)">([A-Z0-9]+)</a>')


def roc_dash_to_iso(s):
    y, m, d = s.split("-")
    return f"{int(y) + 1911:04d}-{m}-{d}"


def parse_list(page):
    """解析清單頁，回傳 [{index, date, dept, session, title, councillors}]；index 是 doc_viewer 的 dataIndex。"""
    out = []
    for li in ITEM.findall(page):
        index = re.search(r'doc_viewer\.html\?dataIndex=(\d+)', li)
        date = re.search(r'<span class="date">(\d+-\d\d-\d\d)</span>', li)
        spans = re.findall(r'<span class="dept">([^<]*)</span>', li)
        title = re.search(r'title="另開視窗至:([^"]*)"', li)
        names = re.findall(r'<span class="starpage">([^<]+)</span>', li)
        if not (index and date and title and names) or len(spans) != 2:
            raise ValueError(f"清單項目格式未知：{li[:300]!r}")
        out.append({
            "index": int(index.group(1)),
            "date": roc_dash_to_iso(date.group(1)),
            "dept": html.unescape(spans[0]).strip(),
            "session": html.unescape(spans[1]).strip(),
            "title": html.unescape(title.group(1)).strip(),
            "councillors": [html.unescape(n).strip() for n in names],
        })
    return out


def parse_viewer(page):
    """解析 doc_viewer 頁，回傳 (書面質詢稿編號, 部門, 屆會次, 公開的 PDF 檢視器 URL)。"""
    viewer = VIEWER_ID.search(page)
    doc_no = DOC_NO.search(page)
    dept = re.search(r'<li>部門別：([^<]*)</li>', page)
    session = re.search(r'<div class="title" id="htitle">([^<]*)</div>', page)
    if "<h2>書面質詢</h2>" not in page or not (viewer and doc_no and dept and session):
        raise ValueError("doc_viewer 頁格式未知")
    return (
        doc_no.group(1),
        html.unescape(dept.group(1)).strip(),
        # 休會、成立大會在 doc_viewer 寫成「第14屆第  次休會」，清單寫「第14屆休會」
        re.sub(r"第\s*次", "", html.unescape(session.group(1)).strip()),
        f"{BASE}/pdf/viewer.html?id={viewer.group(1)}",
    )


class Session:
    """doc_viewer 的 dataIndex 指向「這個 cookie session 最近一次查詢」的結果，所以清單與單筆要走同一個 session。"""

    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.last = 0.0

    def get(self, path, params=None):
        wait = self.last + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with self.opener.open(req, timeout=60) as resp:
                return resp.read().decode("utf-8")
        finally:
            self.last = time.monotonic()


def covered_councillors(conn):
    """source_state 記錄的、上次已翻到底涵蓋過的議員名單。"""
    row = conn.execute(
        "SELECT state FROM source_state WHERE source = 'tcc_interpellations'"
    ).fetchone()
    if row is None:
        return set()
    return set(json.loads(row["state"])["covered"])


def known_docs(conn):
    """DB 裡已有的書面質詢，用清單頁上就看得到的 (日期, 標題, 議員) 識別，才不必先打 doc_viewer。"""
    rows = conn.execute("SELECT date, data FROM fact WHERE kind = 'interpellation'")
    out = set()
    for r in rows:
        d = json.loads(r["data"])
        out.add((r["date"], d["title"], tuple(d["councillors"])))
    return out


def write_doc(conn, item, doc_no, source_url, identity, fetched_at):
    """聯名質詢：每位有對照的議員各寫一筆，fact_key 以文件編號＋person_id 區分。回傳寫入筆數。"""
    n = 0
    for name in item["councillors"]:
        if name not in identity:
            continue
        person_id = identity[name][0]
        upsert_fact(
            conn, f"interp:{doc_no}:{person_id}", person_id, "interpellation",
            {
                "title": item["title"],
                "term": 14,
                "session": item["session"],
                "doc_type": "書面質詢",
                "dept": item["dept"],
                "doc_no": doc_no,
                "councillors": item["councillors"],
            },
            source_url, fetched_at, date=item["date"],
        )
        n += 1
    return n


# ponytail: 增量＝依質詢日期新到舊翻頁，碰到 DB 已有文件的那一頁處理完就停。上限：
#   1) 舊文件事後被修正（標題、PDF 換版）不會重抓；
#   2) doc_viewer 的 dataIndex 綁 session 查詢結果，若伺服器端不快照、翻頁途中剛好有新文件上架，索引可能位移——
#      以 doc_viewer 回傳的部門、屆會次與清單比對擋掉大部分錯位，但同部門同會期的相鄰文件擋不住。
#   identity 出現未涵蓋的議員時（新加入的對照名單），會把清單翻到底，只對未知文件打 doc_viewer；
#   完成後把涵蓋名單記進 source_state，之後恢復一般增量。
# 升級：定期（例如每週）加一個 full=True 的全量重掃；或改用文件編號區間比對找缺漏。
def run(conn, full=False):
    identity = load_identity()
    covered = covered_councillors(conn)
    uncovered = set(identity) - covered
    exhaustive = full or bool(uncovered)
    known = set() if full else known_docs(conn)
    fetched_at = now_utc()
    s = Session()
    page_no = 1
    while True:
        items = parse_list(s.get(LIST_PATH, {**LIST_PARAMS, "currentPage": str(page_no)}))
        if not items:
            if page_no == 1:
                raise ValueError("書面質詢清單第 1 頁沒有任何項目，頁面格式可能改了")
            break
        hit_known = False
        for item in items:
            if (item["date"], item["title"], tuple(item["councillors"])) in known:
                hit_known = True
                continue
            if not any(n in identity for n in item["councillors"]):
                continue
            doc_no, dept, session, source_url = parse_viewer(
                s.get("/pdf/index/doc_viewer.html", {"dataIndex": str(item["index"]), "fromPage": "1"})
            )
            if (dept, session) != (item["dept"], item["session"]):
                raise ValueError(f"doc_viewer 與清單不一致（索引位移？）：{item} vs {dept} {session}")
            write_doc(conn, item, doc_no, source_url, identity, fetched_at)
        if hit_known and not exhaustive:
            break
        page_no += 1
    upsert(
        conn, "source_state",
        {"source": "tcc_interpellations", "state": json.dumps({"covered": sorted(identity)}, ensure_ascii=False)},
        ("source",),
    )
