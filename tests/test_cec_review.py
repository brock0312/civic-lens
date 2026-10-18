import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from etl import cec_review
from etl.db import open_db, upsert, upsert_fact, upsert_person
from etl.sources import national_candidates


def write_csv(tmp, text):
    p = Path(tmp) / "review.csv"
    p.write_text(text, encoding="utf-8")
    return p


def cand(conn, pid, name, district_id, office, source="cec_reg_2026"):
    upsert_person(conn, pid, name)
    upsert(conn, "person_source_id", {"source": source, "source_key": f"{district_id}:{name}", "person_id": pid,
                                      "verified_by": "t"}, ("source", "source_key"))
    upsert_fact(conn, f"candidacy:2026-local:{pid}", pid, "candidacy",
                {"election": "2026-local", "office": office, "district_id": district_id, "status": "registered"},
                "https://u", "t")


class ReviewTable(unittest.TestCase):
    def test_only_disqualified_rows_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = write_csv(tmp, "area,name,result\n花蓮縣第5選舉區,甲,不合格\n")
            self.assertEqual(cec_review.disqualified(ok), {("花蓮縣第5選舉區", "甲")})
            with self.assertRaises(ValueError):
                cec_review.disqualified(write_csv(tmp, "area,name,result\n花蓮縣第5選舉區,甲,合格\n"))
            with self.assertRaises(ValueError):
                cec_review.disqualified(write_csv(tmp, "area,name,result\n花蓮縣第5選舉區,甲,不合格\n花蓮縣第5選舉區,甲,不合格\n"))

    def test_repo_table_has_no_reasons_column(self):
        header = cec_review.PATH.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(header, "area,name,result")

    def test_district_and_table_mapping(self):
        self.assertEqual(cec_review.district_of("臺北市第6選舉區"), "tpe-council-06")
        self.assertEqual(cec_review.district_of("金門縣第1選舉區"), "kin-council-01")
        self.assertEqual([cec_review.table_of(o) for o in ("tpe_mayor", "khh_councilor", "hua_mayor", "kee_councilor")],
                         ["1-1", "2-1", "3-1", "4-1"])


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = open_db(Path(self.tmp.name) / "civic.db", Path(self.tmp.name) / "civic.sql")
        cand(self.conn, "pa", "甲", "hua-council-05", "hua_councilor")
        cand(self.conn, "pb", "乙", "hua-council-05", "hua_councilor")
        cand(self.conn, "pc", "丙", "tpe-council-06", "tpe_councilor", source="tpe_reg_2026")
        self.csv = write_csv(self.tmp.name, "area,name,result\n花蓮縣第5選舉區,甲,不合格\n臺北市第6選舉區,丙,不合格\n")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def run_review(self, totals):
        with mock.patch.object(cec_review, "PATH", self.csv), mock.patch.object(cec_review, "TOTALS", totals):
            cec_review.run(self.conn)

    def test_drops_disqualified_and_marks_the_rest_reviewed(self):
        self.run_review({"4-1": (2, 1)})  # 臺北那位不合格後 2-1 沒有人
        rows = {r["person_id"]: json.loads(r["data"]) for r in self.conn.execute("SELECT * FROM fact WHERE kind = 'candidacy'")}
        self.assertEqual(set(rows), {"pb"})
        self.assertEqual((rows["pb"]["status"], rows["pb"]["review_url"]), ("qualified", cec_review.REVIEW_URL))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM person WHERE person_id = 'pa'").fetchone()[0], 1)

    def test_count_mismatch_raises(self):
        with self.assertRaises(ValueError):
            self.run_review({"2-1": (1, 0), "4-1": (2, 2)})

    def test_unknown_disqualified_name_raises(self):
        self.csv = write_csv(self.tmp.name, "area,name,result\n花蓮縣第5選舉區,丁,不合格\n")
        with self.assertRaises(ValueError):
            self.run_review({"4-1": (2, 2), "2-1": (1, 1)})


class NationalCheck(unittest.TestCase):
    def test_check_review_counts_and_matches(self):
        rows = [{"area": "花蓮縣第5選舉區", "name": n} for n in ("甲", "乙")]
        with mock.patch.object(cec_review, "TOTALS", {"4-1": (2, 1)}):
            national_candidates.check_review([("4-1", rows)], {("花蓮縣第5選舉區", "甲")})
            with self.assertRaises(ValueError):
                national_candidates.check_review([("4-1", rows)], {("花蓮縣第5選舉區", "丁")})
            with self.assertRaises(ValueError):
                national_candidates.check_review([("4-1", rows)], set())


if __name__ == "__main__":
    unittest.main()
