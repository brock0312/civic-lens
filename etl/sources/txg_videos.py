"""臺中市議會第 4 屆口頭質詢影片：網際網路多媒體隨選視訊系統 vod.tccc.gov.tw（V15）。

只收「現任臺中市議員且登記參選 2026」的人。影片是逐人剪輯：議員清單 wb_name01.asp 給每人的 cno，
個人清單 wb_name02.asp?url=22&cno=<cno>&PageNo=<n> 每頁 10 支、新到舊，翻到第 4 屆以前就停。
每支影片連到 index.asp?url=22&cno=<cno>&ano=<ano>（影片本身就是該議員的質詢片段）。
聯合質詢的標題列出同組議員「(甲、乙等議員聯合質詢)」，每位議員清單各列一次。
自我檢查：python3 -m etl.sources.txg_videos（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import json
import re
import sys
import time
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import get, now_utc
from etl.match import VARIANTS, han
from etl.sources.national_councilors import TERM_START

VOD = "https://vod.tccc.gov.tw"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "txg_vod"
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔（robots.txt 404，V15）
MAX_PAGES = 60      # 安全上限：陳淑華第 2 屆起共 32 頁
_VAR = str.maketrans(VARIANTS)

ROW = re.compile(r'class="link01">(?:<a href="index\.asp\?url=22&cno=\d+&ano=(\d+)[^"]*"[^>]*>)?([^<]+?)(?:</a>)?</td>'
                 r'.*?nowrap="nowrap">(\d{4}-\d\d-\d\d)</td>', re.S)
CURRENT = re.compile(r"ano=(\d+)&PageNo=")  # 分頁連結帶著「目前播放」那支（第 1 頁沒有連結的那列）的 ano
LAST = re.compile(r"PageNo=(\d+)\" target=\"_top\">最末頁")
MEMBER = re.compile(r'(?:<a href="index\.asp\?url=22&cno=(\d+)"[^>]*>)?<font color="blue">([^<]+)</font>')
TITLE = re.compile(r"^第(\d+)屆第(\d+)次(定期會|臨時會)\s*(.+)$")
JOINT = re.compile(r"[(（]([^()（）]+?)等?議員聯合質+詢[)）]$")  # 標題偶有「聯合質質詢」
DEPT = re.compile(r"^業務質詢[:：](.+?)部分?$")

_last = 0.0


def fetch(path):
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return get(VOD + path).decode("utf-8")
    finally:
        _last = time.monotonic()


def parse_page(html):
    """個人清單一頁 → ([{ano, title, date}], 最末頁)。沒有連結的那列（目前播放）用分頁連結的 ano。"""
    cur = CURRENT.search(html)
    rows = []
    for ano, title, date in ROW.findall(html):
        if not ano:
            if not cur:
                raise ValueError(f"臺中影片清單有未連結的列但找不到 ano：{title!r}")
            ano = cur.group(1)
        rows.append({"ano": ano, "title": title.strip(), "date": date})
    last = LAST.search(html)
    return rows, int(last.group(1)) if last else 1


def parse_title(title):
    """影片標題 → {session, doc_type, dept, title, term, councillors}；不是質詢回 None；含「質詢」但格式未知就 raise。"""
    m = TITLE.match(title)
    if not m:
        if "質詢" in title:
            raise ValueError(f"臺中影片標題格式未知：{title!r}")
        return None
    term, nth, kind, meeting = m.groups()
    j = JOINT.search(meeting)
    councillors = [x.strip() for x in j.group(1).split("、")] if j else []
    meeting = meeting[:j.start()].strip() if j else meeting.strip()
    if "質詢" not in meeting:
        return None
    out = {"session": f"第{int(term)}屆第{int(nth)}次{kind}", "term": int(term), "councillors": councillors}
    if meeting == "市政總質詢":
        return {**out, "doc_type": "市政總質詢", "dept": None, "title": "市政總質詢"}
    d = DEPT.match(meeting)
    if not d:
        raise ValueError(f"臺中影片標題格式未知：{title!r}")
    dept = d.group(1).strip()
    return {**out, "doc_type": "部門質詢", "dept": dept, "title": f"業務質詢（{dept}）"}


def parse_videos(rows, name):
    """快取的清單列 → 第 4 屆口頭質詢 [{video_id, date, ...}]，同一 ano 只留一筆，依日期排序。"""
    best = {}
    for r in rows:
        if r["date"] < TERM_START:
            continue
        meta = parse_title(r["title"])
        if not meta or meta["term"] != 4:
            continue
        best[r["ano"]] = {**meta, "councillors": meta["councillors"] or [name], "video_id": r["ano"],
                          "date": r["date"], "list_title": r["title"]}
    return sorted(best.values(), key=lambda v: (v["date"], int(v["video_id"])))


def video_url(cno, ano):
    return f"{VOD}/index.asp?url=22&cno={cno}&ano={ano}"


def parse_members(html):
    """wb_name01.asp → {漢字姓名（異體字正規化）: (姓名, cno)}；名字沒有連結（沒有個人影片頁）時 cno 為 None。重名就 raise。"""
    out = {}
    for cno, name in MEMBER.findall(html):
        k = han(name).translate(_VAR)
        if k in out and out[k][1] != cno:
            raise ValueError(f"臺中 VOD 議員名單重名：{name}")
        out[k] = (name.strip(), cno or None)
    return out


def match_members(targets, members):
    """[{person_id, name}] × parse_members → {person_id: (vod_name, cno)}；名單上沒有這個名字就 raise。"""
    out, missing = {}, []
    for t in targets:
        hit = members.get(han(t["name"]).translate(_VAR))
        if hit:
            out[t["person_id"]] = hit
        else:
            missing.append(t)
    if missing:
        raise ValueError(f"臺中 VOD 議員名單對不到：{missing}")
    return out


def targets(conn):
    """有臺中市議員任職 fact 且有 2026 candidacy 的人。"""
    rows = conn.execute("""
        SELECT DISTINCT p.person_id, p.name FROM fact o JOIN person p USING (person_id)
        WHERE o.kind = 'office' AND json_extract(o.data, '$.office') = 'txg_councilor'
          AND EXISTS (SELECT 1 FROM fact c WHERE c.person_id = o.person_id AND c.kind = 'candidacy')
        ORDER BY p.person_id""")
    return [{"person_id": r["person_id"], "name": r["name"]} for r in rows]


def fetch_member(cno, full=False):
    """快取 data/cache/txg_vod/cno_<cno>.json = {rows}（清單原始欄位，新到舊）。

    從第 1 頁往後翻，直到出現第 4 屆以前的影片、翻完，或（增量）遇到快取裡已有的 ano。
    ponytail: 增量假設新影片只會出現在清單前面；日期較舊的補上架影片會漏，升級：run(full=True)。
    """
    path = CACHE / f"cno_{cno}.json"
    cached = None if full or not path.exists() else json.loads(path.read_text(encoding="utf-8"))
    known = {r["ano"] for r in cached["rows"]} if cached else set()
    rows, page, last = [], 1, 1
    while page <= last:
        if page > MAX_PAGES:
            raise ValueError(f"臺中 cno={cno} 超過 {MAX_PAGES} 頁")
        got, last = parse_page(fetch(f"/wb_name02.asp?url=22&cno={cno}&PageNo={page}"))
        new = [r for r in got if r["ano"] not in known and r["ano"] not in {x["ano"] for x in rows}]
        rows += new
        if len(new) < len(got) or any(r["date"] < TERM_START for r in got):
            break
        page += 1
    if cached:
        rows += cached["rows"]
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    return rows


def write_videos(conn, person_id, cno, videos, fetched_at, known=frozenset()):
    """每位議員每支影片一筆 fact；已在 DB 的 key 不重寫（fetched_at 不變）。回傳新寫入筆數。"""
    n = 0
    for v in videos:
        key = f"tvideo:{v['video_id']}:{person_id}"
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
            video_url(cno, v["video_id"]), fetched_at, date=v["date"],
        )
        n += 1
    return n


def load_members(full=False):
    path = CACHE / "members.html"
    if full or not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(fetch("/wb_name01.asp?url=21"), encoding="utf-8")
    return parse_members(path.read_text(encoding="utf-8"))


def run(conn, full=False):
    ts = targets(conn)
    try:
        vod = match_members(ts, load_members(full))
    except ValueError:  # 名單可能更新過：重抓一次再對
        vod = match_members(ts, load_members(True))
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'tvideo:%'")}
    fetched_at = now_utc()
    total = new = 0
    for t in ts:
        name, cno = vod[t["person_id"]]
        if not cno:  # 名單上有名字但沒有個人影片頁（例：張清照）
            continue
        videos = parse_videos(fetch_member(cno, full), name)
        total += len(videos)
        new += write_videos(conn, t["person_id"], cno, videos, fetched_at, known)
    print(f"txg_videos：對象 {len(ts)} 人，影片 {total} 筆，新寫入 {new} 筆")


def dump_targets():
    import tempfile
    from etl.db import open_db
    with tempfile.TemporaryDirectory() as d:
        return targets(open_db(Path(d) / "check.db", Path(__file__).resolve().parents[2] / "data" / "civic.sql"))


def check(sample=2, seed=15):
    """讀快取與 data/civic.sql：印出對象人數、有影片人數、影片數，並固定 seed 抽樣連結（供 curl 核對標題）。"""
    import random
    ts = dump_targets()
    vod = match_members(ts, load_members())
    picks, have, total = [], 0, 0
    for t in ts:
        name, cno = vod[t["person_id"]]
        path = CACHE / f"cno_{cno}.json"
        if not cno:
            print(f"  VOD 名單沒有個人影片頁：{name}")
            continue
        if not path.exists():
            print(f"  未抓取：{name}（cno={cno}）")
            continue
        vs = parse_videos(json.loads(path.read_text(encoding="utf-8"))["rows"], name)
        have += bool(vs)
        total += len(vs)
        picks += [(name, video_url(cno, v["video_id"]), v["list_title"]) for v in vs]
    print(f"臺中：對象 {len(ts)} 人，有影片 {have} 人，影片 {total} 支")
    for name, url, title in random.Random(seed).sample(picks, min(sample, len(picks))):
        print(f"  抽樣：{name}｜{title}｜{url}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:  # 只更新快取（對象取自 data/civic.sql），不寫 DB
        for name, cno in match_members(dump_targets(), load_members()).values():
            if cno:
                print(name, len(fetch_member(cno)), flush=True)
    check()
