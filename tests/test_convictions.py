import csv
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from etl.db import open_db, upsert, upsert_fact
from etl.sources import convictions as cv

T = "2026-10-03T00:00:00Z"
FID = "TPHM,114,上訴,123,20260618,1"
PAGE = ("<html>" + "x" * 3000 + "臺灣高等法院 114 年度上訴字第 123 號刑事判決"
        "<script>$.get('/controls/GetJudHistory.ashx?jid=TPHM%2C114%2C%E4%B8%8A%E8%A8%B4%2C123')</script></html>")


def row(**kw):
    r = {"fjud_id": FID, "person_id": "p1", "court": "臺灣高等法院", "case_no": "114 年度上訴字第 123 號",
         "judgment_date": "2026-06-18", "offense": "某罪", "result": "有期徒刑六月", "finality_basis": "A",
         "identity_path": "1", "identity_basis": "判決載明第 N 屆議員，對 identity.csv 唯一", "reviewed_by": "Claude 初審；verifier 複核",
         "reviewed_at": "2026-11-26", "note": ""}
    r.update(kw)
    return r


def load_rows(*rows):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.csv"
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cv.FIELDS)
            w.writeheader()
            w.writerows(rows)
        return cv.load(p)


def fetcher(page=PAGE, history=None):
    history = history if history is not None else {"count": 2, "list": [{"desc": "一審", "href": "data.aspx?x", "red": 0},
                                                                         {"desc": "二審", "href": "data.aspx?y", "red": 0}]}

    def fetch(url):
        if "GetJudHistory" in url:
            return json.dumps(history).encode()
        return page.encode()
    return fetch


class LoadTest(unittest.TestCase):
    def test_valid_rows_load_and_the_repo_table_is_valid(self):
        self.assertEqual(load_rows(row())[0]["fjud_id"], FID)
        cv.load()

    def test_rows_outside_the_standard_are_rejected(self):
        for bad in (row(finality_basis="G"), row(finality_basis="F"), row(identity_path="3"), row(judgment_date="2026-06-17"),
                    row(fjud_id="TPHM,114,上訴,123"), row(reviewed_by=""), row(result="")):
            with self.assertRaises(ValueError):
                load_rows(bad)
        with self.assertRaises(ValueError):
            load_rows(row(), row())


class VerifyTest(unittest.TestCase):
    def test_passes_when_page_and_history_are_clean(self):
        self.assertIsNone(cv.verify(row(), fetcher(), sleep=0))
        self.assertEqual(cv.jid_of(PAGE), "TPHM,114,上訴,123")

    def test_pending_appeal_or_a_blocked_or_changed_page_fails_closed(self):
        pending = {"list": [{"desc": "最高法院 115 年度台上字第 1 號", "href": "", "red": 0}]}
        red = {"list": [{"desc": "上訴最高法院", "href": "data.aspx?z", "red": 1}]}
        self.assertIn("尚未結案", cv.verify(row(), fetcher(history=pending), sleep=0))
        self.assertIn("尚未結案", cv.verify(row(), fetcher(history=red), sleep=0))
        self.assertIn("被擋", cv.verify(row(), fetcher(page="Request Rejected"), sleep=0))
        self.assertIn("判決字號", cv.verify(row(case_no="114 年度上訴字第 999 號"), fetcher(), sleep=0))
        self.assertIn("jid", cv.verify(row(), fetcher(page=PAGE.replace("GetJudHistory.ashx?jid=", "x")), sleep=0))

        def boom(url):
            raise OSError("404")
        self.assertIn("抓取失敗", cv.verify(row(), boom, sleep=0))


class RunTest(unittest.TestCase):
    def db(self, tmp):
        conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
        upsert(conn, "district", {"district_id": "tpe-council-01", "office": "tpe_councilor", "name": "x", "seats": 1,
                                  "source_url": "http://d", "fetched_at": T}, ("district_id",))
        for pid in ("p1", "p2"):
            upsert(conn, "person", {"person_id": pid, "name": pid}, ("person_id",))
        upsert_fact(conn, "c:p1", "p1", "candidacy", {"district_id": "tpe-council-01"}, "http://c", T)
        return conn

    def test_verified_rows_become_final_facts_and_failures_remove_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self.db(tmp)
            with unittest.mock.patch("builtins.print"):
                cv.run(conn, [row(), row(person_id="p2")], fetcher(), sleep=0)
            got = conn.execute("SELECT person_id, date, data, source_url FROM fact WHERE kind = 'conviction'").fetchall()
            self.assertEqual([(g["person_id"], g["date"]) for g in got], [("p1", "2026-06-18")])
            self.assertTrue(json.loads(got[0]["data"])["final"])
            self.assertTrue(got[0]["source_url"].startswith("https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPHM%2C114"))
            with unittest.mock.patch("builtins.print"):
                cv.run(conn, [row()], fetcher(history={"list": [{"desc": "x", "href": "", "red": 0}]}), sleep=0)
            self.assertEqual(conn.execute("SELECT count(*) FROM fact WHERE kind = 'conviction'").fetchone()[0], 0)

if __name__ == "__main__":
    unittest.main()
