"""第 11 屆現任立法委員（立法院 API /legislators），串到 2026 地方選舉候選人。

網站只呈現 2026 候選人（HANDOFF §3 第 9 點），所以立委只有在參選縣市長或議員時才會出現：候選人標「現任立法委員」，
人物頁列任職與立法院問政紀錄（ly_records）。沒參選的現任立委照常建 person 與任職 fact，export 不輸出。

身分（PLAN §5）：person_source_id 用 歷屆立法委員編號（跨屆穩定）。串到 2026 候選人的條件比議員嚴：
- 自動串：區域立委、全國候選人中漢字同名只有 1 人、比對鍵（含拼音）相同、候選人在同一縣市、現任立委中漢字同名只有 1 人。
- 其餘（不分區、原住民立委、跨縣市參選、同名、拼音或異體字不同）進審閱，只印到 log；
  人工確認寫在 data/identity_legislators.csv，表內列出的才視為確認串接。
"""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from etl import lyapi
from etl.db import upsert, upsert_fact
from etl.fetch import now_utc
from etl.match import VARIANTS, han, name_key

SOURCE = "ly_legislator"
IDENTITY_PATH = Path(__file__).resolve().parents[2] / "data" / "identity_legislators.csv"
FACT_PREFIX = f"office:ly-{lyapi.TERM}:"
_VAR = str.maketrans(VARIANTS)


def load_identity(path=IDENTITY_PATH):
    """人工確認表 → {歷屆立法委員編號: (person_id, verified_by)}。檔案不存在視為空表；缺欄位或重複就 raise。"""
    if not Path(path).exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for r in rows:
        k = str(r["bio_id"]).strip()
        if k in out:
            raise ValueError(f"identity_legislators.csv 重複：{k}")
        if not (k and r["person_id"] and r["confirmed_by"] and r["confirmed_at"]):
            raise ValueError(f"identity_legislators.csv 缺 bio_id、person_id、confirmed_by 或 confirmed_at：{r}")
        out[k] = (r["person_id"], f"人工確認：{r['confirmed_by']} {r['confirmed_at']}")
    return out


def _cand_iso(district_id):
    return district_id.split("-")[0]


def plan(legislators, candidates, identity):
    """現任立委 → ([{row, bio_id, person_id, verified_by}], 審閱清單)。person_id 為 None 代表沒對到候選人、要新建。純函式。

    legislators：/legislators 的列（已篩現任）；candidates：2026 候選人 {person_id, name, district_id}。
    """
    by_key, by_han = defaultdict(list), defaultdict(list)
    for c in candidates:
        by_key[name_key(c["name"])].append(c)
        by_han[han(c["name"]).translate(_VAR)].append(c)
    leg_han = Counter(han(r["委員姓名"]).translate(_VAR) for r in legislators)

    rows, review = [], []
    for r in legislators:
        bio_id, name = str(r["歷屆立法委員編號"]), r["委員姓名"]
        h = han(name).translate(_VAR)
        out = {"row": r, "bio_id": bio_id, "person_id": None,
               "verified_by": "auto: 立法院 API 第 11 屆委員名單，未串到 2026 候選人"}
        rows.append(out)
        if bio_id in identity:
            out["person_id"], out["verified_by"] = identity[bio_id]
            continue
        hits = by_han.get(h, [])
        if not hits:
            continue  # 沒有參選 2026
        exact = by_key.get(name_key(name), [])
        iso, _ = lyapi.area(r.get("選區名稱"))
        if len(hits) > 1 or leg_han[h] > 1:
            reason = "duplicate_name"
        elif not exact:
            reason = "romanization_or_variant"
        elif iso is None:
            reason = "at_large_or_indigenous"  # 不分區、原住民立委：沒有縣市可比，一律人工確認
        elif _cand_iso(exact[0]["district_id"]) != iso:
            reason = "other_county"
        else:
            out["person_id"] = exact[0]["person_id"]
            out["verified_by"] = ("auto: 全國漢字同名唯一、比對鍵相同、同縣市"
                                  "（立法院 API 第 11 屆委員名單 vs 2026 候選人登記彙總表）")
            continue
        review.append({"bio_id": bio_id, "name": name, "area": r.get("選區名稱"), "reason": reason,
                       "person_ids": [c["person_id"] for c in hits]})
    return rows, review


def office_data(r, valid_districts):
    """任職 fact 的 data。district_id 只在 district 表有這個立委選區時才填，其餘只留選區名稱文字。"""
    _, district_id = lyapi.area(r.get("選區名稱"))
    data = {"office": "legislator", "title": "立法委員", "term": lyapi.TERM, "ly_name": r["委員姓名"],
            "area_name": r.get("選區名稱") or ""}
    if district_id in valid_districts:
        data["district_id"] = district_id
    if r.get("黨籍"):
        data["party"] = r["黨籍"]
    return data


def run(conn):
    fetched_at = now_utc()
    rows, list_url = lyapi.fetch_all("legislators", {"屆": lyapi.TERM})
    current = [r for r in rows if lyapi.is_current(r)]
    if not 100 <= len(current) <= 113:  # 總額 113 席；遞補前後可能短暫少於 113
        raise ValueError(f"第 {lyapi.TERM} 屆現任立委 {len(current)} 人，不在 100–113 之間，請檢查離職欄位")
    cands = [{"person_id": r["person_id"], "name": r["name"], "district_id": json.loads(r["data"])["district_id"]}
             for r in conn.execute("SELECT f.person_id, p.name, f.data FROM fact f JOIN person p USING (person_id) "
                                   "WHERE f.kind = 'candidacy'")]
    valid = {d for (d,) in conn.execute("SELECT district_id FROM district WHERE office = 'legislator'")}
    planned, review = plan(current, cands, load_identity())

    keys = set()
    for x in planned:
        r, person_id = x["row"], x["person_id"]
        if not person_id:
            person_id = "p" + hashlib.sha1(f"{SOURCE}:{x['bio_id']}".encode()).hexdigest()[:10]
            upsert(conn, "person", {"person_id": person_id, "name": r["委員姓名"]}, ("person_id",))
        upsert(conn, "person_source_id",
               {"source": SOURCE, "source_key": x["bio_id"], "person_id": person_id, "verified_by": x["verified_by"]},
               ("source", "source_key"))
        data = office_data(r, valid)
        if r.get("選區名稱") and lyapi.area(r["選區名稱"])[0] and "district_id" not in data:
            print(f"注意：{r['委員姓名']} 的選區「{r['選區名稱']}」不在 district 表，任職只留選區名稱")
        key = f"{FACT_PREFIX}{person_id}"
        keys.add(key)
        upsert_fact(conn, key, person_id, "office", data,
                    lyapi.item_url("legislator", lyapi.TERM, r["委員姓名"]), fetched_at, date=lyapi.to_date(r.get("到職日")))
    # 現任以 API 名單為準：離職（或改串他人）的舊任職要刪掉
    for (k,) in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE ?", (f"{FACT_PREFIX}%",)).fetchall():
        if k not in keys:
            conn.execute("DELETE FROM fact WHERE fact_key = ?", (k,))

    linked = [x for x in planned if x["person_id"]]
    print(f"第 {lyapi.TERM} 屆現任立委 {len(current)} 人（{list_url}）：串到 2026 候選人 {len(linked)} 人、審閱 {len(review)} 人")
    for x in linked:
        print(f"  串接 {x['row']['委員姓名']}（{x['row'].get('選區名稱')}）→ {x['person_id']}：{x['verified_by']}")
    for x in review:
        print(f"  審閱 {x['name']}（{x['area']}，編號 {x['bio_id']}）：{x['reason']} → {x['person_ids']}")
