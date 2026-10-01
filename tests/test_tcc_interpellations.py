import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from etl.db import open_db, upsert_person
from etl.sources import tcc_interpellations
from etl.sources.tcc_interpellations import known_docs, parse_list, parse_viewer, run, write_doc

FIXTURES = Path(__file__).parent / "fixtures"
LIST_SAMPLE = (FIXTURES / "tcc_dq_list_sample.html").read_text(encoding="utf-8")
VIEWER_SAMPLE = (FIXTURES / "tcc_dq_viewer_sample.html").read_text(encoding="utf-8")
VIEWER_URL = "https://gaz.tcc.gov.tw/pdf/viewer.html?id=F626A9A3C33FECE0DAEC37626CEDBFBDF4D1149F9F07E2CCF956DF52FFFF6CDEB1819EADFBF58901D53A4C1421580216D8309A9A54DE7DF3"


class TestTccInterpellations(unittest.TestCase):
    def test_parse_list_reads_fields_and_joint_councillors(self):
        items = parse_list(LIST_SAMPLE)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0], {
            "index": 2508, "date": "2023-02-24", "dept": "教育", "session": "第14屆休會",
            "title": "有關民眾反映，本市國小學生使用之電子信箱有無法接收電子郵件、學生資料有流失之虞乙事，請市府儘速查明並予改善。",
            "councillors": ["徐立信"],
        })
        self.assertEqual(items[1]["councillors"], ["陳宥丞", "張志豪"])
        self.assertEqual(items[1]["index"], 2509)

    def test_parse_list_rejects_item_without_councillor(self):
        with self.assertRaises(ValueError):
            parse_list(LIST_SAMPLE.replace('<span class="starpage">徐立信</span>', ""))

    def test_parse_viewer_reads_doc_no_and_public_viewer_url(self):
        self.assertEqual(parse_viewer(VIEWER_SAMPLE), ("AQ14102629", "民政", "第14屆第08次定期大會", VIEWER_URL))

    def test_parse_viewer_drops_blank_meeting_number_to_match_list(self):
        page = VIEWER_SAMPLE.replace('id="htitle">第14屆第08次定期大會', 'id="htitle">第14屆第  次休會')
        self.assertEqual(parse_viewer(page)[2], "第14屆休會")

    def test_parse_viewer_rejects_non_written_interpellation(self):
        with self.assertRaises(ValueError):
            parse_viewer(VIEWER_SAMPLE.replace("<h2>書面質詢</h2>", "<h2>會議紀錄</h2>"))

    def test_joint_interpellation_writes_one_fact_per_mapped_councillor(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            upsert_person(conn, "pA", "陳宥丞")
            upsert_person(conn, "pB", "張志豪")
            item = parse_list(LIST_SAMPLE)[1]
            identity = {"陳宥丞": ("pA", "x"), "張志豪": ("pB", "y")}

            n = write_doc(conn, item, "AQ14000001", "https://gaz.tcc.gov.tw/pdf/viewer.html?id=AB", identity, "t")

            self.assertEqual(n, 2)
            rows = conn.execute("SELECT fact_key, person_id, kind, date, data FROM fact ORDER BY fact_key").fetchall()
            self.assertEqual([r["fact_key"] for r in rows], ["interp:AQ14000001:pA", "interp:AQ14000001:pB"])
            self.assertEqual({r["kind"] for r in rows}, {"interpellation"})
            self.assertEqual({r["date"] for r in rows}, {"2023-02-24"})
            data = json.loads(rows[0]["data"])
            self.assertEqual(data["title"], "請貴處說明是否有未依法行政與行政怠惰的情事與理由")
            self.assertEqual((data["term"], data["session"], data["doc_type"], data["dept"]),
                             (14, "第14屆休會", "書面質詢", "交通"))
            self.assertEqual(data["councillors"], ["陳宥丞", "張志豪"])
            self.assertEqual(known_docs(conn), {("2023-02-24", data["title"], ("陳宥丞", "張志豪"))})

    def test_unmapped_councillor_gets_no_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            upsert_person(conn, "pA", "陳宥丞")
            item = parse_list(LIST_SAMPLE)[1]

            n = write_doc(conn, item, "AQ14000001", "https://x", {"陳宥丞": ("pA", "x")}, "t")

            self.assertEqual(n, 1)
            self.assertEqual([r[0] for r in conn.execute("SELECT person_id FROM fact")], ["pA"])


PAGE1 = [{
    "index": 1, "date": "2023-02-24", "dept": "教育", "session": "第14屆休會",
    "title": "已知文件", "councillors": ["徐立信"],
}]
PAGE2 = [{
    "index": 2, "date": "2023-01-01", "dept": "交通", "session": "第14屆休會",
    "title": "新對照議員的未知文件", "councillors": ["陳重文"],
}]


class TestRunBackfill(unittest.TestCase):
    def _run_with_pages(self, conn, identity):
        pages = {1: PAGE1, 2: PAGE2, 3: []}

        def fake_get(self, path, params=None):
            return ""  # 內容不重要，parse_list/parse_viewer 都被 monkeypatch 掉了

        def fake_parse_list(page, _pages=iter([1, 2, 3])):
            return pages[next(_pages)]

        def fake_parse_viewer(page):
            return ("AQ14999999", "交通", "第14屆休會", "https://gaz.tcc.gov.tw/pdf/viewer.html?id=X")

        with mock.patch.object(tcc_interpellations, "load_identity", return_value=identity), \
             mock.patch.object(tcc_interpellations.Session, "get", fake_get), \
             mock.patch.object(tcc_interpellations, "parse_list", fake_parse_list), \
             mock.patch.object(tcc_interpellations, "parse_viewer", fake_parse_viewer):
            run(conn)

    def test_stops_at_known_page_when_all_councillors_covered(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            upsert_person(conn, "p1", "徐立信")
            upsert_person(conn, "p2", "陳重文")
            identity = {"徐立信": ("p1", "x"), "陳重文": ("p2", "x")}
            write_doc(conn, PAGE1[0], "AQ14000001", "https://gaz.tcc.gov.tw/pdf/viewer.html?id=Y", identity, "t")
            conn.execute(
                "INSERT INTO source_state (source, state) VALUES (?, ?)",
                ("tcc_interpellations", json.dumps({"covered": sorted(identity)})),
            )

            self._run_with_pages(conn, identity)

            rows = conn.execute("SELECT fact_key FROM fact").fetchall()
            self.assertEqual({r["fact_key"] for r in rows}, {"interp:AQ14000001:p1"})

    def test_scans_to_end_when_identity_has_uncovered_councillor(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            upsert_person(conn, "p1", "徐立信")
            upsert_person(conn, "p2", "陳重文")
            identity = {"徐立信": ("p1", "x"), "陳重文": ("p2", "x")}
            write_doc(conn, PAGE1[0], "AQ14000001", "https://gaz.tcc.gov.tw/pdf/viewer.html?id=Y", identity, "t")
            conn.execute(
                "INSERT INTO source_state (source, state) VALUES (?, ?)",
                ("tcc_interpellations", json.dumps({"covered": ["徐立信"]})),
            )

            self._run_with_pages(conn, identity)

            rows = conn.execute("SELECT fact_key FROM fact").fetchall()
            self.assertEqual({r["fact_key"] for r in rows}, {"interp:AQ14000001:p1", "interp:AQ14999999:p2"})
            state = json.loads(
                conn.execute(
                    "SELECT state FROM source_state WHERE source = 'tcc_interpellations'"
                ).fetchone()["state"]
            )
            self.assertEqual(state["covered"], sorted(identity))


if __name__ == "__main__":
    unittest.main()
