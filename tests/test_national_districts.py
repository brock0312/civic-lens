import io
import struct
import unittest
import zipfile

from etl import moi
from etl.sources import national_districts as nd

# 1153150253 號公告 pdftotext -layout 的節錄（原文「市」有異體字「巿」）
ANN_TEXT = """
 一、選舉種類：
  (一)直轄市長：臺北市第9屆、新北市、臺中市、臺南市、高
           雄市第5屆、桃園市第4屆市長。
 三、選舉區劃分、名額及競選經費最高金額訂定如下：
(一)直轄市長：
    選舉區      名額
    臺北巿      1      83,986,000
    新北市      1      106,551,000
    桃園巿      1      82,989,000
    臺中市      1      90,149,000
    臺南市      1      75,886,000
    高雄巿      1      87,960,000
（二）縣（市）長：
    新竹縣      1      38,376,000
    苗栗縣      1      37,420,000
    彰化縣      1      46,865,000
    南投縣      1      36,543,000
    雲林縣      1      39,074,000
    嘉義縣      1      36,592,000
    屏東縣      1      40,915,000
    宜蘭縣      1      36,282,000
    花蓮縣      1      34,360,000
    臺東縣      1      32,912,000
    澎湖縣      1      31,494,000
    金門縣      1      31,933,000
    連江縣      1      30,192,000
    基隆市      1      35,024,000
    新竹市      1      36,382,000
    嘉義市      1      33,662,000
(三) 直轄市議員：
"""

# 新竹縣（竹北市切成兩區、山地原住民依鄉鎮分兩區）與澎湖縣（沒有原住民選區）的議員表
TABLES = {
    "新竹縣": [
        {"n": 1, "seats": 4, "range": "竹北市尚義里、崇義里"},
        {"n": 2, "seats": 9, "range": "竹北市竹北里、竹仁里"},
        {"n": 3, "seats": 5, "range": "湖口鄉"},
        {"n": 4, "seats": 1, "range": "尖石鄉、五峰鄉"},
        {"n": 5, "seats": 1, "range": "新竹縣之平地原住民"},
        {"n": 6, "seats": 1, "range": "尖石鄉及竹北市、湖口鄉之山地原住民"},
        {"n": 7, "seats": 1, "range": "五峰鄉之山地原住民"},
    ],
    "澎湖縣": [{"n": 1, "seats": 19, "range": "馬公市"}],
}
TOTALS = """
                         議員總額：22名
                         一、區域：19名
     合計
                         二、平地原住民：1名
                         三、山地原住民：2名
                         議員總額：19名
"""


def vill(code, county, town, name):
    return {"VILLCODE": code, "COUNTYNAME": county, "COUNTYCODE": code[:5], "TOWNNAME": town, "VILLNAME": name}


VILLAGES = [
    vill("10004010001", "新竹縣", "竹北市", "尚義里"), vill("10004010002", "新竹縣", "竹北市", "崇義里"),
    vill("10004010003", "新竹縣", "竹北市", "竹北里"), vill("10004010004", "新竹縣", "竹北市", "竹仁里"),
    vill("10004020001", "新竹縣", "湖口鄉", "湖口村"), vill("10004030001", "新竹縣", "尖石鄉", "新樂村"),
    vill("10004040001", "新竹縣", "五峰鄉", "大隘村"), vill("10016010001", "澎湖縣", "馬公市", "重慶里"),
]


def by(rows, office):
    return {r["villcode"]: r["district_id"] for r in rows if r["office"] == office}


class TestAnnouncement(unittest.TestCase):
    def test_parse_mayors_reads_all_22_counties_despite_variant_character(self):
        got = nd.parse_mayors(ANN_TEXT)
        self.assertEqual(len(got), 22)
        self.assertEqual(got["臺北市"], 1)

    def test_parse_mayors_rejects_missing_county(self):
        with self.assertRaises(ValueError):
            nd.parse_mayors(ANN_TEXT.replace("    連江縣      1      30,192,000\n", ""))

    def test_parse_totals_reads_subtotals_and_county_without_indigenous(self):
        text = TOTALS * 11  # parse_totals 要求 22 個合計格
        got = nd.parse_totals(text)
        self.assertEqual(got[0], {"total": 22, "regional": 19, "plains": 1, "mountain": 2})
        self.assertEqual(got[1], {"total": 19, "regional": 19, "plains": 0, "mountain": 0})

    def test_check_totals_passes_when_seats_add_up(self):
        nd.check_totals(TABLES, nd.parse_totals(TOTALS * 11)[:2])

    def test_check_totals_raises_when_seats_do_not_add_up(self):
        tables = {**TABLES, "新竹縣": [{**TABLES["新竹縣"][0], "seats": 5}] + TABLES["新竹縣"][1:]}
        with self.assertRaises(ValueError):
            nd.check_totals(tables, nd.parse_totals(TOTALS * 11)[:2])

    def test_district_rows_label_indigenous_districts(self):
        rows = {r["district_id"]: r for r in nd.district_rows(TABLES, {"新竹縣": 1, "澎湖縣": 1})}
        self.assertEqual(rows["hsq-council-02"]["name"], "新竹縣第2選舉區")
        self.assertEqual(rows["hsq-council-05"]["name"], "新竹縣第5選舉區（平地原住民）")
        self.assertEqual(rows["hsq-council-07"]["name"], "新竹縣第7選舉區（山地原住民）")
        self.assertEqual((rows["hsq-mayor"]["office"], rows["hsq-mayor"]["seats"]), ("hsq_mayor", 1))


class TestVillageRows(unittest.TestCase):
    def setUp(self):
        self.rows = nd.village_rows(TABLES, VILLAGES, "T")

    def test_zhubei_city_split_into_two_districts_by_village(self):
        got = by(self.rows, "hsq_councilor")
        self.assertEqual(got["10004010001"], "hsq-council-01")
        self.assertEqual(got["10004010002"], "hsq-council-01")
        self.assertEqual(got["10004010003"], "hsq-council-02")
        self.assertEqual(got["10004010004"], "hsq-council-02")
        self.assertEqual(got["10004030001"], "hsq-council-04")

    def test_indigenous_districts_follow_town(self):
        self.assertEqual(set(by(self.rows, "hsq_councilor_plains").values()), {"hsq-council-05"})
        mountain = by(self.rows, "hsq_councilor_mountain")
        self.assertEqual(mountain["10004010003"], "hsq-council-06")
        self.assertEqual(mountain["10004030001"], "hsq-council-06")
        self.assertEqual(mountain["10004040001"], "hsq-council-07")

    def test_county_without_indigenous_districts_gets_no_indigenous_rows(self):
        offices = {r["office"] for r in self.rows if r["villcode"] == "10016010001"}
        self.assertEqual(offices, {"pen_councilor"})

    def test_taipei_only_gets_indigenous_rows(self):
        tables = {"臺北市": [{"n": 1, "seats": 59, "range": "北投區"},
                           {"n": 7, "seats": 1, "range": "臺北市之平地原住民"},
                           {"n": 8, "seats": 1, "range": "臺北市之山地原住民"}]}
        rows = nd.village_rows(tables, [vill("63000120001", "臺北市", "北投區", "建民里")], "T")
        self.assertEqual({(r["office"], r["district_id"]) for r in rows},
                         {("tpe_councilor_plains", "tpe-council-07"), ("tpe_councilor_mountain", "tpe-council-08")})

    def test_town_missing_from_indigenous_districts_raises(self):
        tables = {"新竹縣": TABLES["新竹縣"][:6]}  # 少了五峰鄉的山地原住民選區
        with self.assertRaises(ValueError):
            nd.village_rows(tables, VILLAGES, "T")

    def test_village_missing_from_regional_districts_raises(self):
        with self.assertRaises(ValueError):
            nd.village_rows(TABLES, VILLAGES + [vill("10004010099", "新竹縣", "竹北市", "新設里")], "T")

    def test_village_in_two_districts_raises(self):
        tables = {"新竹縣": TABLES["新竹縣"] + [{"n": 8, "seats": 1, "range": "竹北市竹北里"}]}
        with self.assertRaises(ValueError):
            nd.village_rows(tables, VILLAGES, "T")


def dbf(fields, records):
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(n for _, n in fields)
    out = bytearray(struct.pack("<BBBBIHH20x", 3, 126, 8, 17, len(records), header_len, record_len))
    for name, n in fields:
        out += name.encode().ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([n]) + b"\0" * 15
    out += b"\x0d"
    for flag, values in records:
        out += flag + b"".join(v.encode().ljust(n, b" ") for v, (_, n) in zip(values, fields))
    return bytes(out)


class TestMoiVillages(unittest.TestCase):
    def test_reads_named_villages_from_dbf_inside_zip(self):
        fields = [("VILLCODE", 11), ("COUNTYNAME", 9), ("VILLNAME", 12)]
        data = dbf(fields, [(b" ", ["10004010001", "新竹縣", "尚義里"]),
                            (b" ", ["10004010002", "新竹縣", ""]),          # 未編定村里
                            (b"*", ["10004010003", "新竹縣", "已刪除里"])])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("VILLAGE_NLSC_1150817.dbf", data)
        self.assertEqual(moi.villages_from_zip(buf.getvalue()),
                         [{"VILLCODE": "10004010001", "COUNTYNAME": "新竹縣", "VILLNAME": "尚義里"}])


if __name__ == "__main__":
    unittest.main()
