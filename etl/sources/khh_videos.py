"""高雄市議會第 4 屆口頭質詢影片：議事影音系統 ivod.kcc.gov.tw 的 JSON 端點（V15）。

只收「現任高雄市議員且登記參選 2026」的人。每人一次 getConvertVideoSearch（依發言人搜尋），結果每支影片
一筆、已帶該議員發言起點秒數 `in`，所以不必逐支打 getConvertVideoData。深連結 `/watch/<gid>/<source>?start=<in>`。
只收標題含「質詢」的場次（部門業務質詢、市政總質詢、市長施政報告質詢）；二、三讀會等發言不算口頭質詢。
"""
import datetime
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import UA, get_json, now_utc
from etl.match import VARIANTS, han
from etl.sources.national_councilors import TERM_START

API = "https://ivod.kcc.gov.tw/cms/public/api"
WATCH = "https://ivod.kcc.gov.tw/watch"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "khh_ivod"
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔
PAGE_SIZE = 5000    # 實測一次可回 860 筆（邱俊憲全部）；回滿就代表可能被截斷
# ponytail: 增量＝快取過的人只重抓「上次抓取日前 60 天」起的影片並合併。上限：會議 60 天後才上架的影片會漏；
#   升級：run(full=True) 全量重抓（每人一次請求，約 54 次）。
REFETCH_DAYS = 60
_VAR = str.maketrans(VARIANTS)

CN = {c: i for i, c in enumerate("一二三四五六七八九十", 1)}
TITLE = re.compile(r"^\d{3}-\d\d-\d\d \d\d:\d\d:\d\d 第(.+?)屆第(.+?)次(定期會|臨時會) (.+)$")
DEPT = re.compile(r"^(.+?)(?:部門)?業務(?:報告與)?質詢(?:[:：].*)?$")
DEPT_ALIAS = {"都委員會": "都市計畫委員會"}  # 第四屆第二次定期會的標題簡寫
GENERAL = {"市政總質詢": "市政總質詢", "市長施政報告質詢": "施政報告質詢", "市長施政報告與質詢": "施政報告質詢"}

_last = 0.0


def _num(s):
    """「4」「四」「十」「十一」→ int。"""
    if s.isdigit():
        return int(s)
    if s.startswith("十"):
        return 10 + CN.get(s[1:], 0)
    if s.endswith("十"):
        return CN[s[0]] * 10
    if "十" in s:
        a, b = s.split("十")
        return CN[a] * 10 + CN[b]
    return CN[s]


def _wait():
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)


def get(path):
    global _last
    _wait()
    try:
        return get_json(API + path)
    finally:
        _last = time.monotonic()


def post(path, form):
    global _last
    _wait()
    req = urllib.request.Request(API + path, data=urllib.parse.urlencode(form).encode(), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    finally:
        _last = time.monotonic()


def roc_date(s):
    y, m, d = s.split("-")
    return f"{int(y) + 1911}-{m}-{d}"


def parse_title(title):
    """影片標題 → {session, doc_type, dept, title}；不是口頭質詢回 None；含「質詢」但格式未知就 raise。"""
    m = TITLE.match(title.strip())
    if not m:
        if "質詢" in title:
            raise ValueError(f"高雄影片標題格式未知：{title!r}")
        return None
    term, nth, kind, meeting = m.groups()
    meeting = meeting.strip().rstrip("。")
    if "質詢" not in meeting:
        return None
    session = f"第{_num(term)}屆第{_num(nth)}次{kind}"
    if meeting in GENERAL:
        doc_type = GENERAL[meeting]
        return {"session": session, "doc_type": doc_type, "dept": None, "title": doc_type, "term": _num(term)}
    d = DEPT.match(meeting)
    if not d:
        raise ValueError(f"高雄影片標題格式未知：{title!r}")
    dept = DEPT_ALIAS.get(d.group(1), d.group(1))
    return {"session": session, "doc_type": "部門質詢", "dept": dept, "title": f"部門質詢（{dept}）", "term": _num(term)}


def parse_search(items, name, gid):
    """getConvertVideoSearch 結果 → 第 4 屆口頭質詢 [{video_id, gid, date, start_sec, ...}]，每支影片一筆。

    同一支影片會以議員自己的頻道（gid）與議會頻道各出現一次，起點相同：優先用議員頻道，否則用議會頻道。
    同一議員在一支影片有多段發言時，搜尋只回第一段，等於取最早的起點（同臺北分段重複時的規則）。
    """
    best = {}
    for it in items:
        if it.get("name") != name or roc_date(it["date"]) < TERM_START:
            continue
        meta = parse_title(it["title"])
        if not meta or meta["term"] != 4:
            continue
        source = it["source"].split("?")[0]
        v = {**meta, "video_id": source, "gid": it["owner_group"], "date": roc_date(it["date"]),
             "start_sec": int(it["in"]), "list_title": it["title"]}
        prev = best.get(source)
        if prev is None or (prev["gid"] != gid and v["gid"] == gid) or (
                prev["gid"] == v["gid"] and v["start_sec"] < prev["start_sec"]):
            best[source] = v
    return sorted(best.values(), key=lambda v: (v["date"], v["video_id"]))


def video_url(v):
    return f"{WATCH}/{v['gid']}/{v['video_id']}?start={v['start_sec']}"


def match_members(targets, members):
    """[{person_id, name, district_n}] × getMembers → {person_id: (ivod_name, gid)}；以漢字姓名＋選區對，對不到就 raise。"""
    index = {}
    for m in members:
        n = re.fullmatch(r"第(\d+)選區", m.get("regionName") or "")
        name = re.sub(r"(副議長|議長|議員)$", "", m["title"]).strip()
        if n:
            index[(han(name).translate(_VAR), int(n.group(1)))] = (name, m["gid"])
    out, missing = {}, []
    for t in targets:
        hit = index.get((han(t["name"]).translate(_VAR), t["district_n"]))
        if hit:
            out[t["person_id"]] = hit
        else:
            missing.append(t)
    if missing:
        raise ValueError(f"iVOD 議員名單對不到：{missing}")
    return out


def targets(conn):
    """有高雄市議員任職 fact 且有 2026 candidacy 的人。"""
    rows = conn.execute("""
        SELECT DISTINCT p.person_id, p.name, json_extract(o.data, '$.district_id') AS district_id
        FROM fact o JOIN person p USING (person_id)
        WHERE o.kind = 'office' AND json_extract(o.data, '$.office') = 'khh_councilor'
          AND EXISTS (SELECT 1 FROM fact c WHERE c.person_id = o.person_id AND c.kind = 'candidacy')
        ORDER BY p.person_id""")
    return [{"person_id": r["person_id"], "name": r["name"], "district_n": int(r["district_id"].rsplit("-", 1)[1])}
            for r in rows]


def fetch_member(name, gid, full=False, today=None):
    """快取 data/cache/khh_ivod/search_<gid>.json = {through, items}（原始搜尋結果）；增量時只抓近期並合併。"""
    today = today or datetime.date.today()
    path = CACHE / f"search_{gid}.json"
    cached = None if full or not path.exists() else json.loads(path.read_text(encoding="utf-8"))
    form = {"searchSpeaker": name, "page": 1, "pageSize": PAGE_SIZE}
    if cached:
        start = datetime.date.fromisoformat(cached["through"]) - datetime.timedelta(days=REFETCH_DAYS)
        form |= {"dateRange[start]": start.isoformat(), "dateRange[end]": today.isoformat()}
    items = post("/getConvertVideoSearch", form)
    if len(items) >= PAGE_SIZE:
        raise ValueError(f"{name} 搜尋回 {len(items)} 筆，達 pageSize 上限，可能被截斷")
    if cached:
        fresh = {(it["source"], it["owner_group"]) for it in items}
        items = [it for it in cached["items"] if (it["source"], it["owner_group"]) not in fresh] + items
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"through": today.isoformat(), "items": items}, ensure_ascii=False), encoding="utf-8")
    return items


def write_videos(conn, person_id, name, videos, fetched_at, known=frozenset()):
    """每位議員每支影片一筆 fact；已在 DB 的 key 不重寫（fetched_at 不變）。回傳新寫入筆數。"""
    n = 0
    for v in videos:
        key = f"kvideo:{v['video_id']}:{person_id}"
        if key in known:
            continue
        upsert_fact(
            conn, key, person_id, "interpellation",
            {
                "title": v["title"],
                "doc_type": v["doc_type"],
                "dept": v["dept"],
                "term": v["term"],
                "session": v["session"],
                "councillors": [name],
                "group_size": 1,
                "start_sec": v["start_sec"],
                "seekable": True,
                "video_id": v["video_id"],
                "gid": v["gid"],
            },
            video_url(v), fetched_at, date=v["date"],
        )
        n += 1
    return n


def run(conn, full=False):
    ts = targets(conn)
    members_path = CACHE / "members.json"
    if full or not members_path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        members_path.write_text(json.dumps(get("/getMembers"), ensure_ascii=False), encoding="utf-8")
    try:
        ivod = match_members(ts, json.loads(members_path.read_text(encoding="utf-8")))
    except ValueError:  # 名單可能更新過：重抓一次再對
        members_path.write_text(json.dumps(get("/getMembers"), ensure_ascii=False), encoding="utf-8")
        ivod = match_members(ts, json.loads(members_path.read_text(encoding="utf-8")))
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'kvideo:%'")}
    fetched_at = now_utc()
    total = new = 0
    for t in ts:
        name, gid = ivod[t["person_id"]]
        videos = parse_search(fetch_member(name, gid, full), name, gid)
        total += len(videos)
        new += write_videos(conn, t["person_id"], name, videos, fetched_at, known)
    print(f"khh_videos：對象 {len(ts)} 人，影片 {total} 筆，新寫入 {new} 筆")
