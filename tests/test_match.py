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


if __name__ == "__main__":
    unittest.main()
