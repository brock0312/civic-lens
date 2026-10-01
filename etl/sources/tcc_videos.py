"""臺北市議會第 14 屆口頭質詢影片（M5）。來源：議事影音系統 tccvideo.tcc.gov.tw 的 JSON 端點。

只收市政總質詢與部門質詢。影片只切到「質詢組」，沒有切到個人：每位有對照的議員、每個分段各寫一筆，
深連結到該組起播位置（見 docs/validation/V3-council-video.md）。
"""
import json
import re
import time
import urllib.parse

from etl.db import upsert, upsert_fact
from etl.fetch import get_json, now_utc
from etl.sources.tcc_councilors import TERM_START, load_identity

BASE = "https://tccvideo.tcc.gov.tw"
MIN_INTERVAL = 1.0  # 秒；禮貌爬取
# GetList 不帶 cookie 回傳全站影片（V3 實測 5,148 筆，2010-12-25 起）。這是觀察到的行為，不是承諾：
# 若改成預設只回近期影片，筆數會掉到幾十筆。存檔只增不減，所以用略低於實測值的固定下限擋；
# 另外要求範圍內的影片不少於 DB 已有的影片（見 run）。
MIN_LIST_TOTAL = 5000

TITLE = re.compile(r"^第(\d+)屆(第\d+次定期大會)(?:(市政總質詢)|(.+)部門質詢)$")
SEGMENT = re.compile(r"^第(\d+)(?:質詢)?組：(.+)$")
SEEKABLE = re.compile(r"^第\d+組")  # 「第N質詢組」的分段 GetInPoint 回 0，&num= 無效（V3 §1.3）


_last = 0.0


def get(path):
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return get_json(BASE + path)
    finally:
        _last = time.monotonic()


def parse_list(items):
    """GetList → 第 14 屆市政總質詢與部門質詢影片 [{video_id, date, list_title, session, doc_type, dept}]。"""
    out = []
    for it in items:
        if it["StartTime"][:10] < TERM_START or it["Type"] != "大會":
            continue
        if "市政總質詢" not in it["Title"] and "部門質詢" not in it["Title"]:
            continue
        m = TITLE.match(it["Title"])
        if not m:
            raise ValueError(f"口頭質詢影片標題格式未知：{it['Title']!r}")
        if m.group(1) != "14":
            continue
        ids = urllib.parse.parse_qs(urllib.parse.urlparse(it["Url"]).query).get("id")
        if not ids:
            raise ValueError(f"影片網址沒有 id：{it['Url']!r}")
        out.append({
            "video_id": ids[0],
            "date": it["StartTime"][:10],
            "list_title": it["Title"],
            "session": f"第14屆{m.group(2)}",
            "doc_type": "市政總質詢" if m.group(3) else "部門質詢",
            "dept": m.group(4),
        })
    return out


def parse_segments(segments):
    """Segment_Read → [{group, councillors, start_sec, seekable}]；一個分段＝一個實際有質詢的組。

    同一組偶有重複分段（2025-11-06 教育部門第1組出現兩次，起點差 0.4 秒）：合併成一筆，取較早的起點。
    """
    out = {}
    for s in segments:
        name = s["Name"].strip()
        m = SEGMENT.match(name)
        if not m:
            raise ValueError(f"分段名稱格式未知：{name!r}")
        seg = {
            "group": int(m.group(1)),
            "councillors": [n.strip() for n in m.group(2).split(",") if n.strip()],
            "start_sec": s["VideoTime"],
            "seekable": bool(SEEKABLE.match(name)),
        }
        prev = out.get(seg["group"])
        if prev and (prev["councillors"], prev["seekable"]) != (seg["councillors"], seg["seekable"]):
            raise ValueError(f"第{seg['group']}組有兩個名單不同的分段：{prev} vs {seg}")
        if not prev or seg["start_sec"] < prev["start_sec"]:
            out[seg["group"]] = seg
    return list(out.values())


def video_url(video_id, group=None):
    return f"{BASE}/Front/VideoContent/Index?id={video_id}" + (f"&num={group}" if group is not None else "")


def write_video(conn, video, segments, identity, fetched_at):
    """每位有對照的議員×每個分段一筆；沒對照的（已離職議員）跳過。回傳寫入筆數。"""
    n = 0
    for seg in segments:
        if video["doc_type"] == "市政總質詢":
            title = f"市政總質詢 第{seg['group']}組"
        else:
            title = f"部門質詢（{video['dept']}）第{seg['group']}組"
        for name in seg["councillors"]:
            if name not in identity:
                continue
            person_id = identity[name][0]
            upsert_fact(
                conn, f"ivideo:{video['video_id']}:{seg['group']}:{person_id}", person_id, "interpellation",
                {
                    "title": title,
                    "doc_type": video["doc_type"],
                    "dept": video["dept"],
                    "term": 14,
                    "session": video["session"],
                    "group": seg["group"],
                    "councillors": seg["councillors"],
                    "group_size": len(seg["councillors"]),
                    "start_sec": seg["start_sec"],
                    "seekable": seg["seekable"],
                    "video_id": video["video_id"],
                },
                video_url(video["video_id"], seg["group"] if seg["seekable"] else None),
                fetched_at, date=video["date"],
            )
            n += 1
    return n


def known_videos(conn):
    rows = conn.execute("SELECT DISTINCT json_extract(data, '$.video_id') FROM fact WHERE fact_key LIKE 'ivideo:%'")
    return {r[0] for r in rows}


def covered_councillors(conn):
    row = conn.execute("SELECT state FROM source_state WHERE source = 'tcc_videos'").fetchone()
    return set(json.loads(row["state"])["covered"]) if row else set()


# ponytail: 增量＝DB 已有的 video_id 不再打 Read／Segment_Read。上限：影片上架後分段若被修正不會重抓；
#   沒有分段的影片（目前 2 支）每次都會重打，直到議會補上分段。identity 新增對照時（同 tcc_interpellations）
#   整批重抓一次（約 529 次請求），把新議員的舊影片補齊。升級：定期 full=True 全量重掃。
def run(conn, full=False):
    identity = load_identity()
    exhaustive = full or bool(set(identity) - covered_councillors(conn))
    known = set() if exhaustive else known_videos(conn)
    items = get("/Front/Query/GetList")
    if len(items) < MIN_LIST_TOTAL:
        raise ValueError(f"GetList 只回 {len(items)} 筆（下限 {MIN_LIST_TOTAL}），不帶 cookie 回全站的行為可能變了")
    videos = parse_list(items)
    in_db = known_videos(conn)
    if len(videos) < len(in_db):
        raise ValueError(f"GetList 範圍內影片 {len(videos)} 支，少於 DB 已有的 {len(in_db)} 支")
    fetched_at = now_utc()
    for v in videos:
        if v["video_id"] in known:
            continue
        read = get(f"/Front/VideoContent/Read?id={v['video_id']}")
        if read.get("Title") != v["list_title"]:
            raise ValueError(f"{v['video_id']}：Read 標題 {read.get('Title')!r} 與清單 {v['list_title']!r} 不一致")
        segments = get(f"/Front/VideoContent/Segment_Read?id={v['video_id']}") or []
        if not segments:
            print(f"注意：{v['date']} {v['list_title']} 沒有分段，只有排定名單，跳過")
            continue
        write_video(conn, v, parse_segments(segments), identity, fetched_at)
    upsert(
        conn, "source_state",
        {"source": "tcc_videos", "state": json.dumps({"covered": sorted(identity)}, ensure_ascii=False)},
        ("source",),
    )
