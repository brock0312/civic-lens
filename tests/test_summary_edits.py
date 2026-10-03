import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "summaries"))
from batch import EditMismatch, apply_edits, candidate_ids  # noqa: E402
from check_report import bigram_idf, filter_citations  # noqa: E402

SUMMARY = {"person_id": "p1", "name": "甲", "issues": [
    {"topic": "捷運漏水", "councilor_points": ["要求改善"], "response": "局長說明已改善，將持續關注。"},
    {"topic": "公園照明", "councilor_points": ["要求增設路燈"], "response": None},
]}


def edit(action, topic, **kw):
    return {"person_id": "p1", "name": "甲", "issue_topic": topic, "action": action, "reason": "r", "reviewer": "x",
            "date": "2026-10-02", **kw}


class TestApplyEdits(unittest.TestCase):
    def test_drop_issue_removes_the_issue_without_mutating_input(self):
        got = apply_edits(SUMMARY, [edit("drop_issue", "公園照明")])
        self.assertEqual([i["topic"] for i in got["issues"]], ["捷運漏水"])
        self.assertEqual(len(SUMMARY["issues"]), 2)

    def test_drop_response_sentence_removes_only_that_text(self):
        got = apply_edits(SUMMARY, [edit("drop_response_sentence", "捷運漏水", text="，將持續關注")])
        self.assertEqual(got["issues"][0]["response"], "局長說明已改善。")
        self.assertEqual(SUMMARY["issues"][0]["response"], "局長說明已改善，將持續關注。")

    def test_unmatched_edits_fail(self):
        for bad in (edit("drop_issue", "不存在的議題"),
                    edit("drop_response_sentence", "捷運漏水", text="不存在的句子"),
                    edit("drop_response_sentence", "公園照明", text="沒有回應"),
                    {**edit("drop_issue", "公園照明"), "name": "乙"},
                    edit("rewrite", "公園照明")):
            with self.assertRaises(EditMismatch, msg=bad):
                apply_edits(SUMMARY, [bad])


class TestRelevanceFilter(unittest.TestCase):
    def test_issue_supported_only_by_pleasantries_is_removed(self):
        corpus = ["謝謝議員，這個我們會研議。", "好，謝謝局長。", "這個部分我們會再研議。", "謝謝。"] * 50 + [
            "公園路燈不足，晚上很暗。", "捷運站漏水很嚴重。"]
        cite = lambda text: {"n": 1, "cited_text": text, "located": True, "short": False,  # noqa: E731
                             "fields": ["councilor"], "source_url": "A#page=1"}
        s, f = filter_citations({"issues": [
            {"topic": "公園照明", "councilor_points": ["要求增設路燈，改善公園夜間照明"], "response": None,
             "citations": [cite("〔公報第1頁〕甲議員：謝謝局長，這個我們會研議。")]},
            {"topic": "捷運漏水", "councilor_points": ["指出捷運站漏水嚴重"], "response": None,
             "citations": [cite("〔公報第2頁〕甲議員：捷運站漏水很嚴重。")]},
        ]}, idf=bigram_idf(corpus))
        self.assertEqual([i["topic"] for i in s["issues"]], ["捷運漏水"])
        self.assertEqual([x["topic"] for x in f["irrelevant_issues"]], ["公園照明"])


class TestCandidateIds(unittest.TestCase):
    def test_returns_only_people_with_a_candidacy_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "civic.db"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE fact (person_id TEXT, kind TEXT)")
            conn.executemany("INSERT INTO fact VALUES (?, ?)",
                             [("run", "candidacy"), ("run", "office"), ("stay", "office"), ("stay", "summary")])
            conn.commit()
            conn.close()
            self.assertEqual(candidate_ids(db), {"run"})


if __name__ == "__main__":
    unittest.main()
