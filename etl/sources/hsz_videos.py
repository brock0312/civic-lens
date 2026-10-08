"""新竹市議會第 11 屆質詢影片：meetingVideo.aspx（會議影音查詢），影片放在 YouTube（V16）。

查詢結果可用網址參數分頁（?pn=N&mid=85&cc=11…，不必送 ASP.NET 表單）：取第 11 屆全部影片，只收標題為
「市政總質詢：甲、乙、丙」「單位業務質詢 甲 乙」（可帶「-2」等分段尾碼）的場次，依標題上的議員名單分給每位對象。
一支影片是同場 1–3 位議員，沒有個人起點，只寫「本場質詢議員…，未細分到個人」（同花蓮）。
連到 YouTube 官方網址，不嵌入播放器；頻道「新竹市議會」由議會官網連結（V16）。
網站資料開放宣告（/TC/page.aspx?mid=21）允許註明出處後利用，頁面標示「影片來源：新竹市議會」。

只寫給有新竹市議員任職 fact 且有 2026 candidacy 的人，姓名以 etl.match 的漢字正規化對全部新竹市議員名錄，
同名或對不到的不收（印 log）。
自我檢查：python3 -m etl.sources.hsz_videos [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import html
import re
import sys
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import now_utc
from etl.sources.hsz_book import OFFICE, TERM, fetch, roc_date
from etl.sources.hua_book import resolve_token
from etl.sources.national_councilors import TERM_START
from etl.sources.nwt_book import resolve, roster_index, targets

CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "hsz_video"
LIST_URL = "https://www.hsinchu-cc.gov.tw/tc/meetingVideo.aspx?pn={}&mid=85&cc=" + str(TERM) + "&m=&c=&y=&mon=&key="

ITEM = re.compile(r'youtube\.com/embed/([\w-]{11})".*?video-text__tittle">(.*?)</h3>.*?video-content-date">([^<]*)</span>'
                  r'<span class="video-content-category">([^<]*)</span>', re.S)
LAST_PAGE = re.compile(r'\?pn=(\d+)&amp;mid=85|\?pn=(\d+)&mid=85')
TITLE = re.compile(r"^(市政總質詢|單位業務質詢)[\s：:；;]+(.+?)(?:-\d+)?$")
WRITTEN = re.compile(r"\s*[（(]書面[）)]")


def parse_page(page):
    """查詢結果一頁 → ([{video_id, title, date, session}], 最後一頁頁碼)。"""
    items = [{"video_id": vid, "title": re.sub(r"\s+", " ", html.unescape(t)).strip(), "date": roc_date(d.strip()),
              "session": re.sub(r"\s+", "", html.unescape(s))} for vid, t, d, s in ITEM.findall(page)]
    pages = [int(a or b) for a, b in LAST_PAGE.findall(page)]
    return items, max(pages, default=1)


def parse_title(title):
    """「市政總質詢：施乃如、劉崇顯、陳啓源」「單位業務質詢 劉崇顯 孫鍚洲 施乃如」→ {doc_type, names}；不是質詢場次回 None。

    名單上註「(書面)」的人改提書面質詢、沒有在影片中質詢，不收；其他括號（黨團聯合質詢、括號內另列的姓名）整段去掉，
    只收列名的質詢議員（同花蓮）；「鍾淑英聯合質詢」去掉尾巴。標題像質詢場次卻不是這兩種格式時 raise ValueError（不猜）。"""
    m = TITLE.match(title)
    if not m:
        if re.search(r"總質詢|業務質詢", title):
            raise ValueError(f"新竹市影片標題格式未知：{title!r}")
        return None
    body = re.sub(r"[（(][^）)]*[）)]", "", WRITTEN.sub("#", m.group(2)))
    names = [re.sub(r"聯合質詢$", "", x) for x in re.split(r"[、，,；;：:\s]+", body) if x and not x.endswith("#")]
    return {"doc_type": m.group(1), "names": [x for x in names if x]}


def fetch_all():
    """快取 data/cache/hsz_video/p<N>.html（第 11 屆全部會議影片）。回傳全部影片。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    items, last, n = [], 1, 1
    while n <= last:
        page = fetch(LIST_URL.format(n)).decode("utf-8")
        (CACHE / f"p{n}.html").write_text(page, encoding="utf-8")
        got, last = parse_page(page)
        items += got
        n += 1
    return items


def cached_items():
    return [it for p in sorted(CACHE.glob("p*.html"), key=lambda p: int(p.stem[1:]))
            for it in parse_page(p.read_text(encoding="utf-8"))[0]]


def assign(items, roster, log=print):
    """→ {person_id: [video]}：每支第 11 屆質詢影片，分給名單上能唯一對到名錄的人（同一影片每人一次）。"""
    out = {}
    for it in items:
        if not it["session"].startswith(f"第{TERM}屆") or not it["date"] or it["date"] < TERM_START:
            continue
        try:
            meta = parse_title(it["title"])
        except ValueError as e:
            log(f"hsz_videos：{e}，不收")
            continue
        if not meta:
            continue
        v = {**it, **meta}
        for name in meta["names"]:
            pids, why = resolve_token(name, roster)
            if not pids or len(pids) != 1:
                log(f"hsz_videos：{it['date']} {meta['doc_type']} {name}：{why or '不是一個人'}")
                continue
            out.setdefault(pids[0], {}).setdefault(it["video_id"], v)
    return {pid: sorted(vs.values(), key=lambda v: (v["date"], v["video_id"])) for pid, vs in out.items()}


def build(conn, items, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    by_pid = assign(items, roster, log)
    out = {}
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"hsz_videos：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        vs = [v for v in by_pid.get(pid, []) if v["date"] >= t["since"]]
        if vs:
            out[pid] = vs
    return ts, out


def video_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def write_videos(conn, by_pid, fetched_at):
    """每位議員每支影片一筆 fact，刪除這次不在結果裡的舊 fact。回傳 (筆數, 刪除筆數)。"""
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'hszvideo:%'")}
    current = set()
    for pid, videos in by_pid.items():
        for v in videos:
            k = f"hszvideo:{v['video_id']}:{pid}"
            current.add(k)
            upsert_fact(conn, k, pid, "interpellation", {
                "title": v["title"], "doc_type": v["doc_type"], "dept": None, "term": TERM, "session": v["session"],
                "councillors": v["names"], "group_size": len(v["names"]), "video_id": v["video_id"], "whole": True,
            }, video_url(v["video_id"]), fetched_at, date=v["date"])
    stale = known - current
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    return len(current), len(stale)


def run(conn):
    items = fetch_all()
    if not items:
        raise ValueError("新竹市影片查詢沒有結果")
    logs = set()
    ts, by_pid = build(conn, items, logs.add)
    for line in sorted(logs):
        print(line)
    n, stale = write_videos(conn, by_pid, now_utc())
    print(f"hsz_videos：影片 {len(items)} 支；對象 {len(ts)} 人，有影片 {len(by_pid)} 人，影片 {n} 筆，刪除 {stale} 筆")


def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    items = cached_items()
    logs = []
    ts, by_pid = build(dump_conn(), items, logs.append)
    for line in sorted(set(logs)):
        print(" ", line)
    n_q = sum(1 for i in items if TITLE.match(i["title"]))
    print(f"快取影片 {len(items)} 支（質詢 {n_q}）；對象 {len(ts)} 人；有影片 {len(by_pid)} 人，影片 {sum(map(len, by_pid.values()))} 筆")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in [p for p in names if names[p] in samples]:
        vs = by_pid.get(pid, [])
        print(f"\n{names[pid]}（{pid}）影片 {len(vs)} 支")
        for v in vs:
            print(f"  {v['date']} {v['session']} {v['title']} {video_url(v['video_id'])}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        fetch_all()
    check([a for a in sys.argv[1:] if not a.startswith("--")])
