import unittest

from etl import cec2022


def row(area, no, win, ori="03", name="甲", by="1980"):
    return {"area_name": area, "ori_area_code": ori, "cand_name": name, "cand_no": no,
            "cand_birthyear": by, "party_name": "無", "is_victor": win}


class ParseCandidatesTest(unittest.TestCase):
    def test_bang_and_star_count_as_elected_and_blank_does_not(self):
        got = cec2022.parse_candidates({"k": [row("宜蘭縣", 1, "!"), row("宜蘭縣", 2, "*"), row("宜蘭縣", 3, " ")]}, "regional")
        self.assertEqual([c["elected"] for c in got], [True, True, False])

    def test_councilor_district_comes_from_ori_area_code(self):
        (c,) = cec2022.parse_candidates({"k": [row("宜蘭縣", 1, "*", ori="03")]}, "plains")
        self.assertEqual((c["district_n"], c["kind"], c["office"], c["birth_year"]), (3, "plains", "ila_councilor", 1980))

    def test_kinmen_and_chiayi_city_stay_apart(self):
        got = cec2022.parse_candidates({"k": [row("金門縣", 1, "*"), row("嘉義市", 1, "*")]}, "mayor")
        self.assertEqual(len({c["iso"] for c in got}), 2)

    def test_mayor_has_no_district_or_kind(self):
        (c,) = cec2022.parse_candidates({"k": [row("臺北市", 1, "*", ori="00", by=" ")]}, "mayor")
        self.assertEqual((c["district_n"], c["kind"], c["office"], c["birth_year"]), (None, None, "tpe_mayor", None))


if __name__ == "__main__":
    unittest.main()
