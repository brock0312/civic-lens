"""新北市議會第 4 屆口頭質詢影片：議事影音 VodCloudV2（vod.ntp.gov.tw，V15）。

影片是整場會議（業務質詢一場是一個黨團 10 多位議員、市政總質詢一場約 5 位），沒有個人起點。每支影片列有「發言議員」，
歸屬只看這份名單：名單上有本人才收（同臺中規則：寧缺勿掛錯人）。

只列清單、連影音網首頁（V15 已定案第 6 點，使用者 2026-10-05 決定）：單支影片網址 ViewDetailMetaData/<id> 依賴
ASP.NET session，讀者連續開啟會出錯；官方 YouTube 只有 2025-09-30 起的整場錄影、標題沒有議員姓名，也無法逐支對應。
所以每筆 fact 的 source_url 都是影音網首頁 HOME（2026-10-05 實測連續開啟、有無 cookie 都回同一頁），data.link = "home"
表示沒有單支連結，讀者以日期、會期與會議名稱自行查詢。

請求量：不逐人查詢（52 人 × 約 13 頁），而是以關鍵字「質詢」查第 4 屆全部影片（每頁 12 支、約 70 頁），
再依發言議員名單分給每位對象；只收議程含「質詢」的場次（「市政總質詢-報告事項」等非質詢議程不收）。
只寫給有新北市議員任職 fact 且有 2026 candidacy 的人（nwt_book.targets），姓名以 etl.match 的漢字正規化對全部
新北市議員名錄，同名或對不到的不收（印 log）。
自我檢查：python3 -m etl.sources.nwt_videos（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import html
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import UA, now_utc
from etl.sources.national_councilors import TERM_START
from etl.sources.nwt_book import resolve, roster_index, targets

VOD = "https://vod.ntp.gov.tw/VodCloudV2"
HOME = "https://vod.ntp.gov.tw/VodCloud/index.htm"  # 影音網首頁，不依賴 session
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "nwt_vod"
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔（robots.txt 404，V15）
KEYWORD = "質詢"
PER_PAGE = 12
MAX_PAGES = 200  # 安全上限：2026-10-04 共 848 支、71 頁

ITEM = re.compile(r'<a href=ViewDetailMetaData/([\w-]+) class="mov">(.*?)</h6>', re.S)
FIELD = re.compile(r">\s*([^<>：]+?)：([^<]*)</span>")
TOTAL = re.compile(r"總筆數:(\d+)")
SESSION = re.compile(r"^第(\d+)屆第(\d+)次(定期會|臨時會)$")

_last = 0.0
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def post(path, form):
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(VOD + path, data=urllib.parse.urlencode(form).encode(), headers={"User-Agent": UA})
    try:
        with _opener.open(req, timeout=60) as resp:
            return resp.read().decode("utf-8")
    finally:
        _last = time.monotonic()


def search_form(page, today):
    # 少了 Sort 伺服器回 500（V15）
    return {"pageindex": page, "MJ": "", "MP": "", "MType": "", "sMDate": TERM_START.replace("-", "/"),
            "eMDate": today.strftime("%Y/%m/%d"), "Keyword": KEYWORD, "cEPName": "", "Sort": "MDate"}


def parse_page(page):
    """搜尋結果一頁 → ([{id, session, agenda, speakers, date, duration}], 總筆數)。"""
    total = TOTAL.search(page)
    if not total:
        raise ValueError("新北 VOD 搜尋結果找不到總筆數")
    items = []
    for vid, block in ITEM.findall(page):
        f = {re.sub(r"[\s　]", "", k): html.unescape(v).strip() for k, v in FIELD.findall(block)}
        y, m, d = f["開會日期"].split("-")
        dur = re.search(r'class="timecode">([\d:]+)<', block)
        items.append({"id": vid, "session": f.get("屆次會期", ""), "agenda": f.get("議程", ""),
                      "speakers": list(dict.fromkeys(s.strip() for s in f.get("發言議員", "").split(",") if s.strip())),
                      "date": f"{int(y) + 1911}-{m}-{d}", "duration": dur.group(1) if dur else None})
    return items, int(total.group(1))


def parse_agenda(agenda):
    """議程 → (doc_type, title)；不是質詢回 None。"""
    if "質詢" not in agenda or "報告事項" in agenda or "抽籤" in agenda:  # 「預備會議-市政總質詢順序抽籤」
        return None
    if agenda.startswith("市政總質詢"):
        return "市政總質詢", "市政總質詢"
    if "業務報告及質詢" in agenda:
        return "業務質詢", agenda.replace("-", "，")
    raise ValueError(f"新北影片議程格式未知：{agenda!r}")


def fetch_all(full=False, today=None):
    """快取 data/cache/nwt_vod/search.json = {items}（第 4 屆、關鍵字「質詢」的全部搜尋結果，依開會日期新到舊）。

    從第 1 頁往後翻，直到翻完，或（增量）某頁出現快取裡已有的影片。
    ponytail: 增量假設新影片只會出現在清單前面；補上架的舊場次影片會漏，升級：run(full=True)（約 70 次請求）。
    """
    today = today or date.today()
    path = CACHE / "search.json"
    cached = None if full or not path.exists() else json.loads(path.read_text(encoding="utf-8"))
    known = {it["id"] for it in cached["items"]} if cached else set()
    items, page, pages = [], 1, 1
    while page <= pages:
        if page > MAX_PAGES:
            raise ValueError(f"新北 VOD 超過 {MAX_PAGES} 頁")
        got, total = parse_page(post("/VOD/Search", search_form(page, today)))
        pages = -(-total // PER_PAGE)
        new = [it for it in got if it["id"] not in known and it["id"] not in {x["id"] for x in items}]
        items += new
        if len(new) < len(got):
            break
        page += 1
    if cached:
        items += [it for it in cached["items"] if it["id"] not in {x["id"] for x in items}]
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return items


def assign(items, roster, log=print):
    """→ {person_id: [video]}：每支第 4 屆質詢影片，分給發言議員名單上能唯一對到名錄的人（同一影片每人一次）。"""
    out = {}
    for it in items:
        m = SESSION.match(it["session"])
        if it["date"] < TERM_START or not m or int(m.group(1)) != 4:
            continue
        kind = parse_agenda(it["agenda"])
        if not kind:
            continue
        doc_type, title = kind
        v = {**it, "doc_type": doc_type, "title": title}
        for name in dict.fromkeys(it["speakers"]):
            pid, why = resolve(name, roster)
            if not pid:
                log(f"nwt_videos：{it['date']} {it['agenda']} 發言議員 {name}：{why}")
                continue
            vs = out.setdefault(pid, {})
            vs.setdefault(it["id"], v)
    return {pid: sorted(vs.values(), key=lambda v: (v["date"], v["id"])) for pid, vs in out.items()}


def build(conn, items, log=print):
    ts = targets(conn)
    roster = roster_index(conn)
    by_pid = assign(items, roster, log)
    out = {}
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"nwt_videos：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        vs = [v for v in by_pid.get(pid, []) if v["date"] >= t["since"]]
        if vs:
            out[pid] = vs
    return ts, out


def write_videos(conn, by_pid, fetched_at):
    """每位議員每支影片一筆 fact，刪除這次不在結果裡的舊 fact。回傳 (筆數, 刪除筆數)。"""
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'ntpvideo:%'")}
    current = set()
    for pid, videos in by_pid.items():
        for v in videos:
            k = f"ntpvideo:{v['id']}:{pid}"
            current.add(k)
            upsert_fact(conn, k, pid, "interpellation", {
                "title": v["title"], "doc_type": v["doc_type"], "dept": None, "term": 4, "session": v["session"],
                "agenda": v["agenda"], "councillors": v["speakers"], "group_size": len(v["speakers"]),
                "video_id": v["id"], "link": "home",
            }, HOME, fetched_at, date=v["date"])
    stale = known - current
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    return len(current), len(stale)


def run(conn, full=False):
    logs = set()  # 同一位前議員會在上百支影片出現，只印一次
    ts, by_pid = build(conn, fetch_all(full), lambda s: logs.add(re.sub(r"^nwt_videos：\S+ \S+ ", "nwt_videos：", s)))
    for line in sorted(logs):
        print(line)
    n, stale = write_videos(conn, by_pid, now_utc())
    print(f"nwt_videos：對象 {len(ts)} 人，有影片 {len(by_pid)} 人，影片 {n} 筆，刪除 {stale} 筆")


def check(samples=()):
    """讀快取與 data/civic.sql：對象人數、有影片人數與筆數，並列出抽查議員的影片。"""
    from etl.sources.nwt_book import dump_conn
    items = json.loads((CACHE / "search.json").read_text(encoding="utf-8"))["items"]
    logs = []
    ts, by_pid = build(dump_conn(), items, logs.append)
    for line in sorted(set(logs)):
        print(" ", line)
    agendas = {}
    for it in items:
        agendas[it["agenda"]] = agendas.get(it["agenda"], 0) + 1
    print("議程：", sorted(agendas.items(), key=lambda x: -x[1]))
    print(f"快取影片 {len(items)} 支；對象 {len(ts)} 人；有影片 {len(by_pid)} 人，影片 {sum(map(len, by_pid.values()))} 筆")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in [p for p in names if names[p] in samples]:
        vs = by_pid.get(pid, [])
        print(f"\n{names[pid]}（{pid}）影片 {len(vs)} 支")
        for v in vs[-5:]:
            print(f"  {v['date']} {v['session']} {v['title']}（{len(v['speakers'])} 位） {v['id']}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        print(len(fetch_all("--full" in sys.argv)), flush=True)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
