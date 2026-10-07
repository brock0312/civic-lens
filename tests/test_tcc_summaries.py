import json
import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_person
from etl.sources import tcc_summaries

VIEWER = "https://gaz.tcc.gov.tw/pdf/viewer.html?id=AAA"
SOURCE = {"heading": "市政總質詢第15組", "doc_type": "市政總質詢", "dept": None, "group": 15, "dates": ["2025-05-06"],
          "transcript_url": VIEWER, "transcript_page_url": VIEWER + "#page=3", "transcript_pages": [10, 11],
          "videos": [{"date": "2025-05-06", "group": 15}]}
DOC = {
    "session": "14-05", "label": "第14屆第5次定期大會", "last_date": "2025-06-10", "generator": "NotebookLM",
    "generated_at": "2026-10-01T03:00:00Z", "disclaimer": "聲明",
    "review": {"status": "approved", "by": "審閱者", "at": "2026-10-02T00:00:00Z", "note": None},
    "summaries": [
        {"person_id": "p1", "name": "甲", "status": "ok", "generator": "NotebookLM",
         "generated_at": "2026-10-01T02:00:00Z", "disclaimer": "聲明", "sources": [SOURCE],
         "issues": [{"topic": "議題", "councilor_points": ["詢問"], "response": None,
                     "citations": [{"source_url": VIEWER + "#page=3", "page": 10, "cited_text": "原文"}]}]},
        {"person_id": "p2", "name": "乙", "status": "no_speech", "generator": None, "generated_at": None,
         "disclaimer": "聲明", "sources": [SOURCE], "issues": []},
        {"person_id": "p9", "name": "沒對照", "status": "ok", "generator": "NotebookLM",
         "generated_at": "2026-10-01T02:00:00Z", "disclaimer": "聲明", "sources": [SOURCE], "issues": []},
    ],
}


class TestTccSummaries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        (tmp / "summaries").mkdir()
        (tmp / "summaries" / "14-05.json").write_text(json.dumps(DOC, ensure_ascii=False), encoding="utf-8")
        for tag, review in (("14-03", {"status": "pending", "by": None, "at": None, "note": None}),
                            ("14-04", {"status": "rejected", "by": "審閱者", "at": "2026-10-02T00:00:00Z", "note": "錯頁"}),
                            ("14-02", None)):
            doc = {**DOC, "session": tag, "review": review} if review else {k: v for k, v in DOC.items() if k != "review"}
            (tmp / "summaries" / f"{tag}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        self.conn = open_db(tmp / "civic.db", tmp / "civic.sql")
        for pid in ("p1", "p2", "p9"):
            upsert_person(self.conn, pid, pid)
        tcc_summaries.run(self.conn, tmp / "summaries", identity={"甲": ("p1", "x"), "乙": ("p2", "x")})
        self.rows = {r["fact_key"]: r for r in self.conn.execute("SELECT * FROM fact")}

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_writes_one_summary_fact_per_mapped_councilor(self):
        self.assertEqual(sorted(self.rows), ["summary:14-05:p1", "summary:14-05:p2"])
        r = self.rows["summary:14-05:p1"]
        self.assertEqual((r["kind"], r["date"], r["source_url"]), ("summary", "2025-06-10", VIEWER))
        self.assertEqual(r["fetched_at"], "2026-10-01T02:00:00Z")
        data = json.loads(r["data"])
        self.assertEqual(sorted(data), ["disclaimer", "generated_at", "generator", "issues", "session", "sources", "status"])
        self.assertEqual(data["session"], "第14屆第5次定期大會")
        self.assertEqual(data["issues"][0]["citations"], [{"source_url": VIEWER + "#page=3", "page": 10}])

    def test_citation_excerpts_from_old_session_files_never_reach_the_db(self):
        self.assertFalse([k for k, r in self.rows.items() if "cited_text" in r["data"]])

    def test_pending_rejected_and_unreviewed_sessions_write_no_summary_facts(self):
        for tag in ("14-02", "14-03", "14-04"):
            self.assertFalse([k for k in self.rows if k.startswith(f"summary:{tag}:")], tag)

    def test_no_speech_keeps_status_and_falls_back_to_file_timestamp(self):
        r = self.rows["summary:14-05:p2"]
        self.assertEqual(json.loads(r["data"])["status"], "no_speech")
        self.assertEqual(r["fetched_at"], "2026-10-01T03:00:00Z")


if __name__ == "__main__":
    unittest.main()
