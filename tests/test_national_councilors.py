import tempfile
import unittest
from pathlib import Path

from etl.sources.national_heads import MOI_INAUGURATION
from unittest import mock

from etl.sources import national_councilors as nc
from etl.sources.national_councilors import IDENTITY_PATH, load_identity, plan, roster_url


def ros(iso, n, name, current=True):
    return {"iso": iso, "district_n": n, "name": name, "current": current, "note": ""}


def won(iso, n, name, party):
    return {"iso": iso, "district_n": n, "name": name, "party": party, "elected": True}


def cand(pid, name, did):
    return {"person_id": pid, "name": name, "district_id": did}


def identity_from(text):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "i.csv"
        p.write_text("iso,roster_name,district_n,person_id,confirmed_by,confirmed_at,note\n" + text, encoding="utf-8")
        return load_identity(p)


class NationalCouncilorsTest(unittest.TestCase):
    def test_links_unique_candidate_and_writes_2022_term_with_cec_party(self):
        rows, review = plan([ros("nwt", 3, "王大明")], [won("nwt", 3, "王大明", "民主進步黨")],
                            [cand("p1", "王大明", "nwt-council-03")], {})
        self.assertEqual(review, [])
        x = rows[0]
        self.assertEqual((x["person_id"], x["date"]), ("p1", "2022-12-25"))
        self.assertEqual(x["data"], {"office": "nwt_councilor", "district_id": "nwt-council-03",
                                     "title": "新北市議員", "party": "民主進步黨", "party_year": 2022,
                                     "inauguration_source_url": MOI_INAUGURATION[0],
                                     "inauguration_source_label": MOI_INAUGURATION[1]})

    def test_hsinchu_county_office_names_the_2022_district_and_lists_its_2026_districts(self):
        rows, review = plan([ros("hsq", 1, "王大明"), ros("hsq", 3, "李四")], [],
                            [cand("p1", "王大明", "hsq-council-02"), cand("p2", "李四", "hsq-council-04")], {})
        self.assertEqual(review, [])
        self.assertEqual([x["person_id"] for x in rows], ["p1", "p2"])
        a, b = rows[0]["data"], rows[1]["data"]
        self.assertEqual((a["district_id"], a["district_name"], a["districts_2026"]),
                         ("hsq-council-2022-01", "新竹縣第1選舉區（2022 年劃分）", ["hsq-council-01", "hsq-council-02"]))
        self.assertEqual((b["district_id"], b["districts_2026"]), ("hsq-council-2022-03", ["hsq-council-04"]))

    def test_counties_without_redistricting_keep_the_roster_district(self):
        x = plan([ros("hsz", 3, "王大明")], [], [], {})[0][0]["data"]
        self.assertEqual(x["district_id"], "hsz-council-03")
        self.assertNotIn("district_name", x)
        self.assertNotIn("districts_2026", x)

    def test_party_from_2022_cites_cec_file(self):
        w = {**won("nwt", 3, "王大明", "民主進步黨"), "source_url": "https://cec/x.json"}
        x = plan([ros("nwt", 3, "王大明")], [w], [], {})[0][0]["data"]
        self.assertEqual((x["party_source_url"], x["party_source_label"]), ("https://cec/x.json", "中選會 2022 開票結果"))

    def test_former_members_are_skipped(self):
        rows, _ = plan([ros("khh", 4, "李四", current=False)], [], [], {})
        self.assertEqual(rows, [])

    def test_member_not_elected_in_2022_has_no_start_date_or_party(self):
        rows, _ = plan([ros("nwt", 5, "石一佑")], [won("nwt", 5, "別人", "無")], [], {})
        self.assertIsNone(rows[0]["date"])
        self.assertIsNone(rows[0]["person_id"], "沒串到候選人就新建")
        self.assertNotIn("party", rows[0]["data"])

    def test_2022_seat_ignores_romanization_word_order_but_not_district(self):
        w = [won("khh", 14, "高忠德 Takiludun．Anu", "中國國民黨")]
        rows, _ = plan([ros("khh", 14, "高忠德(Taki ludun‧Anu)")], w, [], {})
        self.assertEqual(rows[0]["date"], "2022-12-25")
        rows, _ = plan([ros("khh", 15, "高忠德")], w, [], {})
        self.assertIsNone(rows[0]["date"])

    def test_review_is_reported_and_not_linked(self):
        rows, review = plan([ros("tnn", 13, "施余興望")], [], [cand("p1", "施余興望 Tjakumay Tagaw", "tnn-council-13")], {})
        self.assertIsNone(rows[0]["person_id"])
        self.assertEqual((review[0]["reason"], review[0]["row"]["name"]), ("romanization", "施余興望"))

    def test_confirmed_table_overrides_review(self):
        ident = identity_from("tnn,施余興望,13,p1,Brock,2026-10-03,公報生日一致\n")
        rows, _ = plan([ros("tnn", 13, "施余興望")], [], [cand("p1", "施余興望 Tjakumay Tagaw", "tnn-council-13")], ident)
        self.assertEqual(rows[0]["person_id"], "p1")
        self.assertIn("Brock", rows[0]["verified_by"])

    def test_confirmed_table_rejects_missing_confirmer(self):
        with self.assertRaises(ValueError):
            identity_from("tnn,施余興望,13,p1,,2026-10-03,\n")

    def test_repo_confirmed_table_loads(self):
        self.assertIsInstance(load_identity(IDENTITY_PATH), dict)

    def test_multi_page_rosters_cite_the_district_page(self):
        self.assertTrue(roster_url("tao", 3).endswith("area=3"))
        self.assertEqual(roster_url("nwt", 3), roster_url("nwt", 1))

    def test_every_roster_county_has_expected_incumbent_count(self):
        self.assertEqual(set(nc.ISOS), set(nc.EXPECTED))
        self.assertEqual({k: nc.EXPECTED[k] for k in ("kee", "cyq", "nan", "mia", "hua", "cha", "hsq", "hsz", "kin", "lie")},
                         {"kee": 28, "cyq": 37, "nan": 34, "mia": 36, "hua": 32,
                          "cha": 53, "hsq": 37, "hsz": 33, "kin": 19, "lie": 9})

    def test_fetch_rosters_raises_when_incumbent_count_differs(self):
        rows = lambda iso: [ros(iso, 1, f"{iso}{i}") for i in range(nc.EXPECTED[iso] - (iso == "nan"))]
        with mock.patch.object(nc, "fetch_roster", rows), mock.patch.object(nc.time, "sleep"):
            with self.assertRaisesRegex(ValueError, "nan 名錄現任 33 人"):
                nc.fetch_rosters()


if __name__ == "__main__":
    unittest.main()
