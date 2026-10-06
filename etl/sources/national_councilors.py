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
from etl.match import VARIANTS, _districts_2026, han, match
from etl.rosters import ROSTER_URLS, fetch_roster
from etl.sources.national_heads import MOI_INAUGURATION
from etl.sources.national_districts import COUNTIES, council_id

SOURCE = "roster_2026"
ISOS = ["nwt", "tao", "txg", "tnn", "khh", "kee", "cyq", "nan", "mia", "hua", "cha", "hsq", "hsz", "kin", "lie",
        "yun", "pen", "pif", "ila", "ttt"]
# 現任數：五都依 V13 §3；其餘依 python3 -m etl.rosters 快取自我檢查（2026-10-02），yun～ttt 於 2026-10-05 線上重抓一致
EXPECTED = {"nwt": 64, "tao": 61, "txg": 62, "tnn": 55, "khh": 61,
            "kee": 28, "cyq": 37, "nan": 34, "mia": 36, "hua": 32,
            "cha": 53, "hsq": 37, "hsz": 33, "kin": 19, "lie": 9,
            "yun": 42, "pen": 19, "pif": 51, "ila": 33, "ttt": 30}
# 嘉義市議會 robots.txt 禁止所有爬蟲：不爬名錄，以中選會 2022 當選人建立任職，前端標「2022 當選」而非「現任」（V13 已定案第 3 點）
CEC_ISOS = ["cyi"]
CEC_BASIS = "cec_2022"
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
    # 同縣市同選區、漢字相同（異體字視為相同）即為同一席；不看拼音詞序。@FA3E@ 是中選會「慨」的造字碼（澎湖 歐中慨）
    return iso, n, han(name.replace("@FA3E@", "慨")).translate(_VAR)


def assign_districts(roster, won):
    """名錄沒有選區（澎湖）：縣內 2022 當選人中同名者唯一才補上選區；其餘（遞補等）回傳到審閱清單、不寫任職。純函式。"""
    out, review = [], []
    for r in roster:
        if r["district_n"] is not None or not r["current"]:
            out.append(r)
            continue
        hits = [c["district_n"] for c in won if _seat_key(c["iso"], 0, c["name"]) == _seat_key(r["iso"], 0, r["name"])]
        if len(hits) == 1:
            out.append({**r, "district_n": hits[0]})
        else:
            review.append({"row": r, "person_ids": [],
                           "reason": "no_2022_district" if not hits else "ambiguous_2022_district"})
    return out, review


def cec_roster(won):
    """嘉義市：2022 當選人當作名錄列，帶 basis 與開票 JSON 網址。"""
    return [{"iso": c["iso"], "district_n": c["district_n"], "name": c["name"], "current": True, "note": "",
             "basis": CEC_BASIS, "source_url": c.get("source_url")}
            for c in won if c["iso"] in CEC_ISOS]


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
        basis = r.get("basis")
        src = "中選會 2022 當選名單" if basis else "議會官網現任名錄"
        if manual:
            person_id, verified_by = manual
        elif i in links:
            person_id = links[i]
            verified_by = f"auto: etl.match 唯一同名、同縣市且選區重疊（{src} vs 2026 候選人登記彙總表）"
        else:
            person_id, verified_by = None, f"auto: {src}，未串到 2026 候選人"
        w = seats.get(_seat_key(r["iso"], r["district_n"], r["name"]))
        data = {"office": f"{r['iso']}_councilor", "district_id": council_id(r["iso"], r["district_n"]),
                "title": f"{NAMES[r['iso']]}議員"}
        new = sorted(_districts_2026({"iso": r["iso"], "district_n": r["district_n"]}))
        if new != [data["district_id"]]:
            # 名錄是 2022 劃分、2026 改了界線（新竹縣）：區號不能當 2026 選區 id。
            # 改用 2022 專屬 id（公報串接仍取得 2022 區號），寫出 2022 選區名稱，並列出對應的 2026 選區供「現任」比對
            data["district_id"] = f"{r['iso']}-council-2022-{r['district_n']:02d}"
            data["district_name"] = f"{NAMES[r['iso']]}第{r['district_n']}選舉區（2022 年劃分）"
            data["districts_2026"] = new
        if r.get("party"):
            data["party"] = r["party"]
        elif w:  # 名錄沒有政黨時用 2022 推薦政黨，前端標「2022 推薦」，避免換黨者顯示成目前政黨
            data["party"], data["party_year"] = w["party"], 2022
            if w.get("source_url"):
                data["party_source_url"], data["party_source_label"] = w["source_url"], "中選會 2022 開票結果"
        if basis:  # 只知道 2022 當選，不知道是否仍在任：不寫任職起日
            data["basis"] = basis
            w = None
        if w:
            data["inauguration_source_url"], data["inauguration_source_label"] = MOI_INAUGURATION
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
        url = f"{TICKETS}/{path}"
        won += [{**c, "source_url": url} for c in parse_candidates(get_json(url), kind) if c["elected"] and c["iso"] in ISOS + CEC_ISOS]
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
    roster, unplaced = assign_districts(roster, won)
    rows, review = plan(roster + cec_roster(won), won, cands, load_identity())
    review = review + unplaced
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
        upsert_fact(conn, key, person_id, "office", x["data"], r.get("source_url") or roster_url(r["iso"], r["district_n"]), fetched_at,
                    date=x["date"])
    # 現任以名錄為準：離開名錄（或改串他人）的舊任職要刪掉，不再顯示為現任
    for iso in ISOS + CEC_ISOS:
        for (k,) in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE ?", (f"office:{iso}-council-2022:%",)).fetchall():
            if k not in keys:
                conn.execute("DELETE FROM fact WHERE fact_key = ?", (k,))
    for iso in ISOS + CEC_ISOS:
        mine = [x for x in rows if x["row"]["iso"] == iso]
        print(f"{iso} 現任議員：{len(mine)} 人，串到 2026 候選人 {sum(1 for x in mine if x['person_id'])}、"
              f"新建 {sum(1 for x in mine if not x['person_id'])}、審閱 {sum(1 for x in review if x['row']['iso'] == iso)}、"
              f"任職起日留空 {[x['row']['name'] for x in mine if not x['date']]}")
    for x in review:
        r = x["row"]
        print(f"  審閱 {r['iso']} 第{r['district_n']}區 {r['name']}：{x['reason']} → "
              f"{[(p, names.get(p)) for p in x['person_ids']]}")
