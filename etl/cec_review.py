"""2026 候選人資格審定結果（中選會 115-10-16 公告，article 65212）。

公告列出全部直轄市長、縣市長候選人姓名（均合格），議員只列不合格者。
`data/cec_review_2026.csv` 只記選舉區、姓名、結果；公告中的不合格原因含刑案與身分資訊，本站不轉載。
tpe_candidates、national_candidates 讀這張表：不合格者不寫 candidacy（已有的刪除），其餘標 status=qualified。
run() 接在 national_candidates 之後，不連網：對 DB 既有的 candidacy 再套一次並核對公告人數
（完整 ETL 時是無變動的檢查；只補跑審定時不必重抓登記冊 PDF）。
"""
import csv
import json
import re
from pathlib import Path

from etl.db import upsert_fact

REVIEW_URL = "https://web.cec.gov.tw/api/central/article/65212"
REVIEW_DATE = "2026-10-16"
REVIEW_FETCHED = "2026-10-18"  # 依公告逐列抄錄審定表的日期（頁面腳註的擷取日）
PATH = Path(__file__).resolve().parent.parent / "data" / "cec_review_2026.csv"
# 公告的「受理登記／符合規定」人數；national_candidates 依登記彙總表 1-1～4-1 逐表核對
TOTALS = {"1-1": (23, 23), "2-1": (610, 605), "3-1": (58, 58), "4-1": (892, 887)}


def disqualified(path=None):
    """{(選舉區, 姓名)}：審定不合格者。結果欄只接受「不合格」，避免表格誤填。"""
    with open(path or PATH, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    bad = [r for r in rows if r["result"] != "不合格"]
    if bad:
        raise ValueError(f"審定表結果欄只能是「不合格」：{bad}")
    keys = [(r["area"], r["name"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("審定表有重複列")
    return set(keys)


def status_data():
    return {"status": "qualified", "review_url": REVIEW_URL, "review_date": REVIEW_DATE, "review_fetched_at": REVIEW_FETCHED}


def drop_candidacy(conn, person_id):
    conn.execute("DELETE FROM fact WHERE fact_key = ?", (f"candidacy:2026-local:{person_id}",))


AREA = re.compile(r"(\S{2}[縣市])第(\d+)選舉區")
CAND_SOURCES = ("tpe_reg_2026", "cec_reg_2026")  # tpe_candidates、national_candidates 的 person_source_id


def district_of(area):
    from etl.sources.national_districts import ISO, council_id
    m = AREA.fullmatch(area)
    if not m or m.group(1) not in ISO:
        raise ValueError(f"審定表選舉區格式未知：{area!r}")
    return council_id(ISO[m.group(1)], int(m.group(2)))


def table_of(office):
    """candidacy 的 office（tpe_councilor…）→ 登記彙總表編號，對應 TOTALS。"""
    iso, kind = office.split("_")
    municipal = iso in ("tpe", "nwt", "tao", "txg", "tnn", "khh")
    return {("mayor", True): "1-1", ("councilor", True): "2-1", ("mayor", False): "3-1", ("councilor", False): "4-1"}[(kind, municipal)]


def run(conn):
    marks = ",".join("?" * len(CAND_SOURCES))
    pid_of = {r["source_key"]: r["person_id"] for r in conn.execute(
        f"SELECT source_key, person_id FROM person_source_id WHERE source IN ({marks})", CAND_SOURCES)}
    disq = disqualified()
    for area, name in sorted(disq):
        pid = pid_of.get(f"{district_of(area)}:{name}")
        if not pid:
            raise ValueError(f"審定不合格者在登記名冊對照找不到：{area} {name}")
        drop_candidacy(conn, pid)
    counts = {}
    for r in conn.execute("SELECT * FROM fact WHERE kind = 'candidacy'").fetchall():
        data = json.loads(r["data"])
        if data.get("election") != "2026-local":
            continue
        counts[table_of(data["office"])] = counts.get(table_of(data["office"]), 0) + 1
        # 登記冊沒有重抓：保留原擷取時間，審定公告的擷取日另記在 review_fetched_at
        upsert_fact(conn, r["fact_key"], r["person_id"], "candidacy", {**data, **status_data()},
                    r["source_url"], r["fetched_at"], date=r["date"])
    want = {k: q for k, (_, q) in TOTALS.items()}
    if counts != want:
        raise ValueError(f"審定後候選人數 {counts} 與公告合格人數 {want} 不符")
    print(f"審定：不合格 {len(disq)} 人已移除；合格 {sum(counts.values())} 人 {sorted(counts.items())}")
