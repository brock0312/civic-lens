"""澎湖縣議會第 20 屆縣政總質詢影片：官方 YouTube @penghucc（V16）。

議會官網首頁「議會線上直播」「議會影音隨選」連到 https://www.youtube.com/@penghucc（2026-10-15 重新確認），以此認定為官方頻道。
直播分頁一場（上午／下午）一支，從第 5 次定期會（2025-05）起，縣政總質詢的標題列出質詢議員（1–2 人）：
「[1150924AM]蘇育德議員縣政總質詢」「[1151001AM]宋昀芝議員、藍凱元副議長縣政總質詢」。
更早的第 20 屆影片標題沒有姓名（「第N次會議」），本站只收 2025-05-01 以後（V16 已定案第 8 點）；第 19 屆的舊格式標題不解析。
審查委員會場（「[1150603AM]第一、二審查委員會縣政總質詢」）標題沒有個人姓名，但說明欄依委員會列出排定時段：
「第一審查委員會：」下一行一位「09：00－09：20　召集人許育愷議員」；每位列名議員一筆，data.slots 是本人的排定時段
（說明欄排定時間，實際起點可能不同）。時段後不是姓名的（如「議長總結」）不收；說明欄沒有排定議員的影片不收（印 log）。
日期取標題的民國日期（直播分頁的 flat-playlist 沒有上傳日期）；同日依 data.seq（上午 0、下午 10000，再加本人排定起點 HHMM）排序。
會期取各「第20屆第N次定期會」播放清單的成員，不在任何定期會清單的影片會期留空（印 log）。
標題列兩位議員時掛給兩人，標示同場質詢議員（data.joint），本人時段未標示；只放 YouTube 連結，不下載。
姓名以 etl.match 的漢字正規化整名對全部澎湖縣議員任職 fact（不做子字串或模糊比對），同名或對不到的不收（印 log）；
只寫給有 2026 candidacy 的人，且只收任職起日以後的影片。莊光大（遞補）沒有任職 fact，標題列到他時他那份不收。
快取：data/cache/pen/（yt_streams.tsv、yt_playlists.tsv、playlist_<id>.tsv、desc/<id>.txt）。run() 每次重抓清單（yt-dlp 約 1 分鐘），
說明欄只抓還沒快取的（審查委員會場，watch 頁 shortDescription，間隔 1.2 秒）。
自我檢查：python3 -m etl.sources.pen_videos [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import UA, get, now_utc
from etl.sources.nwt_book import resolve, roster_index, targets

OFFICE = "pen_councilor"
TERM = 20
SINCE = "2025-05-01"  # V16 已定案第 8 點：只列 2025-05 以後
CHANNEL = "https://www.youtube.com/@penghucc"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "pen"
DOC_TYPE = "縣政總質詢"

TITLE = re.compile(r"^\[(\d{3})(\d\d)(\d\d)(AM|PM)\](.+)縣政總質詢$")
SPEAKER = re.compile(r"^([㐀-鿿]{2,4}?)(副議長|議長|議員)$")
SESSION_LIST = re.compile(rf"^第{TERM}屆第0?(\d+)次定期會$")
COMMITTEE_TITLE = re.compile(r"^第[一二三四五六七八九十、\d]+審查委員會$")
COMMITTEE_HEAD = re.compile(r"^(第[一二三四五六七八九十\d]+審查委員會)\s*[：:]?$")
SLOT = re.compile(r"^(\d{1,2})\s*[：:]\s*(\d\d)\s*[－—–\-~～]\s*(\d{1,2})\s*[：:]\s*(\d\d)\s+(.+)$")
SHORT_DESC = re.compile(r'"shortDescription":("(?:[^"\\]|\\.)*")')
MIN_INTERVAL = 1.2


def _ytdlp(url):
    return subprocess.run(["yt-dlp", "--no-update", "--flat-playlist", "--sleep-requests", "1.2", "--user-agent", UA,
                           "--extractor-args", "youtube:lang=zh-TW", "--print", "%(id)s\t%(title)s", url],
                          capture_output=True, check=True, text=True).stdout


def fetch_lists():
    """直播分頁、播放清單列表、第 20 屆各定期會播放清單 → 快取。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    streams = _ytdlp(f"{CHANNEL}/streams")
    if not streams.strip():
        raise ValueError("澎湖 YouTube 直播分頁沒有影片")
    (CACHE / "yt_streams.tsv").write_text(streams, encoding="utf-8")
    playlists = _ytdlp(f"{CHANNEL}/playlists")
    (CACHE / "yt_playlists.tsv").write_text(playlists, encoding="utf-8")
    for pl, _ in session_playlists():
        (CACHE / f"playlist_{pl}.tsv").write_text(_ytdlp(f"https://www.youtube.com/playlist?list={pl}"), encoding="utf-8")


def _rows(path):
    return [tuple(line.split("\t", 1)) for line in path.read_text(encoding="utf-8").splitlines() if "\t" in line]


def session_playlists():
    """→ [(playlist_id, 定期會次)]。"""
    out = []
    for pl, title in _rows(CACHE / "yt_playlists.tsv"):
        m = SESSION_LIST.match(title.strip())
        if m:
            out.append((pl, int(m.group(1))))
    return out


def load_sessions():
    """→ {video_id: 定期會次}（只讀快取）。"""
    out = {}
    for pl, nth in session_playlists():
        path = CACHE / f"playlist_{pl}.tsv"
        if path.exists():
            out.update({vid: nth for vid, _ in _rows(path)})
    return out


def parse_title(title):
    """標題 → {date, pm, names, committee}；不是縣政總質詢回 None。
    審查委員會場（「第一、二審查委員會縣政總質詢」）committee 是委員會文字、names 空（姓名在說明欄）；
    其他場次的每個片段都要是「姓名＋職稱」，否則 raise ValueError（不猜）。"""
    m = TITLE.match(title.strip())
    if not m:
        return None
    y, mo, d, ampm, body = m.groups()
    meta = {"date": f"{int(y) + 1911}-{mo}-{d}", "pm": ampm == "PM", "names": [], "committee": None}
    if COMMITTEE_TITLE.match(body):
        return {**meta, "committee": body}
    for tok in body.split("、"):
        s = SPEAKER.match(tok.strip())
        if not s:
            raise ValueError(f"標題沒有可辨識的議員姓名：{title.strip()!r}")
        if s.group(1) not in meta["names"]:
            meta["names"].append(s.group(1))
    return meta


def parse_description(text, log=print):
    """審查委員會場的說明欄 → [{committee, start, end, name}]（排定時段，依說明欄順序）。
    「第一審查委員會：」標題下的「09：00－09：20　召集人許育愷議員」一行一筆；時段後不是「[召集人|副召集人]姓名＋職稱」的行
    （如「議長總結」）不收，沒有「總結」字樣的另印 log。"""
    out, committee = [], None
    for line in (text or "").splitlines():
        line = line.strip()
        h = COMMITTEE_HEAD.match(line)
        if h:
            committee = h.group(1)
            continue
        m = SLOT.match(line)
        if not m:
            continue
        h1, m1, h2, m2, who = m.groups()
        s = SPEAKER.match(re.sub(r"^(副召集人|召集人)", "", who.strip()))
        if not s or not committee:
            if "總結" not in who:
                log(f"pen_videos：說明欄時段無法辨識議員：{line!r}")
            continue
        out.append({"committee": committee, "start": f"{h1}:{m1}", "end": f"{h2}:{m2}", "name": s.group(1)})
    return out


def description(video_id, fetch_missing=False):
    """watch 頁的 shortDescription（/watch 不在 YouTube robots 禁止清單），只快取說明文字：data/cache/pen/desc/<id>.txt。"""
    path = CACHE / "desc" / f"{video_id}.txt"
    if not path.exists():
        if not fetch_missing:
            return None
        page = get(video_url(video_id)).decode("utf-8")
        time.sleep(MIN_INTERVAL)
        m = SHORT_DESC.search(page)
        if not m:
            raise ValueError(f"澎湖 YouTube {video_id} 讀不到說明欄")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.loads(m.group(1)), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def load_items(log=print, fetch_missing=False):
    """快取 → [{video_id, title, date, pm, names, nth, committee, slots: {姓名: [slot]}}]：2025-05 以後、列有議員的縣政總質詢
    （標題列名，或審查委員會場的說明欄排定時段）。fetch_missing：說明欄沒快取的才抓。"""
    sessions = load_sessions()
    out, seen = [], set()
    for vid, title in _rows(CACHE / "yt_streams.tsv"):
        if vid in seen:
            continue
        seen.add(vid)
        try:
            meta = parse_title(title)
        except ValueError as e:
            if f"{int(TITLE.match(title.strip()).group(1)) + 1911}" >= SINCE[:4]:  # 只列收錄期間附近的，舊屆次不吵
                log(f"pen_videos：{vid} {e}，不收")
            continue
        if not meta or meta["date"] < SINCE:
            continue
        slots = {}
        if meta["committee"]:
            text = description(vid, fetch_missing)
            if text is None:
                log(f"pen_videos：{vid} {title.strip()} 說明欄未快取，不收")
                continue
            for slot in parse_description(text, log):
                slots.setdefault(slot["name"], []).append(slot)
            if not slots:
                log(f"pen_videos：{vid} {title.strip()} 說明欄沒有排定質詢議員，不收")
                continue
            meta = {**meta, "names": list(slots)}
        if vid not in sessions:
            log(f"pen_videos：{vid} {title.strip()} 不在第 {TERM} 屆定期會播放清單，會期留空")
        out.append({"video_id": vid, "title": title.strip(), **meta, "nth": sessions.get(vid), "slots": slots})
    return out


def seq_of(v, name):
    """同日排序：上午／下午，再依本人排定時段起點（標題列名的場次沒有時段，排在該半天最前）。"""
    first = v["slots"].get(name, [{"start": "00:00"}])[0]["start"]
    return int(v["pm"]) * 10000 + int(first.replace(":", ""))


def build(conn, items, log=print):
    """→ (targets, {person_id: [item＋name、seq]})：name 是標題或說明欄上的本人姓名。"""
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    since = {}
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"pen_videos：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        since[pid] = t["since"]
    out = {}
    for it in items:
        for name in it["names"]:
            pid, why = resolve(name, roster)
            if not pid:
                log(f"pen_videos：{it['date']} {it['title']}：{name} {why}，不收")
            elif pid in since and it["date"] >= since[pid]:
                out.setdefault(pid, []).append({**it, "name": name, "seq": seq_of(it, name)})
    return ts, {pid: sorted(vs, key=lambda v: (v["date"], v["seq"], v["video_id"])) for pid, vs in out.items()}


def video_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def fact_data(v):
    half = "下午" if v["pm"] else "上午"
    base = {"doc_type": DOC_TYPE, "dept": f"第{v['nth']}次定期會" if v["nth"] else None, "term": TERM,
            "session": f"第{TERM}屆第{v['nth']}次定期會" if v["nth"] else None, "video_id": v["video_id"], "seq": v["seq"]}
    slots = v["slots"].get(v["name"])
    if slots:  # 審查委員會場：說明欄的排定時段，影片有多位議員、各有時段
        committees = "、".join(dict.fromkeys(s["committee"] for s in slots))
        return {**base, "title": f"{committees}{DOC_TYPE}（{half}）", "committee": committees,
                "slots": [f"{s['start']}–{s['end']}" for s in slots]}
    return {**base, "title": f"{DOC_TYPE}（{half}）", "councillors": v["names"], "group_size": len(v["names"]),
            "joint": len(v["names"]) > 1, "whole": True}


def write_videos(conn, by_pid, fetched_at):
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'penvideo:%'")}
    current = set()
    for pid, vs in by_pid.items():
        for v in vs:
            k = f"penvideo:{v['video_id']}:{pid}"
            current.add(k)
            upsert_fact(conn, k, pid, "interpellation", fact_data(v), video_url(v["video_id"]), fetched_at, date=v["date"])
    stale = known - current
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    return len(current), len(stale)


def _report(build_logs):
    for line, n in sorted(Counter(build_logs).items()):
        print(f"{line}（{n} 次）" if n > 1 else line)


def run(conn):
    fetch_lists()
    logs = []
    items = load_items(logs.append, fetch_missing=True)
    ts, by_pid = build(conn, items, logs.append)
    _report(logs)
    n, stale = write_videos(conn, by_pid, now_utc())
    print(f"pen_videos：2025-05 以後列名的縣政總質詢影片 {len(items)} 支；對象 {len(ts)} 人，有影片 {len(by_pid)} 人，"
          f"影片 {n} 筆，刪除 {stale} 筆")


def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    logs = []
    items = load_items(logs.append)
    ts, by_pid = build(dump_conn(), items, logs.append)
    _report(logs)
    print(f"列名的縣政總質詢影片 {len(items)} 支（{min(i['date'] for i in items)}～{max(i['date'] for i in items)}）；"
          f"對象 {len(ts)} 人；有影片 {len(by_pid)} 人 {sum(map(len, by_pid.values()))} 筆")
    print("每會期支數：", sorted(Counter(i["nth"] for i in items).items(), key=lambda x: x[0] or 0))
    for t in ts:
        vs = by_pid.get(t["person_id"], [])
        print(f"  {t['name']}：{len(vs)} 支（標題同場 {sum(len(v['names']) > 1 and not v['slots'] for v in vs)}、"
              f"審查委員會 {sum(bool(v['slots']) for v in vs)}）")
        if t["name"] in samples:
            for v in vs:
                print(f"    {v['date']} 第{v['nth']}次 {fact_data(v)['title']} {fact_data(v).get('slots', '')} {video_url(v['video_id'])}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        fetch_lists()
        load_items(lambda s: None, fetch_missing=True)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
