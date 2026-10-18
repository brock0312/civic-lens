"""彰化縣議會第 20 屆縣政質詢影片：官方 YouTube「彰化縣議會直播頻道」（UCNWh1ZPg_dkTiDSitjVLrrQ，議會官網影音頁連結，V16）。

定期會一天一支，標題「彰化縣議會第20屆第8次定期會(115年10月06日)」（少數沒有日期），說明欄列出當天議程與質詢議員：
「日期：115年10月06日 議程： 縣政質詢 莊陞漢議員 許雅琳議員 …」。只收說明欄議程有「縣政質詢」、列有議員的影片；
影片掛給說明欄列名的每位議員，沒有個人起點，頁面寫「當天質詢議員…，未細分到個人」。
議事錄已刊出的日期（cha_book 找得到當天質詢名單），議事錄顯示當天沒有口頭質詢（沒有發言標籤或只講一兩句改書面）的人
不掛影片，也不列在當天質詢議員；議事錄沒有的日期（第 3 次定期會掃描檔、第 7 次定期會以後未刊出）照說明欄名單，
可能包含當天改提書面質詢的議員（頁面說明）。
說明欄註明「非經當事人同意不得錄製剪輯播放」：只放 YouTube 連結，不下載、不剪輯、不嵌入（V16 已定案第 4 點）。

清單用 yt-dlp 讀「影片」分頁（--flat-playlist、zh-TW，同 kin_videos；直播分頁是同一天的直播重複，不收），
說明欄讀各支 watch 頁的 shortDescription（/watch 不在 YouTube robots 禁止清單），只快取說明文字：data/cache/cha/desc/<id>.txt。
只寫給 cha_book 的對象；姓名以 etl.match 的漢字正規化對全部彰化縣議員名錄，同名或對不到的不收（印 log）。
自我檢查：python3 -m etl.sources.cha_videos [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB；
另比對議事錄同一天的質詢名單，印出差異）；加 --fetch 先更新快取
"""
import json
import re
import subprocess
import sys
import time
from collections import Counter

from etl.db import upsert_fact
from etl.fetch import UA, get, now_utc
from etl.sources.cha_book import CACHE, NAME_VARIANTS, OFFICE, TERM, cha_roster
from etl.sources.nwt_book import resolve, targets

CHANNEL = "https://www.youtube.com/channel/UCNWh1ZPg_dkTiDSitjVLrrQ/videos"
MIN_INTERVAL = 1.2
TITLE = re.compile(rf"^彰化縣議會第{TERM}屆第(\d+)次定期會(?:\s*\(\s*(\d+)年(\d+)月(\d+)日\s*\))?\s*$")
DESC_DATE = re.compile(r"日\s*期[：:]\s*(\d+)年(\d+)月(\d+)日")  # 早期說明欄寫「日 期」「議 程」
DESC_AGENDA = re.compile(r"議\s*程")
DESC_NAME = re.compile(r"^\s*([一-鿿]{2,4})議員\s*$", re.M)
# 說明欄錯字的顯示更正（人工審閱，只改顯示的「當天質詢議員」名單，不據以掛影片）：
# 0TRyR1fsW-w（2023-11-08）寫「詹婉惠」，名錄只有詹琬惠，議事錄電子書第 1343 頁影像為「詹議員琬惠」
DISPLAY_FIX = {("2023-11-08", "詹婉惠"): "詹琬惠"}
SHORT_DESC = re.compile(r'"shortDescription":("(?:[^"\\]|\\.)*")')


def fetch_list():
    out = subprocess.run(["yt-dlp", "--no-update", "--flat-playlist", "--sleep-requests", "1.2", "--user-agent", UA,
                          "--extractor-args", "youtube:lang=zh-TW", "--print", "%(id)s\t%(title)s", CHANNEL],
                         capture_output=True, check=True, text=True).stdout
    if not out.strip():
        raise ValueError("彰化 YouTube 影片分頁沒有影片")
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "yt_videos.tsv").write_text(out, encoding="utf-8")


def load_items():
    """→ [{video_id, nth, title}]：第 20 屆定期會的影片。"""
    out = []
    for line in (CACHE / "yt_videos.tsv").read_text(encoding="utf-8").splitlines():
        vid, _, title = line.partition("\t")
        m = TITLE.match(title.strip())
        if m:
            out.append({"video_id": vid, "nth": int(m.group(1)), "title": title.strip()})
    return out


def description(video_id, fetch_missing=True):
    path = CACHE / "desc" / f"{video_id}.txt"
    if not path.exists():
        if not fetch_missing:
            return None
        page = get(video_url(video_id)).decode("utf-8")
        time.sleep(MIN_INTERVAL)
        m = SHORT_DESC.search(page)
        if not m:
            raise ValueError(f"彰化 YouTube {video_id} 讀不到說明欄")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.loads(m.group(1)), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def parse_description(text):
    """說明欄 → {date, names}；議程不是縣政質詢、沒有日期或沒有列議員回 None。"""
    m = DESC_DATE.search(text or "")
    agenda = DESC_AGENDA.split(text or "", 1)[-1]
    if not m or "縣政質詢" not in agenda:
        return None
    names = list(dict.fromkeys(DESC_NAME.findall(agenda)))
    if not names:
        return None
    y, mo, d = (int(x) for x in m.groups())
    return {"date": f"{y + 1911}-{mo:02d}-{d:02d}", "names": names}


def videos(items, descs, covered=(), skipped=()):
    """covered：議事錄有質詢名單的日期；skipped：{(日期, 姓名)} 議事錄顯示當天沒有口頭質詢的人，從名單拿掉。"""
    out = []
    for it in items:
        meta = parse_description(descs.get(it["video_id"]))
        if not meta:
            continue
        book = meta["date"] in covered
        names = [n for n in meta["names"] if not (book and (meta["date"], n.translate(NAME_VARIANTS)) in skipped)]
        if names:
            shown = [DISPLAY_FIX.get((meta["date"], n), n).translate(NAME_VARIANTS) for n in names]
            out.append({**it, **meta, "names": names, "shown": shown, "listed_by": "議事錄" if book else "影片說明欄",
                        "session": f"第{TERM}屆第{it['nth']}次定期會"})
    return sorted(out, key=lambda v: (v["date"], v["video_id"]))


def assign(vs, roster, pids, log=print):
    out = {}
    for v in vs:
        for name in v["names"]:
            pid, why = resolve(name.translate(NAME_VARIANTS), roster)
            if not pid:
                log(f"cha_videos：{v['date']} {name}：{why}，不收")
            elif pid in pids:
                out.setdefault(pid, []).append(v)
    return out


def video_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def book_days(conn):
    """議事錄快取 → (有質詢名單的日期, {(日期, 姓名)} 名單上當天沒有口頭質詢的人)。不連網。"""
    from etl.sources import cha_book
    books = cha_book.load_books(refresh=False)
    texts = {b["id"]: cha_book.book_pages(b["id"]) for b in books if b["id"] not in cha_book.SKIP_BOOKS}
    _, covered, skipped, _ = cha_book.collect(books, texts, cha_book.roster_names(conn), log=lambda s: None)
    return covered, skipped


def build(conn, items, descs, log=print, book=None):
    ts = targets(conn, OFFICE)
    roster = cha_roster(conn)
    pids = {t["person_id"] for t in ts if resolve(t["name"].translate(NAME_VARIANTS), roster)[0] == t["person_id"]}
    covered, skipped = book_days(conn) if book is None else book
    vs = videos(items, descs, covered, skipped)
    return ts, vs, assign(vs, roster, pids, log)


def write_videos(conn, by_pid, fetched_at):
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'chavideo:%'")}
    current = set()
    for pid, vs in by_pid.items():
        for v in vs:
            k = f"chavideo:{v['video_id']}:{pid}"
            current.add(k)
            upsert_fact(conn, k, pid, "interpellation", {
                "title": "縣政質詢當天議事影片", "doc_type": "縣政質詢", "dept": None, "term": TERM, "session": v["session"],
                "councillors": v["shown"], "group_size": len(v["shown"]), "video_id": v["video_id"], "whole": True, "day": True,
                "listed_by": v["listed_by"],
            }, video_url(v["video_id"]), fetched_at, date=v["date"])
    stale = known - current
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    return len(current), len(stale)


def run(conn):
    fetch_list()
    items = load_items()
    descs = {it["video_id"]: description(it["video_id"]) for it in items}
    logs = Counter()
    ts, vs, by_pid = build(conn, items, descs, lambda s: logs.update([s]))
    for line, n in sorted(logs.items()):
        print(f"{line}（{n} 次）" if n > 1 else line)
    n, stale = write_videos(conn, by_pid, now_utc())
    print(f"cha_videos：第 20 屆定期會影片 {len(items)} 支，縣政質詢 {len(vs)} 支；對象 {len(ts)} 人，有影片 {len(by_pid)} 人，"
          f"影片 {n} 筆，刪除 {stale} 筆")


def compare_with_book(vs, entries, log=print):
    """同一天的議事錄質詢名單（cha_book 收錄的場次）與影片說明欄的議員名單互相比對，只印差異。"""
    book = {}
    for e in entries:
        book.setdefault(e["date"], set()).add(e["name"].translate(NAME_VARIANTS))
    for v in vs:
        if v["date"] in book:
            names = {n.translate(NAME_VARIANTS) for n in v["names"]}
            only_book, only_video = book[v["date"]] - names, names - book[v["date"]]
            if only_book or only_video:
                log(f"  {v['date']}：只在議事錄 {sorted(only_book)}；只在影片說明 {sorted(only_video)}")
    days = {v["date"] for v in vs}
    missing = sorted(d for d in book if d not in days)
    if missing:
        log(f"  議事錄有質詢、影片沒有對到的日期：{missing}")


def check(samples=()):
    from etl.sources import cha_book
    from etl.sources.nwt_book import dump_conn
    items = load_items()
    descs = {it["video_id"]: description(it["video_id"], fetch_missing=False) for it in items}
    logs = []
    conn = dump_conn()
    ts, vs, by_pid = build(conn, items, descs, logs.append)
    for line, n in sorted(Counter(logs).items()):
        print(" ", line, f"（{n} 次）" if n > 1 else "")
    nodesc = [it["video_id"] for it in items if descs[it["video_id"]] is None]
    print(f"第 20 屆定期會影片 {len(items)} 支（說明欄未快取 {len(nodesc)}）；縣政質詢 {len(vs)} 支、{len({v['date'] for v in vs})} 天；"
          f"有影片 {len(by_pid)} 人 {sum(map(len, by_pid.values()))} 筆")
    print("每會期支數：", sorted(Counter(v["nth"] for v in vs).items()))
    books = cha_book.load_books(refresh=False)
    texts = {b["id"]: cha_book.book_pages(b["id"]) for b in books if b["id"] not in cha_book.SKIP_BOOKS}
    _, entries, _ = cha_book.build(conn, books, texts, log=lambda s: None)
    print("議事錄名單（有本人發言者）與影片說明欄比對：")
    compare_with_book(vs, entries)
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in [p for p in names if any(s in names[p] for s in samples)]:
        for v in by_pid.get(pid, []):
            print(f"  {names[pid]} {v['date']} {'、'.join(v['names'])} {video_url(v['video_id'])}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        fetch_list()
        for it in load_items():
            description(it["video_id"])
            print(it["video_id"], flush=True)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
