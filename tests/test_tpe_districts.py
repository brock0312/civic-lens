import unittest

from etl.sources.tpe_districts import check_announcement_pdf, flatten, village_rows, villcode


def _li(area, dept, li, name):
    return {"prv_code": "63", "city_code": "000", "area_code": area, "dept_code": dept,
            "li_code": li, "area_name": name}


DEPTS = {"110": "士林區", "010": "松山區", "999": "外星區"}

PDF_OK = """
    臺北巿      1      83,986,000
    新北市      1      106,551,000
    第1選舉區     北投區、士林區          12    3  10,853,000
    第2選舉區     內湖區、南港區           9    2  10,871,000
    第3選舉區     松山區、信義區           9    2  10,897,000
    第4選舉區     中山區、大同區           8    2  10,853,000
    第5選舉區     中正區、萬華區           8    2  10,811,000
臺
    第6選舉區     大安區、文山區          13    3  10,857,000
"""


class TestTpeDistricts(unittest.TestCase):
    def test_villcode_drops_leading_zero_of_li_code(self):
        self.assertEqual(villcode(_li("01", "110", "0027", "德行里")), "63000110027")

    def test_flatten_merges_grouped_lists(self):
        self.assertEqual(flatten({"a": [1, 2], "b": [3]}), [1, 2, 3])

    def test_village_rows_map_town_to_council_and_area_to_legislator(self):
        rows = village_rows(
            [_li("01", "110", "0027", "德行里"), _li("07", "010", "0012", "慈祐里")], DEPTS, "T"
        )
        got = {(r["villcode"], r["office"]): (r["town"], r["village"], r["district_id"]) for r in rows}
        self.assertEqual(got, {
            ("63000110027", "legislator"): ("士林區", "德行里", "ly-tpe-01"),
            ("63000110027", "tpe_councilor"): ("士林區", "德行里", "tpe-council-01"),
            ("63000010012", "legislator"): ("松山區", "慈祐里", "ly-tpe-07"),
            ("63000010012", "tpe_councilor"): ("松山區", "慈祐里", "tpe-council-03"),
        })

    def test_village_rows_reject_unknown_town(self):
        with self.assertRaises(ValueError):
            village_rows([_li("01", "999", "0001", "某里")], DEPTS, "T")

    def test_village_rows_reject_duplicate_villcode(self):
        li = _li("01", "110", "0027", "德行里")
        with self.assertRaises(ValueError):
            village_rows([li, li], DEPTS, "T")

    def test_check_announcement_pdf_accepts_announcement_text(self):
        check_announcement_pdf(PDF_OK)

    def test_check_announcement_pdf_rejects_changed_text(self):
        with self.assertRaises(ValueError):
            check_announcement_pdf(PDF_OK.replace("大安區、文山區          13", "大安區、文山區          12"))
        with self.assertRaises(ValueError):
            check_announcement_pdf("第1選舉區 石門區、三芝區 4")

    def test_check_announcement_pdf_rejects_missing_mayor_row(self):
        with self.assertRaises(ValueError):
            check_announcement_pdf(PDF_OK.replace("臺北巿      1      83,986,000", ""))


if __name__ == "__main__":
    unittest.main()
