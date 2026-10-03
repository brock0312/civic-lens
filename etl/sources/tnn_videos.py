"""臺南市議會第 4 屆口頭質詢影片：議事影音 councilmovielist.asp 依議員查詢（GET），影片放在 YouTube（V15）。

只收「現任臺南市議員且登記參選 2026」的人。每人每會期約一支「市政總質詢」影片，就是該議員的質詢時段；
連到 YouTube 官方網址 https://www.youtube.com/watch?v=<id>，不嵌入播放器。
議員名單與選區取自同一頁的下拉選單（optgroup「第NN選區-…」）；網站把「李啓維」寫作「李啟維」，以異體字正規化比對。
自我檢查：python3 -m etl.sources.tnn_videos（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import get, now_utc
from etl.match import VARIANTS, han
from etl.sources.national_councilors import TERM_START

SITE = "https://www.tncc.gov.tw/councilmovielist.asp"
ORCAID = "EF1DC98A-A077-4EEA-9687-DE0113752A11"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "tnn_mv"
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔（robots.txt 轉到 blank.asp，等於沒有）
MAX_PAGES = 10      # 安全上限：每頁 5 支，第 4 屆每人約 8 支
_VAR = str.maketrans(VARIANTS)

GROUP = re.compile(r"<optgroup label='第(\d+)選區[^']*'>(.*?)(?=<optgroup|</select>)", re.S)
OPTION = re.compile(r"<option value='([^']+)'>")
BLOCK = re.compile(r'<th colspan="3">([^<]+)</th>(.*?)(?=<thead>|</table>)', re.S)
VIDEO = re.compile(r'youtube\.com/embed/([\w-]{11})".*?class="margin-clear"[^>]*>([^<]*)<', re.S)
PAGE = re.compile(r'id="thispage(\d+)"')
HEADER = re.compile(r"^(\d{4}-\d\d-\d\d)【第(\d+)屆第(\d+)次(定期會|臨時會)[:：](.+)】$")
NAMES = re.compile(r"^(.+?)(?:議員)?\s*市政總質詢")  # 聯合質詢：「甲、乙議員市政總質詢(聯合質詢)」「…（共用時間）」

_last = 0.0


def fetch(params):
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return get(f"{SITE}?{urllib.parse.urlencode(params)}").decode("utf-8")
    finally:
        _last = time.monotonic()


def list_params(name, page):
    return {"orcaid": ORCAID, "topage": page, "status": "^", "council1tag": name, "AVTYPE": "市政總質詢",
            "menu1": "第4屆", "menu2": "", "menu3": ""}


def parse_page(html):
    """查詢結果一頁 → ([{video_id, header, caption}], 最末頁)。"""
    rows = [{"video_id": vid, "header": header.strip(), "caption": caption.strip()}
            for header, body in BLOCK.findall(html) for vid, caption in VIDEO.findall(body)]
    return rows, max([int(n) for n in PAGE.findall(html)] or [1])


def parse_header(header):
    """「2026-09-02【第4屆第8次定期會：市政總質詢】」→ {date, session, term, doc_type, ...}；不是質詢回 None。"""
    m = HEADER.match(header)
    if not m:
        if "質詢" in header:
            raise ValueError(f"臺南影片標題格式未知：{header!r}")
        return None
    date, term, nth, kind, meeting = m.groups()
    meeting = meeting.strip()
    if meeting != "市政總質詢":
        if "質詢" in meeting:
            raise ValueError(f"臺南影片標題格式未知：{header!r}")
        return None
    return {"date": date, "session": f"第{int(term)}屆第{int(nth)}次{kind}", "term": int(term),
            "doc_type": "市政總質詢", "dept": None, "title": "市政總質詢"}


def parse_videos(rows, name):
    """快取列 → 第 4 屆口頭質詢 [{video_id, date, councillors, ...}]。同 id 只留一筆。

    查詢是依標籤，偶有誤標（別位議員的影片），所以影片說明要寫到這位議員才收；說明的錯字（「郭鴻議員」）也因此不收。
    """
    key = han(name).translate(_VAR)
    best = {}
    for r in rows:
        meta = parse_header(r["header"])
        if not meta or meta["term"] != 4 or meta["date"] < TERM_START:
            continue
        if key not in han(r["caption"]).translate(_VAR):
            continue
        names = NAMES.match(r["caption"])
        names = [x.strip() for x in names.group(1).split("、")] if names and "、" in names.group(1) else [name]
        best[r["video_id"]] = {**meta, "video_id": r["video_id"], "caption": r["caption"], "councillors": names}
    return sorted(best.values(), key=lambda v: (v["date"], v["video_id"]))


def video_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def parse_members(html):
    """查詢頁下拉選單 → {(漢字姓名（異體字正規化）, 選區): 網站上的姓名}。"""
    return {(han(name).translate(_VAR), int(n)): name
            for n, body in GROUP.findall(html) for name in OPTION.findall(body)}


def match_members(targets, members):
    """[{person_id, name, district_n}] × parse_members → {person_id: 網站姓名}；對不到就 raise。"""
    out, missing = {}, []
    for t in targets:
        hit = members.get((han(t["name"]).translate(_VAR), t["district_n"]))
        if hit:
            out[t["person_id"]] = hit
        else:
            missing.append(t)
    if missing:
        raise ValueError(f"臺南議事影音議員名單對不到：{missing}")
    return out


def targets(conn):
    """有臺南市議員任職 fact 且有 2026 candidacy 的人。"""
    rows = conn.execute("""
        SELECT DISTINCT p.person_id, p.name, json_extract(o.data, '$.district_id') AS district_id
        FROM fact o JOIN person p USING (person_id)
        WHERE o.kind = 'office' AND json_extract(o.data, '$.office') = 'tnn_councilor'
          AND EXISTS (SELECT 1 FROM fact c WHERE c.person_id = o.person_id AND c.kind = 'candidacy')
        ORDER BY p.person_id""")
    return [{"person_id": r["person_id"], "name": r["name"], "district_n": int(r["district_id"].rsplit("-", 1)[1])}
            for r in rows]


def fetch_member(name, full=False):
    """快取 data/cache/tnn_mv/<姓名>.json = {rows}（查詢結果原始欄位，新到舊）。

    從第 1 頁往後翻到最末頁；增量時遇到快取裡已有的影片就停。
    ponytail: 增量假設新影片只會出現在清單前面；補上架的舊影片會漏，升級：run(full=True)。
    """
    path = CACHE / f"{name}.json"
    cached = None if full or not path.exists() else json.loads(path.read_text(encoding="utf-8"))
    known = {r["video_id"] for r in cached["rows"]} if cached else set()
    rows, page, last = [], 1, 1
    while page <= last:
        if page > MAX_PAGES:
            raise ValueError(f"臺南 {name} 超過 {MAX_PAGES} 頁")
        got, last = parse_page(fetch(list_params(name, page)))
        new = [r for r in got if r["video_id"] not in known | {x["video_id"] for x in rows}]
        rows += new
        if len(new) < len(got):
            break
        page += 1
    if cached:
        rows += cached["rows"]
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    return rows


def write_videos(conn, person_id, name, videos, fetched_at, known=frozenset()):
    """每位議員每支影片一筆 fact；已在 DB 的 key 不重寫（fetched_at 不變）。回傳新寫入筆數。"""
    n = 0
    for v in videos:
        key = f"nvideo:{v['video_id']}:{person_id}"
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
                "councillors": v["councillors"],
                "group_size": len(v["councillors"]),
                "clip": True,
                "video_id": v["video_id"],
            },
            video_url(v["video_id"]), fetched_at, date=v["date"],
        )
        n += 1
    return n


def load_members(full=False):
    path = CACHE / "members.html"
    if full or not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(fetch({"orcaid": ORCAID}), encoding="utf-8")
    return parse_members(path.read_text(encoding="utf-8"))


def run(conn, full=False):
    ts = targets(conn)
    try:
        site = match_members(ts, load_members(full))
    except ValueError:  # 名單可能更新過：重抓一次再對
        site = match_members(ts, load_members(True))
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'nvideo:%'")}
    fetched_at = now_utc()
    total = new = 0
    current = set()
    for t in ts:
        name = site[t["person_id"]]
        videos = parse_videos(fetch_member(name, full), name)
        total += len(videos)
        current |= {f"nvideo:{v['video_id']}:{t['person_id']}" for v in videos}
        new += write_videos(conn, t["person_id"], name, videos, fetched_at, known)
    stale = known - current  # 不再符合條件（例：篩選規則改變、不再是候選人）的舊影片
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    print(f"tnn_videos：對象 {len(ts)} 人，影片 {total} 筆，新寫入 {new} 筆，刪除 {len(stale)} 筆")


def dump_targets():
    import tempfile
    from etl.db import open_db
    with tempfile.TemporaryDirectory() as d:
        return targets(open_db(Path(d) / "check.db", Path(__file__).resolve().parents[2] / "data" / "civic.sql"))


def check(sample=2, seed=15):
    """讀快取與 data/civic.sql：印出對象人數、有影片人數、影片數，並固定 seed 抽樣連結（供 curl 核對標題）。"""
    import random
    ts = dump_targets()
    site = match_members(ts, load_members())
    picks, have, total = [], 0, 0
    for t in ts:
        name = site[t["person_id"]]
        path = CACHE / f"{name}.json"
        if not path.exists():
            print(f"  未抓取：{name}")
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
        vs = parse_videos(rows, name)
        have += bool(vs)
        total += len(vs)
        picks += [(name, video_url(v["video_id"]), v["caption"]) for v in vs]
        dropped = [r for r in rows if r["video_id"] not in {v["video_id"] for v in vs}]
        for r in dropped:
            print(f"  不收：{name}｜{r['header']}｜{r['caption']}")
    print(f"臺南：對象 {len(ts)} 人，有影片 {have} 人，影片 {total} 支")
    for name, url, caption in random.Random(seed).sample(picks, min(sample, len(picks))):
        print(f"  抽樣：{name}｜{caption}｜{url}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:  # 只更新快取（對象取自 data/civic.sql），不寫 DB
        for name in match_members(dump_targets(), load_members()).values():
            print(name, len(fetch_member(name)), flush=True)
    check()
