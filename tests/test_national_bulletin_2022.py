import tempfile
import unittest
from pathlib import Path

from etl import bulletin_grid as bg
from etl.db import open_db, upsert, upsert_fact
from etl.sources import national_bulletin_2022 as nb

P = "01選舉公報/"
MAYOR_FILE = P + "03直轄市長/111年/新北市市長.pdf"
COUNCIL_12 = P + "05直轄市議員/111年/02新北市/12-新北市選舉公報-第十二、十三選區.pdf"
TAO_7 = P + "05直轄市議員/111年/03桃園市/桃園市第7選舉區.pdf"
FILES = [
    {"path": MAYOR_FILE, "iso": "nwt", "districts": [["councilor", 12], ["councilor", 13], ["mayor", None]]},
    {"path": COUNCIL_12, "iso": "nwt", "districts": [["councilor", 12], ["councilor", 13], ["mayor", None]]},
]


def row(office="councilor", n=12, no=1, page=1, platform="一、政見", education="•學歷", experience="•經歷", dropped=None):
    return {"office": office, "district_n": n, "cand_no": no, "page": page, "platform": platform,
            "education": education, "experience": experience, "dropped": dropped or {}}


def cand(name, no=1, elected=True):
    return {"name": name, "cand_no": no, "elected": elected}


class ToCandTest(unittest.TestCase):
    def test_bulleted_lines_become_items_with_wrapped_lines_joined(self):
        c = nb.to_cand(row(education="•國立大學\n畢業\n•高中", experience="議員"))
        self.assertEqual(c["education"], ["•國立大學畢業", "•高中"])
        self.assertEqual(c["experience"], ["議員"])
        self.assertEqual(c["platform"], "一、政見")

    def test_profile_dropped_when_either_column_failed_a_gate(self):
        c = nb.to_cand(row(experience=None, dropped={"experience": "圖片"}))
        self.assertIsNone(c["education"])
        self.assertIsNone(c["experience"])

    def test_blank_column_is_empty_list_but_both_blank_is_not_collected(self):
        c = nb.to_cand(row(experience=None, dropped={"experience": "空白"}))
        self.assertEqual(c["experience"], [])
        both = nb.to_cand(row(education=None, experience=None, dropped={"education": "空白", "experience": "空白"}))
        self.assertIsNone(both["education"])

    def test_dropped_platform_stays_none(self):
        self.assertIsNone(nb.to_cand(row(platform=None, dropped={"platform": "圖片"}))["platform"])


class DedupeTest(unittest.TestCase):
    def test_same_pdf_in_mayor_and_council_dirs_keeps_one_row_per_person_from_matching_dir(self):
        mayor, council = row("mayor", None, 2, page=1), row("councilor", 12, 1, page=2)
        picked = nb.pick_rows([(COUNCIL_12, [council, mayor]), (MAYOR_FILE, [mayor, council])])
        self.assertEqual(set(picked), {("mayor", None, 2), ("councilor", 12, 1)})
        self.assertEqual(picked[("mayor", None, 2)][0], MAYOR_FILE)
        self.assertEqual(picked[("councilor", 12, 1)][0], COUNCIL_12)

    def test_file_for_prefers_matching_dir(self):
        self.assertEqual(nb.file_for(FILES, "mayor", None), MAYOR_FILE)
        self.assertEqual(nb.file_for(FILES, "councilor", 13), COUNCIL_12)
        self.assertIsNone(nb.file_for(FILES, "councilor", 1))


class PlanTest(unittest.TestCase):
    cec = {("nwt", "councilor", 12): {1: cand("王小明", 1), 2: cand("黄大華", 2), 3: cand("高為人Sayun．Watan", 3)}}

    def person(self, name, n=12):
        return {"iso": "nwt", "office": "councilor", "district_n": n, "name": name}

    def test_exact_name_with_passed_row_writes_text(self):
        picked = nb.pick_rows([(COUNCIL_12, [row(no=1, page=2)])])
        p = nb.plan_person(self.person("王小明"), self.cec, FILES, picked)
        self.assertEqual((p["status"], p["path"], p["page"]), ("full", COUNCIL_12, 2))

    def test_aboriginal_name_matches_on_han_part(self):
        picked = nb.pick_rows([(COUNCIL_12, [row(no=3)])])
        self.assertEqual(nb.plan_person(self.person("高為人Watan Sayun"), self.cec, FILES, picked)["status"], "full")

    def test_variant_character_name_gets_link_only(self):
        picked = nb.pick_rows([(COUNCIL_12, [row(no=2, page=3)])])
        p = nb.plan_person(self.person("黃大華"), self.cec, FILES, picked)
        self.assertEqual((p["status"], p["page"]), ("link", 3))
        self.assertNotIn("cand", p)

    def test_row_rejected_by_identity_gate_gets_file_link_without_page(self):
        p = nb.plan_person(self.person("王小明"), self.cec, FILES, {})
        self.assertEqual((p["status"], p["path"], p["page"]), ("link", COUNCIL_12, None))

    def test_plan_carries_the_2022_election_result_of_the_matched_candidate(self):
        cec = {("nwt", "councilor", 12): {1: cand("王小明", 1), 2: cand("石一佑", 2, elected=False)}}
        picked = nb.pick_rows([(COUNCIL_12, [row(no=1), row(no=2)])])
        self.assertTrue(nb.plan_person(self.person("王小明"), cec, FILES, picked)["elected"])
        self.assertFalse(nb.plan_person(self.person("石一佑"), cec, FILES, picked)["elected"])
        self.assertFalse(nb.plan_person(self.person("石一佑"), cec, FILES, {})["elected"])  # 只有原檔連結也要帶

    def test_not_a_2022_candidate_is_missing(self):
        self.assertEqual(nb.plan_person(self.person("陳某某"), self.cec, FILES, {})["status"], "missing")

    def test_no_text_layer_file_gives_link_only(self):
        files = [{"path": TAO_7, "iso": "tao", "districts": [["councilor", 7]]}]
        cec = {("tao", "councilor", 7): {1: cand("李四", 1)}}
        p = nb.plan_person({"iso": "tao", "office": "councilor", "district_n": 7, "name": "李四"}, cec, files, {})
        self.assertEqual((p["status"], p["path"]), ("link", TAO_7))
        self.assertIn("無文字層", p["reason"])
        self.assertIn(TAO_7, bg.NO_TEXT_FILES)

    def test_whole_county_without_text_layer_gives_link_only_with_result_and_no_page(self):
        path = P + "06縣市議員/111年/16臺東縣/臺東縣第1、7、14選舉區.pdf"
        files = [{"path": path, "iso": "ttt", "districts": [["councilor", 1], ["councilor", 7], ["councilor", 14]]}]
        cec = {("ttt", "councilor", 7): {2: cand("王五", 2, elected=False)}}
        p = nb.plan_person({"iso": "ttt", "office": "councilor", "district_n": 7, "name": "王五"}, cec, files, {})
        self.assertEqual((p["status"], p["path"], p["page"], p["elected"]), ("link", path, None, False))
        self.assertIn("無文字層", p["reason"])
        self.assertNotIn("cand", p)

    def test_link_only_counties_are_in_scope_and_never_cut(self):
        for iso in ("yun", "pif", "ila", "ttt", "pen"):
            self.assertIn(iso, nb.ISOS)
            self.assertIn(nb.NAMES[iso], bg.NO_TEXT_LAYER)
        self.assertIn("cyi", nb.ISOS)
        self.assertNotIn("嘉義市", bg.NO_TEXT_LAYER)


class VolumeTest(unittest.TestCase):
    V1 = P + "06縣市議員/111年/13屏東縣/屏東縣第01選舉區1.pdf"
    V2 = P + "06縣市議員/111年/13屏東縣/屏東縣第01選舉區2.pdf"
    files = [{"path": V1, "iso": "pif", "districts": [["councilor", 1]]},
             {"path": V2, "iso": "pif", "districts": [["councilor", 1]]}]

    def test_split_district_links_the_volume_holding_the_ballot_number(self):
        self.assertEqual(nb.file_for(self.files, "councilor", 1, 20), self.V1)
        self.assertEqual(nb.file_for(self.files, "councilor", 1, 21), self.V2)

    def test_plan_for_split_district_uses_matched_candidate_number(self):
        cec = {("pif", "councilor", 1): {23: cand("趙六", 23)}}
        p = nb.plan_person({"iso": "pif", "office": "councilor", "district_n": 1, "name": "趙六"}, cec, self.files, {})
        self.assertEqual((p["status"], p["path"]), ("link", self.V2))


class SamePartyTest(unittest.TestCase):
    def test_tai_variants_are_equal_for_party_only(self):
        self.assertEqual(bg.same_party("台灣民眾黨"), bg.same_party("臺灣民眾黨"))


class LoadTargetsTest(unittest.TestCase):
    def test_only_incumbents_with_a_2026_candidacy_are_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            for pid in ("pRun", "pNot"):
                upsert(conn, "person", {"person_id": pid, "name": pid}, ("person_id",))
                upsert_fact(conn, f"office:mia-council-2022:{pid}", pid, "office",
                            {"office": "mia_councilor", "district_id": "mia-council-08"}, "https://x", "t")
            upsert_fact(conn, "candidacy:2026-local:pRun", "pRun", "candidacy", {"district_id": "mia-council-08"}, "https://x", "t")
            self.assertEqual([t["person_id"] for t in nb.load_targets(conn, "mia")], ["pRun"])
            conn.close()

    def test_hsinchu_county_target_uses_the_2022_district_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            upsert(conn, "person", {"person_id": "p", "name": "p"}, ("person_id",))
            upsert_fact(conn, "office:hsq-council-2022:p", "p", "office",
                        {"office": "hsq_councilor", "district_id": "hsq-council-2022-03",
                         "districts_2026": ["hsq-council-04"]}, "https://x", "t")
            upsert_fact(conn, "candidacy:2026-local:p", "p", "candidacy", {"district_id": "hsq-council-04"}, "https://x", "t")
            self.assertEqual(nb.load_targets(conn, "hsq")[0]["district_n"], 3)
            conn.close()

if __name__ == "__main__":
    unittest.main()
