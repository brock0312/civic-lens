import json
import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert, upsert_fact
from etl.export import export
from etl.sources import candidates_2026_status as cs

T = "2026-10-03T00:00:00Z"
HEAD = ",".join(cs.FIELDS) + "\n"


def row(event, did, name, value="", url="https://web.cec.gov.tw/x", on="2026-10-15"):
    return {"event": event, "district_id": did, "name": name, "value": value, "source_url": url,
            "announced_on": on, "confirmed_by": "Claude 初審；verifier 複核", "confirmed_at": "2026-10-16", "note": ""}


def cand(pid, name, did, **data):
    return {"person_id": pid, "name": name, "district_id": did,
            "data": {"district_id": did, "status": "registered", **data}}


CANDS = [cand("p1", "王大明", "tpe-council-01"), cand("p2", "李小華", "tpe-council-01"), cand("p3", "陳一", "nwt-mayor")]


def load_text(text):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.csv"
        p.write_text(HEAD + text, encoding="utf-8")
        return cs.load(p)


class StatusApplyTest(unittest.TestCase):
    def test_approval_marks_everyone_in_scope_except_the_excluded(self):
        out = cs.apply(CANDS, [row("approved_all", "*", ""), row("excluded", "tpe-council-01", "李小華", "disqualified")])
        self.assertEqual({p: d["status"] for p, d in out.items()}, {"p1": "approved", "p2": "disqualified", "p3": "approved"})
        self.assertEqual(out["p1"]["status_source_url"], "https://web.cec.gov.tw/x")

    def test_approval_can_be_scoped_to_one_county(self):
        out = cs.apply(CANDS, [row("approved_all", "nwt", "")])
        self.assertEqual(list(out), ["p3"])

    def test_ballot_numbers_attach_with_their_source(self):
        out = cs.apply(CANDS, [row("ballot", "tpe-council-01", "王大明", "2", on="2026-11-17")])
        self.assertEqual((out["p1"]["ballot_no"], out["p1"]["ballot_announced_on"]), (2, "2026-11-17"))

    def test_anything_that_does_not_match_exactly_one_candidate_raises(self):
        for rows in ([row("ballot", "tpe-council-01", "張三", "1")],
                     [row("excluded", "tpe-council-02", "王大明", "withdrawn")],
                     [row("ballot", "tpe-council-01", "王大明", "1"), row("ballot", "tpe-council-01", "李小華", "1")],
                     [row("excluded", "tpe-council-01", "王大明", "withdrawn"), row("ballot", "tpe-council-01", "王大明", "1")]):
            with self.assertRaises(ValueError):
                cs.apply(CANDS, rows)

    def test_no_rows_change_nothing(self):
        self.assertEqual(cs.apply(CANDS, []), {})


class StatusLoadTest(unittest.TestCase):
    def test_rows_need_sources_known_events_and_valid_values(self):
        ok = "ballot,tpe-council-01,王大明,3,https://x,2026-11-17,Claude,2026-11-17,\n"
        self.assertEqual(load_text(ok)[0]["value"], "3")
        for bad in ("ballot,tpe-council-01,王大明,三,https://x,2026-11-17,Claude,2026-11-17,\n",
                    "excluded,tpe-council-01,王大明,dead,https://x,2026-10-15,Claude,2026-10-16,\n",
                    "approve,*,,,https://x,2026-10-15,Claude,2026-10-16,\n",
                    "approved_all,*,,,,2026-10-15,Claude,2026-10-16,\n"):
            with self.assertRaises(ValueError):
                load_text(bad)
        self.assertEqual(cs.load(Path("/nonexistent.csv")), [])

    def test_repo_file_is_valid(self):
        cs.load()


class ExportExcludedTest(unittest.TestCase):
    def test_excluded_candidates_are_not_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            upsert(conn, "district", {"district_id": "tpe-council-01", "office": "tpe_councilor", "name": "x", "seats": 1,
                                      "source_url": "http://d", "fetched_at": T}, ("district_id",))
            for pid, status in (("p1", "approved"), ("p2", "disqualified")):
                upsert(conn, "person", {"person_id": pid, "name": pid}, ("person_id",))
                upsert_fact(conn, f"c:{pid}", pid, "candidacy", {"district_id": "tpe-council-01", "status": status}, "http://c", T)
            export(conn, Path(tmp) / "out")
            self.assertEqual(sorted(p.name for p in (Path(tmp) / "out" / "people").iterdir()), ["p1.json"])
            d = json.loads((Path(tmp) / "out" / "districts" / "tpe-council-01.json").read_text(encoding="utf-8"))
            self.assertEqual([p["person_id"] for p in d["people"]], ["p1"])


if __name__ == "__main__":
    unittest.main()
