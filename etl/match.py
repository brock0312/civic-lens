"""把舊紀錄的人（2022 當選人、議會名錄）串到 2026 候選人：全部條件成立才自動串，其餘進審閱或未登記。純函式。"""
import re
from collections import Counter, defaultdict

from etl.sources.national_districts import council_id

# 異體字只產生審閱，不自動串接；之後可加
VARIANTS = {"啓": "啟", "釆": "采", "黄": "黃"}
_VAR = str.maketrans(VARIANTS)
_SEP = re.compile(r"[\s・·‧•．.]")  # 原住民姓名的間隔號：2022 開票 JSON 多用全形「．」，2026 名冊用「‧」


def _norm(name):
    return _SEP.sub("", name)


_ROMAN = re.compile(r"(?<![@0-9A-Za-z])[A-Za-z]+(?![@0-9A-Za-z])")  # 不碰中選會造字碼（如 @FA3E@）


def han(name):
    """姓名去掉羅馬拼音、括號、空白與間隔號後剩下的部分（漢字）。"""
    return re.sub(r"[()（）]", "", _norm(_ROMAN.sub("", name)))


def name_key(name):
    """比對鍵：漢字部分＋羅馬拼音詞的多重集合（小寫）。原住民姓名在官網名錄與中選會的拼音詞序不同。"""
    return han(name), tuple(sorted(w.lower() for w in _ROMAN.findall(name)))


def _iso(district_id):
    return district_id.split("-")[0]


def _districts_2026(rec):
    iso, n = rec["iso"], rec["district_n"]
    if iso == "hsq":  # 新竹縣 2022 第 1 區 → 2026 第 1、2 區；其餘 +1
        ns = (1, 2) if n == 1 else (n + 1,)
    else:
        ns = (n,)
    return {council_id(iso, k) for k in ns}


def _overlap(rec, district_id):
    iso = rec["iso"]
    if rec["office"] == "mayor":
        return district_id == f"{iso}-mayor" or district_id.startswith(f"{iso}-council-")
    return district_id == f"{iso}-mayor" or district_id in _districts_2026(rec)


def match(records, candidates):
    cands = defaultdict(list)  # (iso, 比對鍵) -> candidates
    han_idx, var_idx = defaultdict(list), defaultdict(list)
    for c in candidates:
        iso, k = _iso(c["district_id"]), name_key(c["name"])
        cands[(iso, k)].append(c)
        han_idx[(iso, k[0])].append(c)
        var_idx[(iso, k[0].translate(_VAR))].append(c)
    rec_count = Counter((r["iso"], name_key(r["name"])[0]) for r in records)

    links, review, unregistered = [], [], []
    for r in records:
        k = (r["iso"], name_key(r["name"]))
        exact = cands.get(k, [])
        if not exact:
            # 漢字相同、拼音不同（或只有一邊有拼音）：進審閱，不自動串
            for reason, hits in (("romanization", han_idx.get((r["iso"], k[1][0]), [])),
                                 ("variant", var_idx.get((r["iso"], k[1][0].translate(_VAR)), []))):
                if hits:
                    review.append({"key": r["key"], "person_ids": [c["person_id"] for c in hits], "reason": reason})
                    break
            else:
                unregistered.append(r["key"])
            continue
        ids = [c["person_id"] for c in exact]
        if len(han_idx[(r["iso"], k[1][0])]) > 1 or rec_count[(r["iso"], k[1][0])] > 1:  # 漢字相同者超過 1 人（含「X」與「X Abc」）
            review.append({"key": r["key"], "person_ids": ids, "reason": "duplicate_name"})
        elif _overlap(r, exact[0]["district_id"]):
            links.append({"key": r["key"], "person_id": ids[0]})
        else:
            review.append({"key": r["key"], "person_ids": ids, "reason": "no_overlap"})
    return {"links": links, "review": review, "unregistered": unregistered}


if __name__ == "__main__":
    import json
    import sqlite3
    from pathlib import Path

    from etl.cec2022 import SOURCES, parse_candidates

    cache = Path("data/cache/v13")
    names = ["c1", "c2", "c2r", "cec_T1_T1", "cec_T1_T2", "cec_T1_T3", "cec_T2_T1", "cec_T2_T2", "cec_T2_T3"]
    rows = [c for (kind, _), n in zip(SOURCES, names)
            for c in parse_candidates(json.loads((cache / f"{n}.json").read_text()), kind)]
    recs = [{"key": i, "iso": c["iso"], "name": c["name"],
             "office": "mayor" if c["district_n"] is None else "councilor", "district_n": c["district_n"]}
            for i, c in enumerate(c for c in rows if c["elected"] and c["iso"] != "tpe")]
    db = sqlite3.connect(":memory:")
    db.executescript(Path("data/civic.sql").read_text(encoding="utf-8"))
    cands = [{"person_id": p, "name": n, "district_id": json.loads(d)["district_id"]} for p, n, d in db.execute(
        "SELECT f.person_id, p.name, f.data FROM fact f JOIN person p ON p.person_id = f.person_id WHERE f.kind = 'candidacy'")]
    out = match(recs, cands)
    print("links", len(out["links"]), "review", len(out["review"]), "unregistered", len(out["unregistered"]))
    for x in out["review"]:
        print("  ", recs[x["key"]]["iso"], recs[x["key"]]["name"], x["reason"], x["person_ids"])
