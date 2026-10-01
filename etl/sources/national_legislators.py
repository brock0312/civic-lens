"""全國（臺北以外 21 縣市）村里 → 區域立委選區，以及立委選區本身（L1，V2 §3）。

來源：中選會 2024 第 11 屆立委開票 JSON 的 A（選區）與 L（村里）層級；以內政部現行村里表為主表：
1. VILLCODE 直接命中 L 檔 → 用該列的選區；
2. 沒命中（2024 年後新設或更名）但所在鄉鎮市區只屬一個選區 → 繼承；
3. 其餘（跨選區鄉鎮的新里）不猜，不寫入，印出清單待人工判定。
臺北由 tpe_districts 負責。
"""
import time

from etl import moi
from etl.db import upsert
from etl.fetch import get_json, now_utc
from etl.sources.national_districts import ISO
from etl.sources.tpe_districts import LY_BASE, flatten

LIST_URL = f"{LY_BASE}/C/00_000_00_000_0000.json"


def county_urls(prv, city):
    key = f"{prv}_{city}_00_000_0000.json"
    return f"{LY_BASE}/A/{key}", f"{LY_BASE}/L/{key}"


def ly_id(iso, area_code):
    return f"ly-{iso}-{area_code}"


def village_rows(iso, villages, li_rows, source_url, fetched_at):
    """回傳 (village_district 列, 對不上的村里)。"""
    by_code, by_dept = {}, {}
    for li in li_rows:
        by_dept.setdefault(li["dept_code"], set()).add(li["area_code"])
        # 合併開票單位（li_code 首碼不是 0，例如連江縣「復興村、福沃村」）沒有對應的 VILLCODE，只拿來判斷鄉鎮歸屬
        if li["li_code"][0] == "0":
            by_code[li["prv_code"] + li["city_code"] + li["dept_code"] + li["li_code"][1:]] = li["area_code"]

    rows, unmatched = [], []
    for v in villages:
        area = by_code.get(v["VILLCODE"])
        if area is None:
            areas = by_dept.get(v["TOWNCODE"][5:8], set())
            if len(areas) != 1:
                unmatched.append((v["VILLCODE"], v["COUNTYNAME"], v["TOWNNAME"], v["VILLNAME"], sorted(areas)))
                continue
            area = next(iter(areas))
        rows.append({"villcode": v["VILLCODE"], "office": "legislator", "town": v["TOWNNAME"],
                     "village": v["VILLNAME"], "district_id": ly_id(iso, area),
                     "source_url": source_url, "fetched_at": fetched_at})
    return rows, unmatched


def run(conn):
    fetched_at = now_utc()
    villages = moi.villages()
    code_to_iso = {v["COUNTYCODE"]: ISO[v["COUNTYNAME"]] for v in villages}
    by_county = {}
    for v in villages:
        by_county.setdefault(v["COUNTYCODE"], []).append(v)

    counties = flatten(get_json(LIST_URL))
    codes = {c["prv_code"] + c["city_code"] for c in counties}
    if codes != set(code_to_iso):
        raise ValueError(f"立委 C 檔縣市與村里表不符：{sorted(codes ^ set(code_to_iso))}")

    all_unmatched = []
    for c in counties:
        code = c["prv_code"] + c["city_code"]
        iso = code_to_iso[code]
        if iso == "tpe":
            continue
        area_url, li_url = county_urls(c["prv_code"], c["city_code"])
        time.sleep(1.1)
        areas = flatten(get_json(area_url))
        time.sleep(1.1)
        li_rows = flatten(get_json(li_url))

        valid = {a["area_code"] for a in areas}
        for a in areas:
            upsert(conn, "district", {"district_id": ly_id(iso, a["area_code"]), "office": "legislator",
                                      "name": a["area_name"], "seats": 1, "source_url": area_url,
                                      "fetched_at": fetched_at}, ("district_id",))
        rows, unmatched = village_rows(iso, by_county[code], li_rows, li_url, fetched_at)
        stray = {r["district_id"] for r in rows} - {ly_id(iso, a) for a in valid}
        if stray:
            raise ValueError(f"{c['area_name']} L 檔出現 A 檔沒有的選區：{sorted(stray)}")
        for row in rows:
            upsert(conn, "village_district", row, ("villcode", "office"))
        all_unmatched += unmatched

    for u in all_unmatched:
        print(f"注意：立委選區對不上（跨選區鄉鎮的新里，未寫入）：{u}")
