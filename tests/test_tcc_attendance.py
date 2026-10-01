import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from etl.db import open_db, upsert_person
from etl.sources import tcc_attendance
from etl.sources.tcc_attendance import LIST_URL, parse_detail, parse_list, parse_minutes, run, statuses, write_meeting

FIXTURES = Path(__file__).parent / "fixtures"
# 第 2 次定期大會第 9 次會議（112/11/22）議事錄表頭，pdftotext -layout 原文裁切
MINUTES = (FIXTURES / "tcc_minutes_sample.txt").read_text(encoding="utf-8")
LIST_PAGE = (FIXTURES / "tcc_minutes_list_sample.html").read_text(encoding="utf-8")
DETAIL_PAGE = (FIXTURES / "tcc_minutes_detail_sample.html").read_text(encoding="utf-8")
PDF_URL = "https://obasfront.tcc.gov.tw/Agenda/DownloadFile.aspx?FileName=202600013090.pdf&FilePath=pdf/202609&FileGrpKind=2"
DETAIL_URL = "https://www.tcc.gov.tw/MeetingMinutesDetail.aspx?n=13534&GrpKind=2&FileGrpKindSN="


class TestTccAttendance(unittest.TestCase):
    def test_parse_list_skips_talk_meeting(self):
        items = parse_list(LIST_PAGE)
        self.assertEqual([i["sn"] for i in items], ["8C8808456067DCD16A0A2BBC08F57A8F", "DC58BEDABDD2177F9ED5C9BA03118B7F"])
        self.assertEqual(items[0], {
            "sn": "8C8808456067DCD16A0A2BBC08F57A8F", "session": "第14屆第08次定期大會", "meeting": "第10次會議",
            "detail_url": DETAIL_URL + "8C8808456067DCD16A0A2BBC08F57A8F",
        })

    def test_parse_detail_returns_pdf_not_doc(self):
        self.assertEqual(parse_detail(DETAIL_PAGE), PDF_URL)

    def test_parse_minutes_reads_days_attendees_and_leave(self):
        p = parse_minutes(MINUTES)
        self.assertEqual(p["days"], ["2023-11-22", "2023-11-23", "2023-11-24", "2023-11-27", "2023-11-28"])
        self.assertEqual((p["attendees_n"], p["leave_n"]), (57, 6))
        self.assertEqual(p["attendees"][:3], ["王世堅", "秦慧珠", "戴錫欽"])
        self.assertEqual(p["attendees"][-1], "陳政忠")
        # 「葉林傳 (11/23-11/24)」括號前有空白，仍要黏回同一人
        self.assertEqual(p["leave"], [
            ("葉林傳", "11/23-11/24"), ("秦慧珠", "11/24、11/27-11/28"), ("陳重文", "11/23-11/24"),
            ("楊植斗", None), ("林延鳳", None), ("鍾小平", None),
        ])

    def test_parse_minutes_raises_when_count_disagrees(self):
        with self.assertRaises(ValueError):
            parse_minutes(MINUTES.replace("計 57 位", "計 58 位"))
        with self.assertRaises(ValueError):
            parse_minutes(MINUTES.replace("計6位", "計5位"))

    def test_parse_minutes_without_leave_line(self):
        text = MINUTES.split("請假議員")[0] + "列席：\n"
        self.assertEqual(parse_minutes(text)["leave"], [])

    def test_partial_leave_counts_as_present(self):
        st = statuses(parse_minutes(MINUTES))
        self.assertEqual(st["葉林傳"], ("present", "11/23-11/24"))
        self.assertEqual(st["秦慧珠"], ("present", "11/24、11/27-11/28"))
        self.assertEqual(st["楊植斗"], ("leave", None))
        self.assertEqual(st["王孝維"], ("present", None))
        self.assertEqual(len(st), 60)

    def test_leave_without_date_but_also_present_raises(self):
        with self.assertRaises(ValueError):
            parse_minutes(MINUTES.replace("楊植斗     林延鳳", "王孝維     林延鳳"))

    def test_write_meeting_skips_unmapped_and_absent_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            for pid, name in [("pA", "葉林傳"), ("pB", "楊植斗"), ("pC", "王孝維"), ("pD", "遞補者")]:
                upsert_person(conn, pid, name)
            identity = {"葉林傳": ("pA", "x"), "楊植斗": ("pB", "x"), "王孝維": ("pC", "x"), "遞補者": ("pD", "x")}
            item = {"sn": "SN1", "session": "第14屆第02次定期大會", "meeting": "第09次會議", "detail_url": DETAIL_URL + "SN1"}

            n, unmapped = write_meeting(conn, item, parse_minutes(MINUTES), identity, "t")

            self.assertEqual(n, 3)
            self.assertEqual(len(unmapped), 57)
            self.assertIn("王世堅", unmapped)
            rows = {r["person_id"]: r for r in conn.execute("SELECT * FROM fact")}
            self.assertEqual(set(rows), {"pA", "pB", "pC"})  # 遞補者不在名單：不寫
            self.assertEqual(rows["pA"]["fact_key"], "attend:SN1:pA")
            self.assertEqual(rows["pA"]["kind"], "attendance")
            self.assertEqual(rows["pA"]["date"], "2023-11-22")
            self.assertEqual(rows["pA"]["source_url"], DETAIL_URL + "SN1")
            self.assertEqual(json.loads(rows["pA"]["data"]), {
                "term": 14, "session": "第14屆第02次定期大會", "meeting": "第09次會議",
                "days": ["2023-11-22", "2023-11-23", "2023-11-24", "2023-11-27", "2023-11-28"],
                "status": "present", "partial_leave": "11/23-11/24", "attendees_n": 57, "leave_n": 6,
                "title": "第14屆第02次定期大會 第09次會議",
            })
            self.assertEqual(json.loads(rows["pB"]["data"])["status"], "leave")

    def test_run_skips_non_pdf_and_known_meetings(self):
        pages = {
            LIST_URL: LIST_PAGE.encode(),
            DETAIL_URL + "8C8808456067DCD16A0A2BBC08F57A8F": DETAIL_PAGE.encode(),
            DETAIL_URL + "DC58BEDABDD2177F9ED5C9BA03118B7F": DETAIL_PAGE.replace("202600013090.pdf", "BAD.pdf").encode(),
            PDF_URL: b"%PDF-1.4 ...",
            PDF_URL.replace("202600013090.pdf", "BAD.pdf"): b"<html>974 bytes</html>",
        }
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            upsert_person(conn, "pA", "葉林傳")
            requested = []

            def fake_get(url):
                requested.append(url)
                return pages[url]

            out = io.StringIO()
            with mock.patch.object(tcc_attendance, "get", fake_get), \
                    mock.patch.object(tcc_attendance, "pdf_text", lambda _: MINUTES), \
                    mock.patch.object(tcc_attendance, "load_identity", lambda: {"葉林傳": ("pA", "x")}), \
                    contextlib.redirect_stdout(out):
                run(conn)
                self.assertIn("不是 PDF", out.getvalue())
                keys = [r["fact_key"] for r in conn.execute("SELECT fact_key FROM fact")]
                self.assertEqual(keys, ["attend:8C8808456067DCD16A0A2BBC08F57A8F:pA"])

                requested.clear()
                run(conn)  # 增量：已入庫的會議不再抓；失效的那份會再試
                self.assertNotIn(DETAIL_URL + "8C8808456067DCD16A0A2BBC08F57A8F", requested)
                self.assertIn(DETAIL_URL + "DC58BEDABDD2177F9ED5C9BA03118B7F", requested)

            upsert_person(conn, "pB", "楊植斗")
            with mock.patch.object(tcc_attendance, "get", fake_get), \
                    mock.patch.object(tcc_attendance, "pdf_text", lambda _: MINUTES), \
                    mock.patch.object(tcc_attendance, "load_identity", lambda: {"葉林傳": ("pA", "x"), "楊植斗": ("pB", "x")}), \
                    contextlib.redirect_stdout(io.StringIO()):
                run(conn)  # identity 新增未涵蓋的議員 → 整份重掃
            keys = {r["fact_key"] for r in conn.execute("SELECT fact_key FROM fact")}
            self.assertIn("attend:8C8808456067DCD16A0A2BBC08F57A8F:pB", keys)


if __name__ == "__main__":
    unittest.main()
