"""雲林縣議會第 20 屆質詢影片：議事影音系統（msr.ylcc.gov.tw）依「發言議員」查詢的發言片段（V16）。

V16 已定案第 2、8 點：ws.yunlin.gov.tw（議事錄）被 Cloudflare 擋，不碰；影片只收 2025-05 以後（第 5 次定期會起才有「知識點」：
發言議員＋起點時間）。每位對象以 video_G.php?search=<姓名>&group=5（發言議員）查一次，再讀每支影片的播放頁 temp_3_G.php?id=<n>，
播放頁「發言議員」清單列出每段發言的議員姓名與起點時間。
歸屬一律以播放頁發言議員清單上的姓名，用 etl.match 的漢字正規化整名對雲林縣議員名錄，必須唯一且等於查詢對象；
查詢撈到、但播放頁清單沒有點名本人的影片不收（印 log）。官方誤植的姓名只照 NAME_FIX（人工審閱，影片 id＋寫法）更正。同一支影片本人有多段發言時合併成一筆，列出全部起點時間。
播放頁不讀網址的起點參數，所以連結到播放頁，起點時間以文字顯示。日期取播放頁的錄影時間；同日多支依錄影時刻（data.seq）新到舊。
查詢很慢（每次 40–150 秒），所以抓取與建檔分開：
  python3 -m etl.sources.yun_videos --fetch   只抓快取裡還沒有的查詢與播放頁（可續傳）；要更新查詢結果先刪 data/cache/yun/search/
  run(conn)（etl.run）只讀快取，不連網；快取缺任何一位對象的查詢就整批不寫（避免把舊 fact 當成過期刪掉）。
快取：data/cache/yun/。自我檢查：python3 -m etl.sources.yun_videos [姓名…]（只讀快取與 data/civic.sql）
"""
import html
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import UA, now_utc
from etl.sources.nwt_book import key, resolve, roster_index, targets

OFFICE = "yun_councilor"
TERM = 20
SINCE = "2025-05-01"  # V16 已定案第 8 點
HOST = "http://msr.ylcc.gov.tw/portal/"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "yun"

ITEM = re.compile(r"id='prj_(\d+)'")
TOTAL = re.compile(r"總計\((\d+)\)")
TITLE = re.compile(r'id="video_title">\s*<font[^>]*>(.*?)</font>\s*<font[^>]*>\s*(\d{4}-\d\d-\d\d)[T ](\d\d):(\d\d):(\d\d)', re.S)
SPEAKER = re.compile(r"class='know_title'[^>]*title='([^']*)'>[^<]*</p><p class='time'[^>]*>\s*(\d\d:\d\d:\d\d)\s*</p>")
SESSION = re.compile(r"第20屆第([\d.]+)次(定期會|臨時會)")
# 播放頁發言議員姓名誤植的更正（人工審閱，只對列出的影片 id＋印出的寫法）：
# 第 5 次定期會（2025-05-14～06-12）的 4 支影片印「陳以辰」，名錄只有陳乙辰；陳乙辰本人的查詢從 2025-08-19 起才有、
# 第 5 次定期會一支都沒有，兩種寫法的日期不重疊；6587 教育委員會由她第一個發言，和她之後的教育委員會（13454、13625、16133）相同；
# 中選會 2022 全國縣市議員候選人與 2026 登記名單都沒有陳以辰。這幾支本人查詢撈不到，所以由更正表補進對象的影片。
NAME_FIX = {(6564, "陳以辰"): "陳乙辰", (6587, "陳以辰"): "陳乙辰", (6588, "陳以辰"): "陳乙辰", (6825, "陳以辰"): "陳乙辰"}


def search_url(name):
    q = {"search": name, "group": 5, "page_num": 500, "S_d": SINCE, "L_d": date.today().isoformat()}
    return f"{HOST}video_G.php?{urllib.parse.urlencode(q)}"


def play_url(vid):
    return f"{HOST}temp_3_G.php?id={vid}"


def parse_search(page):
    """查詢結果 → 影片 id（依頁面順序、去重）；頁面總計與列出的筆數不同（要翻頁）就 raise。"""
    ids = list(dict.fromkeys(int(i) for i in ITEM.findall(page)))
    total = TOTAL.search(page)
    if not total or int(total.group(1)) != len(ids):
        raise ValueError(f"雲林影音查詢結果總計 {total and total.group(1)} 與列出 {len(ids)} 筆不符")
    return ids


def parse_play(page):
    """播放頁 → {title, date, seq, session, speakers: [(姓名, 起點)]}；找不到標題或錄影時間回 None。"""
    m = TITLE.search(page)
    if not m:
        return None
    title, day, hh, mm, ss = m.groups()
    title = re.sub(r"\s+", "", html.unescape(title))
    s = SESSION.search(title)
    return {"title": title, "date": day, "seq": int(hh + mm + ss), "session": f"第{s.group(1)}次{s.group(2)}" if s else "",
            "speakers": [(re.sub(r"\s+", "", html.unescape(n)), t) for n, t in SPEAKER.findall(page)]}


# ---------- 抓取（只在 --fetch 時連網） ----------

_last = [0.0]


def fetch(url, timeout=200):
    """同一主機間隔 ≥ 1.1 秒，循序；查詢要 40–150 秒，所以逾時放寬到 200 秒。"""
    wait = 1.1 - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as resp:
            return resp.read()
    finally:
        _last[0] = time.monotonic()


def _save(path, url):
    """抓 url 存到 path（先寫暫存檔再改名，中斷不留半個檔）；已存在就跳過。失敗印 log、回 False。"""
    if path.exists():
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    try:
        body = fetch(url)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
        print(f"  失敗 {url}：{e}（{time.monotonic() - t0:.0f} 秒）", flush=True)
        return False
    tmp = path.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.rename(path)
    print(f"  {path.relative_to(CACHE)} {len(body)} B（{time.monotonic() - t0:.0f} 秒）", flush=True)
    return True


def crawl(names):
    """查詢每位對象，再抓查詢結果裡每支影片的播放頁；已快取的都跳過，可重複執行續傳。"""
    failed = 0
    for i, name in enumerate(names, 1):
        print(f"[{i}/{len(names)}] {name}", flush=True)
        path = CACHE / "search" / f"{name}.html"
        if not _save(path, search_url(name)):
            failed += 1
            continue
        for vid in parse_search(path.read_text(encoding="utf-8")):
            failed += not _save(CACHE / "play" / f"{vid}.html", play_url(vid))
    print(f"完成；失敗 {failed} 個請求（重跑 --fetch 會補抓）", flush=True)


# ---------- 建檔（只讀快取） ----------

def load(names):
    """→ ({姓名: [id]}, {id: 播放頁解析結果})；任何一位的查詢或任何一支播放頁沒有快取就 raise。"""
    searches = {}
    for name in names:
        path = CACHE / "search" / f"{name}.html"
        if not path.exists():
            raise ValueError(f"yun_videos：沒有 {name} 的查詢快取，先跑 python3 -m etl.sources.yun_videos --fetch")
        searches[name] = parse_search(path.read_text(encoding="utf-8"))
    plays = {}
    for vid in [v for ids in searches.values() for v in ids] + [v for v, _ in NAME_FIX]:
        p = CACHE / "play" / f"{vid}.html"
        if not p.exists():
            raise ValueError(f"yun_videos：沒有播放頁 id={vid} 的快取，先跑 --fetch")
        plays.setdefault(vid, parse_play(p.read_text(encoding="utf-8")))
    return searches, plays


# 程序委員會只排議程、閉會只是散會程序，不是問政，不列入
PROCEDURAL = ("程序委員會", "閉會")


def build(conn, searches, plays, log=print):
    """→ (targets, {person_id: [video]})；video 是播放頁解析結果加 id 與本人的起點時間 starts。"""
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    plays = {vid: p and {**p, "speakers": [(NAME_FIX.get((vid, n), n), s) for n, s in p["speakers"]]} for vid, p in plays.items()}
    for name in sorted({n for p in plays.values() if p for n, _ in p["speakers"]}):
        _, why = resolve(name, roster)
        if why:
            log(f"yun_videos：發言議員「{name}」{why}，不收")
    out = {}
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"yun_videos：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        vs = []
        fixed = [v for (v, _), real in NAME_FIX.items() if real == t["name"] and v in plays]
        for vid in dict.fromkeys(searches.get(t["name"], []) + fixed):
            p = plays[vid]
            if not p:
                log(f"yun_videos：id={vid} 播放頁格式不明，不收")
                continue
            if p["date"] < max(SINCE, t["since"]):
                continue
            if any(w in p["title"] for w in PROCEDURAL):
                continue
            starts = [s for n, s in p["speakers"] if resolve(n, roster)[0] == pid]
            if not starts:
                log(f"yun_videos：查詢 {t['name']} 撈到 id={vid}，播放頁發言議員沒有此人，不收")
                continue
            vs.append({**p, "id": vid, "starts": sorted(set(starts))})
        if vs:
            out[pid] = sorted(vs, key=lambda v: (v["date"], v["seq"], v["id"]))
    return ts, out


def write_videos(conn, by_pid, fetched_at):
    """每位議員每支影片一筆 fact，刪除這次不在結果裡的舊 fact。回傳 (筆數, 刪除筆數)。"""
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'yunvideo:%'")}
    current = set()
    for pid, items in by_pid.items():
        for v in items:
            k = f"yunvideo:{v['id']}:{pid}"
            current.add(k)
            upsert_fact(conn, k, pid, "interpellation", {
                "title": v["title"], "dept": v["session"], "term": TERM, "video_id": str(v["id"]),
                "starts": v["starts"], "seq": v["seq"],
            }, play_url(v["id"]), fetched_at, date=v["date"])
    stale = known - current
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    return len(current), len(stale)


def run(conn):
    ts = targets(conn, OFFICE)
    if not ts:
        raise ValueError("雲林縣議員名錄沒有參選 2026 的對象")
    searches, plays = load([t["name"] for t in ts])
    logs = set()
    ts, by_pid = build(conn, searches, plays, logs.add)
    for line in sorted(logs):
        print(line)
    n, stale = write_videos(conn, by_pid, now_utc())
    print(f"yun_videos：查詢 {len(searches)} 次、影片 {len(plays)} 支；對象 {len(ts)} 人，有紀錄 {len(by_pid)} 人，{n} 筆，刪除 {stale} 筆")


def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    conn = dump_conn()
    searches, plays = load([t["name"] for t in targets(conn, OFFICE)])
    logs = []
    ts, by_pid = build(conn, searches, plays, logs.append)
    for line in sorted(set(logs)):
        print(" ", line)
    print(f"影片 {len(plays)} 支；對象 {len(ts)} 人；有紀錄 {len(by_pid)} 人，{sum(map(len, by_pid.values()))} 筆")
    for t in ts:
        vs = by_pid.get(t["person_id"], [])
        print(f"  {t['name']}：{len(vs)} 筆" + (f"（{vs[0]['date']}～{vs[-1]['date']}）" if vs else ""))
        if t["name"] in samples:
            for v in vs:
                print(f"    {v['date']} {v['title']} 自 {'、'.join(v['starts'])} 起 {play_url(v['id'])}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        from etl.sources.nwt_book import dump_conn
        crawl([t["name"] for t in targets(dump_conn(), OFFICE)])
    else:
        check([a for a in sys.argv[1:] if not a.startswith("--")])
