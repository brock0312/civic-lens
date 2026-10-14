"""金門縣議會第 8 屆縣政總質詢影片：官方 YouTube 頻道（UCssU97D8roqOPbnU4I-OsOw，議會官網「議事影音直播」連結，V16）。

第 8 屆影片標題沒有議員姓名，只有日期與會期（「1131209金門縣議會第八屆第4次定期會-1」，一天一至數段）。
以「會期＋日期」對到 kin_book 的縣政總質詢紀錄：那天有總質詢紀錄的，當天全部影片分給當天的質詢議員，沒有個人起點，
頁面寫「當天質詢議員…，未細分到個人」。日期異常（不作排序日期）的總質詢紀錄不對影片。
頻道說明禁止未經同意重製、剪輯或公開傳輸，所以只放 YouTube 連結，不下載、不嵌入。
清單用 yt-dlp（--flat-playlist、zh-TW，否則標題會被自動翻成英文）讀直播與影片兩個分頁，快取 data/cache/kin/yt_*.tsv。

只寫給 kin_book 的對象；姓名以 etl.match 的漢字正規化對全部金門縣議員名錄，同名或對不到的不收（印 log）。
自我檢查：python3 -m etl.sources.kin_videos [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import re
import subprocess
import sys
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import UA, now_utc
from etl.sources import kin_book
from etl.sources.kin_book import CACHE, OFFICE, TERM
from etl.sources.nwt_book import resolve, roster_index, targets

CHANNEL = "https://www.youtube.com/channel/UCssU97D8roqOPbnU4I-OsOw/"
TABS = ("streams", "videos")
# 「1131209金門縣議會第八屆第4次定期會-1」「1121116金門縣議會第八屆第2次定期會-1(第2段請至影片頁籤觀看)」
TITLE = re.compile(r"^(\d{2,3})(\d\d)(\d\d)金門縣議會第八屆第(\d+)次定期會(?:-(\d+))?(?:\(.*\))?$")


def fetch_tab(tab):
    path = CACHE / f"yt_{tab}.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    out = subprocess.run(["yt-dlp", "--no-update", "--flat-playlist", "--sleep-requests", "1.2", "--user-agent", UA,
                          "--extractor-args", "youtube:lang=zh-TW", "--print", "%(id)s\t%(title)s", CHANNEL + tab],
                         capture_output=True, check=True, text=True).stdout
    if not out.strip():
        raise ValueError(f"金門 YouTube {tab} 分頁沒有影片")
    path.write_text(out, encoding="utf-8")


def load_items():
    """兩個分頁的快取 → [{video_id, title}]（同一 id 只留一次）。"""
    out = {}
    for tab in TABS:
        for line in (CACHE / f"yt_{tab}.tsv").read_text(encoding="utf-8").splitlines():
            vid, _, title = line.partition("\t")
            out.setdefault(vid, {"video_id": vid, "title": title.strip()})
    return list(out.values())


def parse_title(title):
    """→ {date, nth, part}；不是第 8 屆定期會大會影片（審查委員會、臨時會、其他屆）回 None。"""
    m = TITLE.match(title)
    if not m:
        return None
    y, mo, d, nth, part = m.groups()
    return {"date": f"{int(y) + 1911}-{mo}-{d}", "nth": int(nth), "part": int(part) if part else None}


def match(items, govs):
    """→ [{video_id, date, session, part, names}]：第 8 屆定期會影片中，同會期同日期有縣政總質詢紀錄的，
    names 是當天各場質詢議員（依清單順序、不重複）。"""
    days = {}
    for g in govs:
        if g["date"] and g["kind"] == "定期會":
            names = days.setdefault((g["nth"], g["date"]), [])
            names += [n for n in g["names"] if n not in names]
    out = []
    for it in items:
        meta = parse_title(it["title"])
        if meta and (meta["nth"], meta["date"]) in days:
            out.append({**meta, "video_id": it["video_id"], "session": f"第{TERM}屆第{meta['nth']}次定期會",
                        "names": days[(meta["nth"], meta["date"])]})
    return sorted(out, key=lambda v: (v["date"], v["part"] or 0, v["video_id"]))


def assign(videos, roster, pids, log=print):
    out = {}
    for v in videos:
        for name in v["names"]:
            pid, why = resolve(name, roster)
            if not pid:
                log(f"kin_videos：{v['date']} {name}：{why}")
            elif pid in pids:
                out.setdefault(pid, []).append(v)
    return out


def video_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def build(conn, items, govs, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    pids = {t["person_id"] for t in ts if resolve(t["name"], roster)[0] == t["person_id"]}
    videos = match(items, govs)
    return ts, videos, assign(videos, roster, pids, log)


def write_videos(conn, by_pid, fetched_at):
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'kinvideo:%'")}
    current = set()
    for pid, videos in by_pid.items():
        for v in videos:
            k = f"kinvideo:{v['video_id']}:{pid}"
            current.add(k)
            part = f"（第 {v['part']} 段）" if v["part"] else ""
            upsert_fact(conn, k, pid, "interpellation", {
                "title": f"縣政總質詢當天議事影片{part}",
                "doc_type": "縣政總質詢", "dept": None, "term": TERM, "session": v["session"], "councillors": v["names"],
                "group_size": len(v["names"]), "video_id": v["video_id"], "whole": True, "day": True,
            }, video_url(v["video_id"]), fetched_at, date=v["date"])
    stale = known - current
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    return len(current), len(stale)


def _govs(refresh):
    gov = kin_book.load_list("AgendaGovMinutes", refresh)
    details = {r["id"]: kin_book.detail_page(r["id"], refresh) for r in gov}
    return kin_book.gov_rows(gov, details, log=lambda s: None)


def run(conn):
    for tab in TABS:
        fetch_tab(tab)
    items = load_items()
    logs = set()
    ts, videos, by_pid = build(conn, items, _govs(refresh=False), logs.add)  # kin_book 剛更新過清單與詳細頁快取
    for line in sorted(logs):
        print(line)
    n, stale = write_videos(conn, by_pid, now_utc())
    print(f"kin_videos：頻道影片 {len(items)} 支，對到縣政總質詢日 {len(videos)} 支；對象 {len(ts)} 人，有影片 {len(by_pid)} 人，"
          f"影片 {n} 筆，刪除 {stale} 筆")


def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    items = load_items()
    logs = []
    ts, videos, by_pid = build(dump_conn(), items, _govs(refresh=False), logs.append)
    for line in sorted(set(logs)):
        print(" ", line)
    days = sorted({v["date"] for v in videos})
    print(f"快取影片 {len(items)} 支；對到 {len(videos)} 支、{len(days)} 天；有影片 {len(by_pid)} 人，影片 {sum(map(len, by_pid.values()))} 筆")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in [p for p in names if any(s in names[p] for s in samples)]:
        for v in by_pid.get(pid, []):
            print(f"  {names[pid]} {v['date']} 第 {v['part']} 段 {'、'.join(v['names'])} {video_url(v['video_id'])}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        for tab in TABS:
            fetch_tab(tab)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
