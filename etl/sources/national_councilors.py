"""臺北以外縣市的現任議員（L3-A）：「現任」以議會官網名錄為準（V13 已定案第 2 點），任職起日與黨籍取自中選會 2022 開票。

身分：名錄現任議員用 etl.match 串到 2026 候選人；只有 links 才串，審閱清單只印到 log。
人工確認的串接寫在 data/identity_national.csv，表內列出的才視為確認串接。其餘另建 person（不確定就不併人）。
"""
import csv
import hashlib
import json
import time
from pathlib import Path

from etl.cec2022 import SOURCES as CEC_SOURCES, TICKETS, parse_candidates
from etl.db import upsert, upsert_fact
from etl.fetch import get_json, now_utc
from etl.match import VARIANTS, han, match
from etl.rosters import ROSTER_URLS, fetch_roster
from etl.sources.national_districts import COUNTIES, council_id

SOURCE = "roster_2026"
ISOS = ["nwt", "tao", "txg", "tnn", "khh"]  # 之後逐日擴充
EXPECTED = {"nwt": 64, "tao": 61, "txg": 62, "tnn": 55, "khh": 61}  # V13 §3：五都現任數
IDENTITY_PATH = Path(__file__).resolve().parents[2] / "data" / "identity_national.csv"
TERM_START = "2022-12-25"  # 內政部 111-12-25 新聞稿：九合一當選人宣誓就職（同 national_heads）
NAMES = dict(COUNTIES)
_VAR = str.maketrans(VARIANTS)


def roster_url(iso, n):
    url = ROSTER_URLS[iso]
    return url[n - 1] if isinstance(url, list) else url  # 桃園、臺南一選區一頁，依選區順序


def load_identity(path=IDENTITY_PATH):
    """人工確認表 → {(iso, roster_name, district_n): (person_id, verified_by)}。缺欄位或重複就 raise。"""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for r in rows:
        k = (r["iso"], r["roster_name"], int(r["district_n"]))
        if k in out:
            raise ValueError(f"identity_national.csv 重複：{k}")
        if not (r["person_id"] and r["confirmed_by"] and r["confirmed_at"]):
            raise ValueError(f"identity_national.csv 缺 person_id、confirmed_by 或 confirmed_at：{r}")
        out[k] = (r["person_id"], f"人工確認：{r['confirmed_by']} {r['confirmed_at']}")
    return out


def _seat_key(iso, n, name):
    # 同縣市同選區、漢字相同（異體字視為相同）即為同一席；不看拼音詞序
    return iso, n, han(name).translate(_VAR)


def plan(roster, won, candidates, identity):
    """名錄現任議員 → ([{row, person_id, verified_by, data, date}], 審閱清單)。person_id 為 None 代表要新建。純函式。

    won：中選會 2022 議員當選人（cec2022.parse_candidates 的列）；candidates：2026 候選人 {person_id, name, district_id}。
    """
    cur = [r for r in roster if r["current"]]
    recs = [{"key": i, "iso": r["iso"], "name": r["name"], "office": "councilor", "district_n": r["district_n"]}
            for i, r in enumerate(cur)]
    out = match(recs, candidates)
    links = {x["key"]: x["person_id"] for x in out["links"]}
    seats = {_seat_key(c["iso"], c["district_n"], c["name"]): c for c in won}
    rows = []
    for i, r in enumerate(cur):
        manual = identity.get((r["iso"], r["name"], r["district_n"]))
        if manual:
            person_id, verified_by = manual
        elif i in links:
            person_id = links[i]
            verified_by = "auto: etl.match 唯一同名、同縣市且選區重疊（議會官網現任名錄 vs 2026 候選人登記彙總表）"
        else:
            person_id, verified_by = None, "auto: 議會官網現任名錄，未串到 2026 候選人"
        w = seats.get(_seat_key(r["iso"], r["district_n"], r["name"]))
        data = {"office": f"{r['iso']}_councilor", "district_id": council_id(r["iso"], r["district_n"]),
                "title": f"{NAMES[r['iso']]}議員"}
        if r.get("party") or w:
            data["party"] = r.get("party") or w["party"]
        # 2022 當選人才寫任職起日；其餘（遞補或補選，依據未查）留空
        rows.append({"row": r, "person_id": person_id, "verified_by": verified_by, "data": data,
                     "date": TERM_START if w else None})
    review = [{**x, "row": cur[x["key"]]} for x in out["review"]]
    return rows, review


def fetch_won():
    won = []
    for kind, path in CEC_SOURCES:
        if kind == "mayor":
            continue
        time.sleep(1.1)
        won += [c for c in parse_candidates(get_json(f"{TICKETS}/{path}"), kind) if c["elected"] and c["iso"] in ISOS]
    return won


def fetch_rosters():
    roster = []
    for iso in ISOS:
        time.sleep(1.1)
        rows = fetch_roster(iso)
        n = sum(1 for r in rows if r["current"])
        if n != EXPECTED[iso]:
            raise ValueError(f"{iso} 名錄現任 {n} 人，與 V13 的 {EXPECTED[iso]} 人不一致")
        roster += rows
    return roster


def run(conn):
    fetched_at = now_utc()
    roster = fetch_rosters()
    won = fetch_won()
    cands = [{"person_id": r["person_id"], "name": r["name"], "district_id": json.loads(r["data"])["district_id"]}
             for r in conn.execute("SELECT f.person_id, p.name, f.data FROM fact f JOIN person p USING (person_id) "
                                   "WHERE f.kind = 'candidacy'")]
    rows, review = plan(roster, won, cands, load_identity())
    names = {r["person_id"]: r["name"] for r in cands}
    keys = set()
    for x in rows:
        r = x["row"]
        source_key = f"{council_id(r['iso'], r['district_n'])}:{r['name']}"
        person_id = x["person_id"]
        if not person_id:
            person_id = "p" + hashlib.sha1(f"{SOURCE}:{source_key}".encode()).hexdigest()[:10]
            upsert(conn, "person", {"person_id": person_id, "name": r["name"]}, ("person_id",))
        upsert(conn, "person_source_id",
               {"source": SOURCE, "source_key": source_key, "person_id": person_id, "verified_by": x["verified_by"]},
               ("source", "source_key"))
        key = f"office:{r['iso']}-council-2022:{person_id}"
        keys.add(key)
        upsert_fact(conn, key, person_id, "office", x["data"], roster_url(r["iso"], r["district_n"]), fetched_at,
                    date=x["date"])
    # 現任以名錄為準：離開名錄（或改串他人）的舊任職要刪掉，不再顯示為現任
    for iso in ISOS:
        for (k,) in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE ?", (f"office:{iso}-council-2022:%",)).fetchall():
            if k not in keys:
                conn.execute("DELETE FROM fact WHERE fact_key = ?", (k,))
    for iso in ISOS:
        mine = [x for x in rows if x["row"]["iso"] == iso]
        print(f"{iso} 現任議員：{len(mine)} 人，串到 2026 候選人 {sum(1 for x in mine if x['person_id'])}、"
              f"新建 {sum(1 for x in mine if not x['person_id'])}、審閱 {sum(1 for x in review if x['row']['iso'] == iso)}、"
              f"任職起日留空 {[x['row']['name'] for x in mine if not x['date']]}")
    for x in review:
        r = x["row"]
        print(f"  審閱 {r['iso']} 第{r['district_n']}區 {r['name']}：{x['reason']} → "
              f"{[(p, names.get(p)) for p in x['person_ids']]}")
