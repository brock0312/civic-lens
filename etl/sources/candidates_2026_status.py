"""2026 候選人的審定結果與號次（選舉時程維運，V1 §1）：把人工核對過的官方公告套到 candidacy fact 上。

輸入是 repo 內的 data/candidates_2026_status.csv（不連網），每列一個事件：
- approved_all：中選會審定候選人資格（10/16 前）。district_id 填 *（全國）或縣市代碼（如 tpe），
  name 留空；範圍內沒有被 excluded 的候選人 status 改為 approved。
- excluded：審定不合格（value=disqualified）或撤回登記等（value=withdrawn）。網站只呈現候選人，export 不輸出這些人。
- ballot：號次（value=號次，10/23 抽籤、11/12 縣市長與 11/17 議員名單公告）。可用 scripts/ballot_numbers_2026.py
  由官方檔案轉出，核對後再併進本檔。

每列都要有 source_url（官方公告）、announced_on、confirmed_by、confirmed_at；姓名必須在該選區唯一對到一位候選人，
對不上就 raise（官方名單不該有對不上的人，對不上代表輸入錯了，不猜）。
登記冊來源（tpe_candidates、national_candidates）每次重跑都會把 status 寫回 registered，所以本來源要排在它們之後、每次重套。
"""
import csv
import json
from pathlib import Path

from etl.db import upsert_fact
from etl.match import name_key

PATH = Path(__file__).resolve().parents[2] / "data" / "candidates_2026_status.csv"
FIELDS = ("event", "district_id", "name", "value", "source_url", "announced_on", "confirmed_by", "confirmed_at", "note")
EXCLUDED = ("disqualified", "withdrawn")


def load(path=PATH):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["event"] not in ("approved_all", "excluded", "ballot"):
            raise ValueError(f"candidates_2026_status.csv 不認得的 event：{r}")
        if not (r["source_url"].startswith("http") and r["announced_on"] and r["confirmed_by"] and r["confirmed_at"]):
            raise ValueError(f"candidates_2026_status.csv 缺出處或核對紀錄：{r}")
        if r["event"] == "excluded" and r["value"] not in EXCLUDED:
            raise ValueError(f"excluded 的 value 必須是 {EXCLUDED}：{r}")
        if r["event"] == "ballot" and not r["value"].isdigit():
            raise ValueError(f"ballot 的 value 必須是號次數字：{r}")
    return rows


def _in_scope(district_id, scope):
    return scope == "*" or district_id.split("-")[0] == scope


def apply(cands, rows):
    """cands：[{person_id, name, district_id, data}] → {person_id: 新的 candidacy data}（只含有變動的人）。純函式。"""
    by_district = {}
    for c in cands:
        by_district.setdefault(c["district_id"], []).append(c)

    def find(r):
        hits = [c for c in by_district.get(r["district_id"], []) if name_key(c["name"]) == name_key(r["name"])]
        if len(hits) != 1:
            raise ValueError(f"{r['district_id']} {r['name']}：對到 {len(hits)} 位候選人（{r['event']}）")
        return hits[0]

    out = {c["person_id"]: dict(c["data"]) for c in cands}
    for r in (x for x in rows if x["event"] == "excluded"):
        d = out[find(r)["person_id"]]
        d.update(status=r["value"], status_source_url=r["source_url"], status_announced_on=r["announced_on"])
    for r in (x for x in rows if x["event"] == "approved_all"):
        for c in cands:
            d = out[c["person_id"]]
            if _in_scope(c["district_id"], r["district_id"]) and d.get("status") not in EXCLUDED:
                d.update(status="approved", status_source_url=r["source_url"], status_announced_on=r["announced_on"])
    seen = {}
    for r in (x for x in rows if x["event"] == "ballot"):
        c = find(r)
        n = int(r["value"])
        if seen.setdefault((c["district_id"], n), c["person_id"]) != c["person_id"]:
            raise ValueError(f"{c['district_id']} 號次 {n} 重複")
        if out[c["person_id"]].get("status") in EXCLUDED:
            raise ValueError(f"{c['district_id']} {c['name']} 已被排除，卻有號次")
        out[c["person_id"]].update(ballot_no=n, ballot_source_url=r["source_url"], ballot_announced_on=r["announced_on"])
    return {pid: d for pid, d in out.items() if d != dict(next(c for c in cands if c["person_id"] == pid)["data"])}


def run(conn):
    rows = load()
    if not rows:
        print("candidates_2026_status.csv 沒有資料，略過")
        return
    facts = conn.execute("SELECT f.fact_key, f.person_id, p.name, f.data, f.source_url, f.fetched_at, f.date "
                         "FROM fact f JOIN person p USING (person_id) WHERE f.kind = 'candidacy'").fetchall()
    cands = [{"person_id": f["person_id"], "name": f["name"], "data": json.loads(f["data"]),
              "district_id": json.loads(f["data"])["district_id"]} for f in facts]
    changed = apply(cands, rows)
    for f in facts:
        if f["person_id"] in changed:
            upsert_fact(conn, f["fact_key"], f["person_id"], "candidacy", changed[f["person_id"]], f["source_url"],
                        f["fetched_at"], date=f["date"])
    status = [d.get("status") for d in changed.values()]
    print(f"候選人狀態：審定 {status.count('approved')}、排除 {sum(status.count(s) for s in EXCLUDED)}、"
          f"有號次 {sum(1 for d in changed.values() if 'ballot_no' in d)}（共 {len(cands)} 位候選人）")
