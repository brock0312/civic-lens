"""花蓮縣議會第 20 屆縣政總質詢影片：video_1.php（定期大會影片查詢，POST），影片放在 YouTube（V16）。

不逐人查詢：以空白關鍵字查第 20 屆全部定期大會影片（一頁列完，2026-10-07 共 190 支），只收議程為「縣政總質詢-甲議員、乙議員…」的場次，
依標題上的議員名單分給每位對象。一支影片是半天（3–7 位議員），沒有個人起點，只寫「本場質詢議員…，未細分到個人」（同新北）。
名單中括號內的人（「楊華美議員(蔡依靜議員補充)」）不收，只收列名的質詢議員。連到 YouTube 官方網址，不嵌入播放器；
頻道「花蓮縣議會」由議會官網連結（V16）。

只寫給有花蓮縣議員任職 fact 且有 2026 candidacy 的人（hua_book 的對象），姓名以 etl.match 的漢字正規化對全部花蓮縣議員名錄，
同名或對不到的不收（印 log）。
自我檢查：python3 -m etl.sources.hua_videos [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import html
import re
import sys
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import now_utc
from etl.sources.hua_book import OFFICE, TERM, post, resolve_token
from etl.sources.national_councilors import TERM_START
from etl.sources.nwt_book import resolve, roster_index, targets

CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "hua_video"

ITEM = re.compile(r'<span class="font_blod">(.*?)</span>.*?href="https://youtu\.be/([\w-]{11})"', re.S)
TITLE = re.compile(r"^花蓮縣議會第(\d+)屆第(\d+)次定期大會(?:延長會)?-(\d{4})年(\d+)月(\d+)日(上午|下午)議程：縣政總質詢-(.+?)。?$")


def parse_page(page):
    """查詢結果 → [{title, video_id}]（頁面順序：新到舊）。"""
    return [{"title": re.sub(r"\s+", "", html.unescape(t)), "video_id": vid} for t, vid in ITEM.findall(page)]


def parse_title(title):
    """「花蓮縣議會第20屆第7次定期大會-2026年6月9日上午議程：縣政總質詢-黃馨議員、…」→ {term, session, date, half, names}；
    不是縣政總質詢回 None。"""
    m = TITLE.match(title)
    if not m:
        if "縣政總質詢-" in title:
            raise ValueError(f"花蓮影片標題格式未知：{title!r}")
        return None
    term, nth, y, mo, d, half, names = m.groups()
    names = [re.sub(r"(議員|副議長|議長)$", "", re.sub(r"[（(][^）)]*[）)]", "", x)) for x in names.split("、")]
    return {"term": int(term), "session": f"第{int(term)}屆第{int(nth)}次定期大會", "date": f"{y}-{int(mo):02d}-{int(d):02d}",
            "half": half, "names": [x for x in names if x]}


def fetch_all():
    """快取 data/cache/hua_video/all.html（第 20 屆全部定期大會影片）。"""
    path = CACHE / "all.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(post("/video_1.php", {"sec_1": TERM, "keyword": "", "search": "y"}), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def assign(items, roster, log=print):
    """→ {person_id: [video]}：每支第 20 屆縣政總質詢影片，分給名單上能唯一對到名錄的人（同一影片每人一次）。"""
    out = {}
    for it in items:
        meta = parse_title(it["title"])
        if not meta or meta["term"] != TERM or meta["date"] < TERM_START:
            continue
        v = {**meta, "video_id": it["video_id"]}
        for name in meta["names"]:
            pids, why = resolve_token(name, roster)
            if not pids or len(pids) != 1:
                log(f"hua_videos：{meta['date']} 縣政總質詢 {name}：{why or '不是一個人'}")
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
            log(f"hua_videos：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        vs = [v for v in by_pid.get(pid, []) if v["date"] >= t["since"]]
        if vs:
            out[pid] = vs
    return ts, out


def video_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def write_videos(conn, by_pid, fetched_at):
    """每位議員每支影片一筆 fact，刪除這次不在結果裡的舊 fact。回傳 (筆數, 刪除筆數)。"""
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'hlccvideo:%'")}
    current = set()
    for pid, videos in by_pid.items():
        for v in videos:
            k = f"hlccvideo:{v['video_id']}:{pid}"
            current.add(k)
            upsert_fact(conn, k, pid, "interpellation", {
                "title": f"縣政總質詢（{v['half']}）", "doc_type": "縣政總質詢", "dept": None, "term": TERM, "session": v["session"],
                "councillors": v["names"], "group_size": len(v["names"]), "video_id": v["video_id"], "whole": True,
            }, video_url(v["video_id"]), fetched_at, date=v["date"])
    stale = known - current
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    return len(current), len(stale)


def run(conn):
    items = parse_page(fetch_all())
    if not items:
        raise ValueError("花蓮影片查詢沒有結果")
    logs = set()
    ts, by_pid = build(conn, items, lambda s: logs.add(re.sub(r"^hua_videos：\S+ ", "hua_videos：", s)))
    for line in sorted(logs):
        print(line)
    n, stale = write_videos(conn, by_pid, now_utc())
    print(f"hua_videos：影片 {len(items)} 支；對象 {len(ts)} 人，有影片 {len(by_pid)} 人，影片 {n} 筆，刪除 {stale} 筆")


def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    items = parse_page((CACHE / "all.html").read_text(encoding="utf-8"))
    logs = []
    ts, by_pid = build(dump_conn(), items, logs.append)
    for line in sorted(set(logs)):
        print(" ", line)
    print(f"快取影片 {len(items)} 支（縣政總質詢 {sum(parse_title(i['title']) is not None for i in items)}）；對象 {len(ts)} 人；"
          f"有影片 {len(by_pid)} 人，影片 {sum(map(len, by_pid.values()))} 筆")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in [p for p in names if names[p] in samples]:
        vs = by_pid.get(pid, [])
        print(f"\n{names[pid]}（{pid}）影片 {len(vs)} 支")
        for v in vs:
            print(f"  {v['date']} {v['session']} {v['half']} {'、'.join(v['names'])} {video_url(v['video_id'])}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        fetch_all()
    check([a for a in sys.argv[1:] if not a.startswith("--")])
