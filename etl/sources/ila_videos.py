"""宜蘭縣議會第 20 屆質詢影片：議事影音（mod.ilcc.gov.tw）的逐人剪輯片段（V16）。

每支影片是一位議員在一場會議的發言片段，標題形如「015林議員岳賢-第20屆第07次定期大會-第26次會議-縣長施政總質詢及答復」
（議長、副議長寫「張議長勝德」「陳副議長漢鍾」；複姓寫「孫湯議員玉惠」）。清單以 film_name=<姓><職稱><名> 查詢，
每位對象依姓氏長度 1（名字 ≥ 4 個漢字時另試 2）× 三種職稱各查一次，清單依開會日期新到舊，翻到第 20 屆以前就停。
歸屬一律以標題解析出的姓名，用 etl.match 的漢字正規化整名對宜蘭縣議員名錄，必須唯一且等於查詢對象；「說明」欄要與標題同一人。
同名、對不到、標題格式不明（如「開幕典禮致詞」）或不是第 20 屆的都不收（印 log）。
清單上的日期是開會日期，直接當質詢日期；同日多場依 data.seq（會期×100＋會議次）新到舊。
連結到播放頁 vod_show_mp4_play.asp?id=<n>（不需 cookie），不下載影片。
快取：data/cache/ila/（清單每次重抓）。
自我檢查：python3 -m etl.sources.ila_videos [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import html
import re
import sys
import time
import urllib.parse
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import get, now_utc
from etl.sources.nwt_book import key, resolve, roster_index, targets

OFFICE = "ila_councilor"
TERM = 20
TERM_START = "2022-12-25"
HOST = "https://mod.ilcc.gov.tw/mod/front2016/"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "ila"
ROLES = ("議員", "副議長", "議長")

ROW = re.compile(r'<a href="vod_show_mp4_play\.asp\?id=(\d+)&rule=1&film_spec=MP4">\s*<font[^>]*><strong>(.*?)</strong>'
                 r'.*?開會日期: </font><font[^>]*>\s*(\d{4})/(\d\d)/(\d\d)\s*</font>'
                 r'.*?說明: </font><font[^>]*>(.*?)</font>', re.S)
PAGES = re.compile(r"共<font[^>]*>(\d+)</font>頁")
TITLE = re.compile(r"^(\d{3})(.+?)(副議長|議長|議員)(.+?)-第(\d+)屆第(\d+)次(定期大會|定期會|大會|臨時大會|臨時會)"
                   r"-第(\d+(?:、\d+)*)次會議-(.+)$")

_last = {}


def fetch(url):
    """同一主機間隔 ≥ 1.1 秒，循序。"""
    host = urllib.parse.urlsplit(url).netloc
    wait = 1.1 - (time.monotonic() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        return get(url)
    finally:
        _last[host] = time.monotonic()


def queries(name):
    """名錄姓名 → film_name 查詢字串（「林議員岳賢」「林副議長岳賢」…；名字 ≥ 4 個漢字時另試複姓）。"""
    k = key(name)
    return [k[:n] + role + k[n:] for n in ((1, 2) if len(k) >= 4 else (1,)) for role in ROLES]


def list_url(q, page_no):
    return f"{HOST}vod_show_list.asp?PageNo={page_no}&PageSize=100&film_name={urllib.parse.quote(q)}&order=1"


def play_url(vid):
    return f"{HOST}vod_show_mp4_play.asp?id={vid}&rule=1&film_spec=MP4"


def parse_list(page):
    """清單一頁 → ([{id, title, date, desc}], 總頁數)。"""
    clean = lambda s: re.sub(r"\s+", "", html.unescape(s))
    rows = [{"id": int(i), "title": clean(t), "date": f"{y}-{m}-{d}", "desc": clean(desc)}
            for i, t, y, m, d, desc in ROW.findall(page)]
    pages = PAGES.search(page)
    return rows, int(pages.group(1)) if pages else 1


def parse_title(title):
    """標題 → {seat, name, role, term, nth, kind, session, meeting, meeting_label, topic}；格式不明回 None。
    定期大會／定期會／大會都是定期會，臨時大會／臨時會是臨時會；「第26、27次會議」（兩場合併）的 meeting 取第一場。
    座號（seat）只是參考：議長有時掛別的座號（第 3 次定期會的 029），歸屬只看姓名。"""
    m = TITLE.match(title)
    if not m:
        return None
    seat, sur, role, given, term, nth, kind, meeting, topic = m.groups()
    kind = "臨時會" if kind.startswith("臨時") else "定期會"
    nth = int(nth)
    nos = [int(n) for n in meeting.split("、")]
    return {"seat": seat, "name": sur + given, "role": role, "term": int(term), "nth": nth, "kind": kind,
            "session": f"第{int(term)}屆第{nth}次{kind}", "meeting": nos[0],
            "meeting_label": f"第{'、'.join(map(str, nos))}次會議", "topic": topic}


def _cached(name, url, refresh):
    path = CACHE / name
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(url))
    return path.read_text(encoding="utf-8")


def load(names, refresh=True):
    """→ {查詢字串: [row]}，只到第 20 屆開始日（清單依開會日期新到舊）。"""
    out = {}
    for name in names:
        for q in queries(name):
            rows, page_no = [], 1
            while True:
                page_rows, pages = parse_list(_cached(f"list/{q}_p{page_no}.html", list_url(q, page_no), refresh))
                rows += page_rows
                if page_no >= pages or any(r["date"] < TERM_START for r in page_rows):
                    break
                page_no += 1
            out[q] = [r for r in rows if r["date"] >= TERM_START]
    return out


def build(conn, listings, log=print):
    """listings：{查詢字串: [row]} → (targets, {person_id: [clip]})。"""
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    out = {}
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"ila_videos：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        clips = {}
        for q in queries(t["name"]):
            for r in listings.get(q, []):
                meta = parse_title(r["title"])
                if not meta:
                    log(f"ila_videos：查詢 {q} id={r['id']} 標題格式不明：{r['title']}，不收")
                    continue
                if meta["term"] != TERM:
                    continue
                owner, why = resolve(meta["name"], roster)
                if owner != pid:
                    log(f"ila_videos：查詢 {q} id={r['id']} 標題姓名 {meta['name']}（{why or '是別人'}），不收")
                    continue
                desc = parse_title(r["desc"])
                if not desc or key(desc["name"]) != key(meta["name"]):
                    log(f"ila_videos：{t['name']} id={r['id']} 說明欄與標題不是同一人：{r['desc']}，不收")
                    continue
                if r["date"] < t["since"]:  # 遞補者從上任起算（第 20 屆目前沒有遞補）
                    continue
                clips[r["id"]] = {**r, **meta}
        if clips:
            out[pid] = sorted(clips.values(), key=lambda v: (v["date"], v["nth"], v["meeting"], v["id"]))
    owners = {}
    for pid, vs in out.items():
        for v in vs:
            owners.setdefault(v["id"], set()).add(pid)
    dup = {i for i, ps in owners.items() if len(ps) > 1}
    for i in sorted(dup):
        log(f"ila_videos：id={i} 同時對到多位議員，不收")
    out = {pid: [v for v in vs if v["id"] not in dup] for pid, vs in out.items()}
    return ts, {pid: vs for pid, vs in out.items() if vs}


def write_videos(conn, by_pid, fetched_at):
    """每位議員每支影片一筆 fact，刪除這次不在結果裡的舊 fact。回傳 (筆數, 刪除筆數)。"""
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'ilavideo:%'")}
    current = set()
    for pid, items in by_pid.items():
        for v in items:
            k = f"ilavideo:{v['id']}:{pid}"
            current.add(k)
            upsert_fact(conn, k, pid, "interpellation", {
                "title": f"{v['meeting_label']} {v['topic']}", "dept": v["session"].replace(f"第{TERM}屆", ""),
                "term": TERM, "session": v["session"], "meeting": v["meeting_label"], "topic": v["topic"],
                "video_id": str(v["id"]), "clip": True, "seat": v["seat"], "seq": v["nth"] * 100 + v["meeting"],
            }, play_url(v["id"]), fetched_at, date=v["date"])
    stale = known - current
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    return len(current), len(stale)


def run(conn):
    ts = targets(conn, OFFICE)
    if not ts:
        raise ValueError("宜蘭縣議員名錄沒有參選 2026 的對象")
    listings = load([t["name"] for t in ts], refresh=True)
    logs = set()
    ts, by_pid = build(conn, listings, logs.add)
    for line in sorted(logs):
        print(line)
    n, stale = write_videos(conn, by_pid, now_utc())
    print(f"ila_videos：查詢 {len(listings)} 次；對象 {len(ts)} 人，有紀錄 {len(by_pid)} 人，{n} 筆，刪除 {stale} 筆")


def check(samples=(), refresh=False):
    from etl.sources.nwt_book import dump_conn
    conn = dump_conn()
    listings = load([t["name"] for t in targets(conn, OFFICE)], refresh=refresh)
    logs = []
    ts, by_pid = build(conn, listings, logs.append)
    for line in sorted(set(logs)):
        print(" ", line)
    print(f"對象 {len(ts)} 人；有紀錄 {len(by_pid)} 人，{sum(map(len, by_pid.values()))} 筆")
    for t in ts:
        vs = by_pid.get(t["person_id"], [])
        print(f"  {t['name']}：{len(vs)} 筆" + (f"（{vs[0]['date']}～{vs[-1]['date']}，座號 {sorted({v['seat'] for v in vs})}，"
                                               f"職稱 {sorted({v['role'] for v in vs})}）" if vs else ""))
        if t["name"] in samples:
            for v in vs:
                print(f"    {v['date']} {v['session']} {v['meeting_label']} {v['topic']} {play_url(v['id'])}")


if __name__ == "__main__":
    check([a for a in sys.argv[1:] if not a.startswith("--")], refresh="--fetch" in sys.argv)
