"""基隆市議會第 20 屆市長施政總質詢影片：議事資訊站 vod.kmc.gov.tw（V16）。

stream2.php 取 csrf_token（帶 cookie），POST stream3.php 只送 s_session=第20屆（不帶姓名），一次取得本屆全部
市長施政總質詢影片（2026-10-14 實測 227 支，和逐人查詢 何淑萍、陳宜、呂美玲 的結果一致）。每支影片就是一位議員
（或一場聯合質詢）的質詢時段，連結是 Akamai 上的 mp4 直連（每支約 1.2 GB），沒有播放頁、不需 session。
早期檔名沒有姓名、檔名日期偶有誤植，姓名與日期一律取清單文字（連結的 title 屬性與卡片文字），不看檔名。
黨團聯合質詢（「民進黨團聯合_甲議員,乙議員」「甲議員暨跨黨派政團聯合-乙議員」）列在每位列名議員名下，標題註明聯合質詢；
註記改以書面總質詢的場次（2024-06-03 北寧路坍方）不確定列名者是否在影片中質詢，不收（印 log）。
著作權聲明同意連結並標示「基隆市議會」：只放連結，不下載、不轉存。

只寫給有基隆市議員任職 fact 且有 2026 candidacy 的人，姓名以 etl.match 的漢字正規化整名對全部基隆市議員名錄
（不做子字串比對），同名或對不到的不收（印 log）；同一網址同一人只收一次。
自我檢查：python3 -m etl.sources.kee_videos [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import html
import http.cookiejar
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import UA, now_utc
from etl.sources.nwt_book import resolve, roster_index, targets

OFFICE = "kee_councilor"
TERM = 20
HOST = "https://vod.kmc.gov.tw"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "kee"
LISTING = CACHE / f"stream3_{TERM}.html"
DOC_TYPE = "市長施政總質詢"

ROW = re.compile(r'<a href="(https://[^"]+\.mp4)"[^>]*\btitle="([^"]*)">.*?<div class="text1">(.*?)</div>', re.S)
SESSION = re.compile(rf"^第{TERM}屆第(\d+)次定期會$")
NAME = re.compile(r"[\u3400-\u9fff]{2,4}")


def fetch_listing():
    """GET stream2.php（csrf_token＋cookie）→ POST stream3.php（只限屆別），原始回應存快取，回傳清單 HTML。"""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    opener.addheaders = [("User-Agent", UA)]
    with opener.open(f"{HOST}/stream2.php", timeout=60) as r:
        page = r.read().decode("utf-8")
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "stream2.html").write_text(page, encoding="utf-8")
    m = re.search(r'name="csrf_token" value="([^"]+)"', page)
    if not m:
        raise ValueError("基隆 stream2.php 找不到 csrf_token")
    form = {"csrf_token": m.group(1), "s_session": f"第{TERM}屆", "s_appoint": "", "s_times": "", "s_date": "",
            "s_time": "", "s_key": ""}
    time.sleep(1.2)  # 同一主機間隔 ≥ 1.1 秒
    req = urllib.request.Request(f"{HOST}/stream3.php", data=urllib.parse.urlencode(form).encode(),
                                 headers={"Referer": f"{HOST}/stream2.php"})
    with opener.open(req, timeout=60) as r:
        listing = r.read().decode("utf-8")
    LISTING.write_text(listing, encoding="utf-8")
    return listing


def parse_listing(page):
    """清單 HTML → [{url, label, date, time, nth, session, kind}]（url 已百分比編碼；label 是 title 屬性的議員文字）。"""
    out = []
    for href, title, text in ROW.findall(page):
        lines = [html.unescape(x).strip() for x in re.split(r"<br\s*/?>", text)]
        if len(lines) < 3:
            raise ValueError(f"基隆影片卡片格式未知：{text!r}")
        dt = re.fullmatch(r"(\d{4}-\d\d-\d\d) (\d\d:\d\d)", lines[0])
        m = SESSION.match(lines[1])
        if not dt or not m:
            raise ValueError(f"基隆影片日期或會期格式未知：{lines[:2]!r}")
        label = re.sub(r"\s*\(另開新視窗\)\s*$", "", html.unescape(title)).strip()
        out.append({"url": urllib.parse.quote(html.unescape(href), safe=":/"), "label": label,
                    "date": dt.group(1), "time": dt.group(2), "nth": int(m.group(1)), "session": lines[1], "kind": lines[2]})
    return out


def parse_label(label):
    """「何淑萍議員」「楊秀玉副議長」「民進黨團聯合_施偉政議員、許睿慈議員」「林旻勳議員暨跨黨派政團聯合_張耿輝議員,呂美玲議員」
    → {names, joint, caucus}。註記改以書面質詢、沒有姓名或有不像姓名的片段時 raise ValueError（不猜）。"""
    if "書面" in label:
        raise ValueError(f"註記改以書面質詢，不確定列名者是否在影片中質詢：{label!r}")
    joint = "聯合" in label
    caucus = "民進黨團" if "進黨" in label else "跨黨派政團" if "跨黨派" in label else ""
    body = re.sub(r"民*進黨團?聯合|暨跨黨派政團聯合", "、", label)  # 官方偶有「民民進黨團聯合」誤植
    names = []
    for tok in re.split(r"[、,，_\-\s]+", body):
        name = re.sub(r"(副議長|議長|議員|議)$", "", tok)  # 「吳驊珈議」漏了「員」
        if not name:
            continue
        if not NAME.fullmatch(name):
            raise ValueError(f"基隆影片議員文字無法拆成姓名：{label!r}")
        if name not in names:
            names.append(name)
    if not names:
        raise ValueError(f"基隆影片沒有議員姓名：{label!r}")
    return {"names": names, "joint": joint, "caucus": caucus}


def assign(items, roster, log=print):
    """→ {person_id: [video]}：每支第 20 屆市長施政總質詢影片，分給能唯一對到名錄的列名議員（同一網址每人一次）。"""
    out = {}
    for it in items:
        if it["kind"] != DOC_TYPE:
            log(f"kee_videos：{it['date']} 不是{DOC_TYPE}（{it['kind']}），不收")
            continue
        try:
            meta = parse_label(it["label"])
        except ValueError as e:
            log(f"kee_videos：{it['date']} {it['time']} {e}，不收")
            continue
        v = {**it, **meta}
        for name in meta["names"]:
            pid, why = resolve(name, roster)
            if not pid:
                log(f"kee_videos：{it['date']} {it['time']} {name}：{why}")
                continue
            out.setdefault(pid, {}).setdefault(it["url"], v)
    return {pid: sorted(vs.values(), key=lambda v: (v["date"], v["time"], v["url"])) for pid, vs in out.items()}


def build(conn, items, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    by_pid = assign(items, roster, log)
    out = {}
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"kee_videos：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        vs = [v for v in by_pid.get(pid, []) if v["date"] >= t["since"]]  # 遞補者從上任起算
        if vs:
            out[pid] = vs
    return ts, out


def title_of(v):
    if not v["joint"]:
        return DOC_TYPE
    return f"{DOC_TYPE}（{v['caucus']}聯合質詢：{'、'.join(v['names'])}）"


def write_videos(conn, by_pid, fetched_at):
    """每位議員每支影片一筆 fact，刪除這次不在結果裡的舊 fact。回傳 (筆數, 刪除筆數)。"""
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'keevideo:%'")}
    current = set()
    for pid, videos in by_pid.items():
        for v in videos:
            video_id = urllib.parse.unquote(v["url"].rsplit("/", 1)[1])
            k = f"keevideo:{video_id}:{pid}"
            current.add(k)
            upsert_fact(conn, k, pid, "interpellation", {
                "title": title_of(v), "doc_type": DOC_TYPE, "dept": None, "term": TERM, "session": v["session"],
                "councillors": v["names"], "group_size": len(v["names"]), "joint": v["joint"], "time": v["time"],
                "video_id": video_id, "clip": True, "mp4": True,
            }, v["url"], fetched_at, date=v["date"])
    stale = known - current
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    return len(current), len(stale)


def run(conn):
    items = parse_listing(fetch_listing())
    if not items:
        raise ValueError("基隆影片查詢沒有結果")
    logs = set()
    ts, by_pid = build(conn, items, logs.add)
    for line in sorted(logs):
        print(line)
    n, stale = write_videos(conn, by_pid, now_utc())
    print(f"kee_videos：影片 {len(items)} 支；對象 {len(ts)} 人，有影片 {len(by_pid)} 人，影片 {n} 筆，刪除 {stale} 筆")


def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    items = parse_listing(LISTING.read_text(encoding="utf-8"))
    logs = []
    ts, by_pid = build(dump_conn(), items, logs.append)
    for line in sorted(set(logs)):
        print(" ", line)
    print(f"快取影片 {len(items)} 支；對象 {len(ts)} 人；有影片 {len(by_pid)} 人，影片 {sum(map(len, by_pid.values()))} 筆")
    for t in ts:
        vs = by_pid.get(t["person_id"], [])
        print(f"  {t['name']}：{len(vs)} 支（個人 {sum(not v['joint'] for v in vs)}、聯合 {sum(v['joint'] for v in vs)}）")
        if t["name"] in samples:
            for v in vs:
                print(f"    {v['date']} {v['time']} {v['session']} {title_of(v)} {v['url']}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        fetch_listing()
    check([a for a in sys.argv[1:] if not a.startswith("--")])
