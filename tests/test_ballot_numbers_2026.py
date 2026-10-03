import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ballot_numbers_2026 as b  # noqa: E402


class BallotNumbersTest(unittest.TestCase):
    def test_district_names_map_to_ids(self):
        self.assertEqual(b.district_of("臺北市第01選舉區"), "tpe-council-01")
        self.assertEqual(b.district_of("台中市第 3 選區"), "txg-council-03")
        self.assertEqual(b.district_of("新竹縣"), "hsq-mayor")
        self.assertEqual(b.district_of("第12選舉區", "新北市議員選舉"), "nwt-council-12")
        self.assertIsNone(b.district_of("第12選舉區"))
        self.assertIsNone(b.district_of("火星市"))

    def test_convert_reads_loose_headers_and_leaves_review_fields_empty(self):
        text = "﻿選舉名稱,選舉區,號次,姓名\n臺北市議員選舉,第01選舉區,01,王大明\n臺北市議員選舉,第01選舉區,,李小華\n"
        rows, bad = b.convert(text, "https://x", "2026-11-17")
        self.assertEqual([(r["district_id"], r["name"], r["value"]) for r in rows], [("tpe-council-01", "王大明", "1")])
        self.assertEqual((rows[0]["confirmed_by"], rows[0]["event"]), ("", "ballot"))
        self.assertEqual(len(bad), 1)
        with self.assertRaises(ValueError):
            b.convert("縣市,名字\n", "https://x", "2026-11-17")


if __name__ == "__main__":
    unittest.main()
