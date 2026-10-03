import json
import unittest
from pathlib import Path

from etl import bulletin2022
from etl.bulletin2022 import file_map, parse_districts

FIX = Path(__file__).parent / "fixtures"
INDEX = json.loads((FIX / "bulletin2022_index.json").read_text())
DISTRICTS = json.loads((FIX / "districts2022.json").read_text())


class ParseDistrictsTest(unittest.TestCase):
    def test_chinese_numerals_and_ji_separator(self):
        self.assertEqual(parse_districts("第十二及第十三選舉區.pdf"), [12, 13])
        self.assertEqual(parse_districts("基隆市選舉公報_第十九選區.pdf"), [19])

    def test_range_mixed_with_list(self):
        self.assertEqual(parse_districts("屏東縣第8、13-16選舉區.pdf"), [8, 13, 14, 15, 16])

    def test_dot_separator(self):
        self.assertEqual(parse_districts("高雄市第12.13.14.15選區.pdf"), [12, 13, 14, 15])
        self.assertEqual(parse_districts("南投縣第3.4選舉區.pdf"), [3, 4])

    def test_leading_file_number_is_not_a_district(self):
        self.assertEqual(parse_districts("12-新北市選舉公報-第十二、十三選區.pdf"), [12, 13])
        self.assertEqual(parse_districts("02議員第三選區公報.pdf"), [3])

    def test_space_before_pdf_extension(self):
        (f,) = file_map([{"path": "01選舉公報/05直轄市議員/111年/04臺中市/臺中市第02選區 .pdf", "size": 1}])
        self.assertEqual((f["iso"], f["districts"]), ("txg", [["councilor", 2]]))


class FileMapGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = file_map(INDEX)

    def covered(self, kind):
        return {(f["iso"], n) for f in self.files for k, n in f["districts"] if k == kind}

    def test_every_2022_council_district_is_covered(self):
        want = {(iso, n) for iso, ns in DISTRICTS.items() for n in ns}
        self.assertEqual(sorted(want - self.covered("councilor")), [])

    def test_no_file_maps_to_a_nonexistent_district(self):
        want = {(iso, n) for iso, ns in DISTRICTS.items() for n in ns}
        self.assertEqual(sorted(self.covered("councilor") - want), [])

    def test_all_22_mayors_are_covered(self):
        self.assertEqual({iso for iso, _ in self.covered("mayor")}, set(DISTRICTS))
        self.assertEqual(len(DISTRICTS), 22)

    def test_recall_notice_is_excluded(self):
        self.assertTrue(any("罷免" in f["path"] for f in INDEX))
        self.assertFalse(any("罷免" in f["path"] for f in self.files))
        self.assertEqual(len(self.files), len(INDEX) - 1)

    def test_every_override_matches_a_listed_file(self):
        self.assertEqual(set(bulletin2022.OVERRIDES) - {f["path"] for f in INDEX}, set())

    def test_hsinchu_city_district_6_file_also_carries_the_mayor(self):
        # 新竹市第 6 區議員檔與市長檔是同一份 PDF
        (f,) = [f for f in self.files if f["path"].endswith("新竹市第06選舉區.pdf")]
        self.assertEqual(f["districts"], [["councilor", 6], ["mayor", None]])

    def test_chiayi_city_mayor_is_the_rerun_bulletin(self):
        (f,) = [f for f in self.files if f["iso"] == "cyi" and ["mayor", None] in f["districts"]]
        self.assertTrue(f["path"].endswith("嘉義市市長重行選舉.pdf"))


if __name__ == "__main__":
    unittest.main()
