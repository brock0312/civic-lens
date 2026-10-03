import unittest

from etl.match import match


def rec(key, iso, name, n, office="councilor"):
    return {"key": key, "iso": iso, "name": name, "office": office, "district_n": n}


def cand(pid, name, did):
    return {"person_id": pid, "name": name, "district_id": did}


class MatchTest(unittest.TestCase):
    def one(self, r, cs):
        return match([r], cs)

    def test_links_unique_name_same_district(self):
        o = self.one(rec(1, "kee", "王大明", 3), [cand("p1", "王 大明", "kee-council-03")])
        self.assertEqual(o["links"], [{"key": 1, "person_id": "p1"}])

    def test_links_indigenous_name_with_different_separators(self):
        o = self.one(rec(1, "nwt", "馬見Lahuy．Ipin", 13), [cand("p1", "馬見Lahuy‧Ipin", "nwt-council-13")])
        self.assertEqual(o["links"], [{"key": 1, "person_id": "p1"}])

    def test_links_indigenous_name_with_different_word_order(self):
        o = self.one(rec(1, "tnn", "Ingay Tali穎艾達利", 12), [cand("p1", "穎艾達利 Ingay Tali", "tnn-council-12")])
        self.assertEqual(o["links"], [{"key": 1, "person_id": "p1"}])
        o = self.one(rec(1, "khh", "范織欽(Pasulang‧Tomatalate)", 15), [cand("p1", "范織欽 Pasulang．Tomatalate", "khh-council-15")])
        self.assertEqual(len(o["links"]), 1)

    def test_links_indigenous_name_with_different_apostrophes(self):
        for a in ("'", "‘", "＇"):
            o = self.one(rec(1, "mia", "黃月娥 Yuma’Baysu’", 8), [cand("p1", f"黃月娥 Yuma{a}Baysu{a}", "mia-council-08")])
            self.assertEqual(o["links"], [{"key": 1, "person_id": "p1"}], a)

    def test_romanization_on_one_side_only_goes_to_review(self):
        o = self.one(rec(1, "tnn", "施余興望", 13), [cand("p1", "施余興望 Tjakumay Tagaw", "tnn-council-13")])
        self.assertEqual(o["review"], [{"key": 1, "person_ids": ["p1"], "reason": "romanization"}])
        self.assertEqual(o["links"], [])

    def test_different_romanization_words_go_to_review(self):
        o = self.one(rec(1, "khh", "高忠德(Taki ludun‧Anu)", 14), [cand("p1", "高忠德 Takiludun．Anu", "khh-council-14")])
        self.assertEqual(o["review"][0]["reason"], "romanization")
        self.assertEqual(o["links"], [])

    def test_duplicate_name_goes_to_review(self):
        o = self.one(rec(1, "kee", "王大明", 3), [cand("p1", "王大明", "kee-council-03"), cand("p2", "王大明", "kee-council-04")])
        self.assertEqual(o["review"][0]["reason"], "duplicate_name")
        self.assertEqual(o["links"], [])

    def test_variant_goes_to_review_not_link(self):
        o = self.one(rec(1, "kee", "黄小明", 3), [cand("p1", "黃小明", "kee-council-03")])
        self.assertEqual(o["review"][0]["reason"], "variant")
        self.assertEqual(o["links"], [])

    def test_hsq_district_shift(self):
        c = [cand("p1", "李四", "hsq-council-02")]
        self.assertEqual(len(self.one(rec(1, "hsq", "李四", 1), c)["links"]), 1)
        c = [cand("p1", "李四", "hsq-council-03")]
        self.assertEqual(self.one(rec(1, "hsq", "李四", 3), c)["review"][0]["reason"], "no_overlap")

    def test_councilor_running_for_mayor_links(self):
        o = self.one(rec(1, "kee", "王大明", 3), [cand("p1", "王大明", "kee-mayor")])
        self.assertEqual(len(o["links"]), 1)

    def test_same_name_other_county_unregistered(self):
        o = self.one(rec(1, "kee", "王大明", 3), [cand("p1", "王大明", "hsz-council-03")])
        self.assertEqual(o["unregistered"], [1])

    def test_han_name_shared_with_romanized_candidate_goes_to_review(self):
        o = match([rec(0, "tao", "王大明", 3)],
                  [cand("p1", "王大明", "tao-council-03"), cand("p2", "王大明 Abc", "tao-council-03")])
        self.assertEqual((o["links"], [x["reason"] for x in o["review"]]), ([], ["duplicate_name"]))


if __name__ == "__main__":
    unittest.main()
