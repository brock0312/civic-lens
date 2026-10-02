"""中選會 111 年地方選舉開票 JSON（全國 C 層檔）：議員與縣市長所有候選人（含當選註記）。

縣市以 area_name 對 national_districts.ISO（與 prv_code+city_code 一一對應，金門 09020、嘉義市 10020 不會混）。
"""
from pathlib import Path

from etl.fetch import get_json
from etl.sources.national_districts import COUNTIES, ISO

TICKETS = "https://db.cec.gov.tw/static/elections/data/tickets/ELC"
_FILE = "C/00_000_00_000_0000.json"
# (office_kind, 路徑)；嘉義市長只取重行選舉檔
SOURCES = [
    ("mayor", f"C1/00/05cc7b904c7a30cc7c88d5b10898c98e/{_FILE}"),
    ("mayor", f"C2/00/63615098f5afa8ec53159c4a86fc01d3/{_FILE}"),
    ("mayor", f"C2/00/1275d73551f2c0caf202e803b1766057/{_FILE}"),
    ("regional", f"T1/T1/25e12c45f9f5641aab4193598d5aff6e/{_FILE}"),
    ("plains", f"T1/T2/44cf35b1708568b94bb3b4c38a3fc74c/{_FILE}"),
    ("mountain", f"T1/T3/699b1ece9739edf4ec4662cea25a0bb3/{_FILE}"),
    ("regional", f"T2/T1/72976331a1ea6b85cfb1ed3380ae5f35/{_FILE}"),
    ("plains", f"T2/T2/c8f4dc82f282bed4ebcdf0f52552cf58/{_FILE}"),
    ("mountain", f"T2/T3/4ad215cf6c4ef28b25278bd1a13bc7bf/{_FILE}"),
]


def parse_candidates(payload, office_kind):
    """office_kind：mayor／regional／plains／mountain。回傳新 list，不改輸入。"""
    mayor = office_kind == "mayor"
    out = []
    for rows in payload.values():
        for c in rows:
            iso = ISO[c["area_name"]]
            by = (c.get("cand_birthyear") or "").strip()
            out.append({
                "iso": iso,
                "office": f"{iso}_{'mayor' if mayor else 'councilor'}",
                "kind": None if mayor else office_kind,
                "district_n": None if mayor else int(c["ori_area_code"]),
                "name": c["cand_name"],
                "cand_no": c["cand_no"],
                "birth_year": int(by) if by.isdigit() else None,
                "party": c["party_name"],
                "elected": c["is_victor"] in ("*", "!"),  # ! = 婦女保障名額
            })
    return out


def fetch_candidates():
    return [c for kind, path in SOURCES for c in parse_candidates(get_json(f"{TICKETS}/{path}"), kind)]


if __name__ == "__main__":
    import json
    from collections import Counter

    cache = Path("data/cache/v13")
    if not cache.exists():
        raise SystemExit("no data/cache/v13")
    names = ["c1", "c2", "c2r", "cec_T1_T1", "cec_T1_T2", "cec_T1_T3", "cec_T2_T1", "cec_T2_T2", "cec_T2_T3"]
    rows = [c for (kind, _), n in zip(SOURCES, names)
            for c in parse_candidates(json.loads((cache / f"{n}.json").read_text()), kind)]
    won = [c for c in rows if c["elected"]]
    council = Counter(c["iso"] for c in won if c["kind"])
    mayors = Counter(c["iso"] for c in won if not c["kind"])
    assert sum(council.values()) == 910, sum(council.values())
    assert len(mayors) == 22 and set(mayors.values()) == {1}, mayors
    print(" ".join(f"{name}{council[iso]}" for iso, name in COUNTIES))
    print("self-check ok")
