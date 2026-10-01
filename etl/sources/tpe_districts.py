"""臺北市「里 → 立委選區／議員選區」對照，以及選區本身（M2）。"""
import re

from etl.db import upsert
from etl.fetch import get, get_json, now_utc, pdf_text

# 中選會 2024 第 11 屆立委開票 JSON（L1 = 區域立委）
LY_BASE = "https://db.cec.gov.tw/static/elections/data/areas/ELC/L0/L1/9c96a2080bfc199c590ec54f3a2bda7b"
LY_AREA_URL = f"{LY_BASE}/A/63_000_00_000_0000.json"
LY_DEPT_URL = f"{LY_BASE}/D/63_000_00_000_0000.json"
LY_LI_URL = f"{LY_BASE}/L/63_000_00_000_0000.json"

# 中選會 115-08-20 中選務字第1153150253號公告（選舉種類、名額、選舉區之劃分）
COUNCIL_URL = "https://web.cec.gov.tw/api/file/45d8e965-f63a-46d5-b636-7d81e47cf4d1.pdf"
# 市長應選名額出自同一份 1153150253 號公告的「三、(一) 直轄市長」表；check_announcement_pdf 會核對該列
MAYOR_URL = COUNCIL_URL

# 區域選區：選區 → (行政區, 應選名額)；每次執行都會用 check_announcement_pdf 對公告原文核對
COUNCIL_AREAS = {
    1: (("北投區", "士林區"), 12),
    2: (("內湖區", "南港區"), 9),
    3: (("松山區", "信義區"), 9),
    4: (("中山區", "大同區"), 8),
    5: (("中正區", "萬華區"), 8),
    6: (("大安區", "文山區"), 13),
}
# 原住民選區看身分，不看戶籍，所以不寫進 village_district
COUNCIL_INDIGENOUS = {7: "臺北市第7選舉區（平地原住民）", 8: "臺北市第8選舉區（山地原住民）"}

TOWN_TO_COUNCIL = {town: n for n, (towns, _) in COUNCIL_AREAS.items() for town in towns}


def council_id(n):
    return f"tpe-council-{n:02d}"


def flatten(obj):
    # 開票 JSON 外層是 {分組鍵: [列, ...]}
    return [row for rows in obj.values() for row in rows]


def villcode(row):
    if row["li_code"][0] != "0":
        raise ValueError(f"li_code 首碼不是 0，VILLCODE 公式不適用：{row}")
    return row["prv_code"] + row["city_code"] + row["dept_code"] + row["li_code"][1:]


def council_for_town(town):
    if town not in TOWN_TO_COUNCIL:
        raise ValueError(f"行政區 {town!r} 不在議員選區對照表")
    return council_id(TOWN_TO_COUNCIL[town])


def check_announcement_pdf(text):
    """確認寫死的市長名額與議員 01–06 對照都在公告原文裡；確認不到就 raise。"""
    flat = re.sub(r"\s+", " ", text)
    # 原文用異體字「巿」
    if not re.search(r"臺北[市巿]\s+1\s+[\d,]+", flat):
        raise ValueError("公告 PDF 找不到臺北市長應選 1 名的列")
    for n, ((a, b), seats) in COUNCIL_AREAS.items():
        needle = f"第{n}選舉區 {a}、{b} {seats} "
        if needle not in flat:
            raise ValueError(f"公告 PDF 找不到「{needle.strip()}」")


def village_rows(li_rows, dept_names, fetched_at):
    """L 檔的每個里產生立委、議員兩列 village_district。"""
    rows = []
    for li in li_rows:
        code = villcode(li)
        town = dept_names[li["dept_code"]]
        common = {"villcode": code, "town": town, "village": li["area_name"], "fetched_at": fetched_at}
        rows.append({**common, "office": "legislator", "district_id": f"ly-tpe-{li['area_code']}",
                     "source_url": LY_LI_URL})
        rows.append({**common, "office": "tpe_councilor", "district_id": council_for_town(town),
                     "source_url": COUNCIL_URL})

    codes = [r["villcode"] for r in rows if r["office"] == "legislator"]
    if len(codes) != len(set(codes)):
        raise ValueError("VILLCODE 重複")
    offices = {}
    for r in rows:
        offices.setdefault(r["villcode"], set()).add(r["office"])
    missing = [c for c, o in offices.items() if o != {"legislator", "tpe_councilor"}]
    if missing:
        raise ValueError(f"缺立委或議員對照：{missing}")
    return rows


def run(conn):
    fetched_at = now_utc()
    check_announcement_pdf(pdf_text(get(COUNCIL_URL)))

    area_rows = flatten(get_json(LY_AREA_URL))
    dept_names = {r["dept_code"]: r["area_name"] for r in flatten(get_json(LY_DEPT_URL))}
    li_rows = flatten(get_json(LY_LI_URL))

    districts = [
        {"district_id": f"ly-tpe-{a['area_code']}", "office": "legislator", "name": a["area_name"],
         "seats": 1, "source_url": LY_AREA_URL}
        for a in area_rows
    ]
    districts += [
        {"district_id": council_id(n), "office": "tpe_councilor", "name": f"臺北市第{n}選舉區",
         "seats": seats, "source_url": COUNCIL_URL}
        for n, (_, seats) in COUNCIL_AREAS.items()
    ]
    districts += [
        {"district_id": council_id(n), "office": "tpe_councilor", "name": name,
         "seats": 1, "source_url": COUNCIL_URL}
        for n, name in COUNCIL_INDIGENOUS.items()
    ]
    districts.append({"district_id": "tpe-mayor", "office": "tpe_mayor", "name": "臺北市",
                      "seats": 1, "source_url": MAYOR_URL})

    # 先寫 district 再寫 village_district（FK）
    for d in districts:
        upsert(conn, "district", {**d, "fetched_at": fetched_at}, ("district_id",))
    for row in village_rows(li_rows, dept_names, fetched_at):
        upsert(conn, "village_district", row, ("villcode", "office"))
