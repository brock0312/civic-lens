import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import ttt_book

# 第 1 次定期會的 01.pdf、02.pdf 對調；工作檢討不收
BOOKS = """
<a href="/img/download/meeting/meeting20_07/01.pdf" download="第一冊第20屆第19.20次臨時會.pdf" target="_blank">20屆第19、20次臨時會</a>
<a href="/img/download/meeting/meeting20_07/02.pdf" download="第二冊20屆第七次定期會.pdf" target="_blank">20屆第七次定期會</a>
<a href="/img/download/meeting/meeting20_07/03.pdf" download="第三冊20屆單位工作檢討.pdf" target="_blank">20屆第七次定期會單位工位檢討</a>
<a href="/img/download/meeting/meeting20_07/04.pdf" download="第四冊20屆縣政總質詢.pdf" target="_blank">20屆第七次定期會縣政總質詢</a>
<a href="/img/download/meeting/meeting20_01/02.pdf" download="第一冊20屆第1、2、3次臨時會.pdf" target="_blank">20屆第1、2、3次臨時會</a>
<a href="/img/download/meeting/meeting20_01/01.pdf" download="第二冊第20屆第1次定期會.pdf" target="_blank">20屆第1次定期會</a>
<a href="/img/download/meeting/meeting19_08/01.pdf" download="第一冊第19屆第8次定期會.pdf" target="_blank">19屆第8次定期會</a>
"""

# pdftotext -layout 的樣子：姓名在換行處被切開、名單跨頁（頁碼與頁首夾在中間）、請假註記、會勘的會次標題
MEETINGS = [
    "                        -4-\n          議事日程表、議員席次表、質詢順序表、各次會議紀錄\n\n"
    "第 20 屆第 7 次定期會會議紀錄\n報到時間：115 年 05 月 06 日（星期三）\n預備會會議紀錄\n"
    "時間：115 年 05 月 06 日（星期三）上午 09 時 11 分\n地點：本會議事廳\n"
    "出席：甲乙丙、丁戊\n   己、庚辛壬\n請假：周駿宥(出差)\n列席：縣長某某、民政處某處長\n主席：吳議長秀華\n"
    "第 1 會次會議紀錄\n時間：114 年 05 月 07 日（星期四）上午 09 時 02 分\n"
    "出席：甲乙丙、丁戊己、\n\n                 -5-\n臺東縣議會第 20 屆第 7 次定期會\n\n庚辛壬、周駿宥\n請假：無\n列席：某\n",
    "第 2 會次會議紀錄 (台東市某里、颱風勘災)\n時間：115 年 05 月 08 日\n地點：台東市\n"
    "出席：甲乙丙、丁戊己\n請假：庚辛壬、周駿宥\n列席：某\n記錄：某某\n"
    "第 3 會次會議紀錄\n時間：115 年 05 月 11 日\n出席：甲乙丙、丁戊己、臺東縣議會第20屆\n請假：周駿宥\n列席：某\n"
    "第 4 會次會議紀錄\n時間：115 年 05 月 12 日\n出席：甲乙丙、丁戊己\n請假：甲乙丙\n列席：某\n",
]

# 第四冊：題目跨頁、英文詞間的空白、答復行標出單位；第二位議員的第二題題首被頁緣裁掉
QUESTIONS = [
    "臺東縣議會第 20 屆第 7 次定期會\n\n林副議長琮翰書面質詢事項一：\n2026 台東博覽會整體規劃：以 Slow for Life\n作為主軸，是否\n"
    "                      - 500 -\n                               質詢\n排擠預算？\n"
    "依文化處藝文推廣科 115 年 6 月 11 日府文推字第 1150129971 號函復如下：\n執行情形：好。\n",
    "林副議長琮翰書面質詢事項二\n\n 鐵花商圈夜間人潮分佈不均。\n依財政及經濟發展處，115年6月5日府財商字第1號函回覆如下：\n"
    "丁議員戊己書面質詢事項一：\n路燈。\n依建設處 115 年 6 月 1 日府建字第 2 號函\n"
    "詢事項二：\n排水。\n依建設處 115 年 6 月 1 日府建字第 3 號函\n"
    "丁議員戊己書面質詢事項三：\n道路。\n依建設處 115 年 6 月 1 日府建字第 4 號函\n",
]


def new_conn(tmp, people):
    """people：[(person_id, name, 有 2026 candidacy)]，都是臺東縣議員。"""
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "ttt_councilor", "district_id": "ttt-council-01"},
                    "https://u", "t", date="2022-12-25")
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "ttt-council-01"}, "https://u", "t")
    return conn


PEOPLE = [("p1", "林琮翰", True), ("p2", "甲乙丙", True), ("p3", "丁戊己", True), ("p4", "庚辛壬", False),
          ("p5", "周駿宥", True), ("p6", "章正輝 Lemaljiz‧Kusaza", True)]


class TestTttBookParse(unittest.TestCase):
    def test_books_are_classified_by_link_text_not_file_number(self):
        books = ttt_book.parse_books(BOOKS)
        self.assertEqual([(b["id"], b["kind"]) for b in books],
                         [("07-01", "temp"), ("07-02", "regular"), ("07-04", "questions"), ("01-02", "temp"), ("01-01", "regular")])
        with self.assertRaises(ValueError):
            ttt_book.parse_books('<a href="/img/download/meeting/meeting20_02/05.pdf">20屆第二次附錄</a>')

    def test_meetings_join_wrapped_names_and_skip_page_furniture_inside_lists(self):
        ms = ttt_book.parse_meetings(MEETINGS)
        self.assertEqual([(m["session"], m["meeting"], m["page"], m["date"]) for m in ms], [
            ("第20屆第7次定期會", "預備會", 1, "2026-05-06"), ("第20屆第7次定期會", "第1會次", 1, "2025-05-07"),
            ("第20屆第7次定期會", "第2會次", 2, "2026-05-08"), ("第20屆第7次定期會", "第3會次", 2, "2026-05-11"),
            ("第20屆第7次定期會", "第4會次", 2, "2026-05-12")])
        self.assertEqual((ms[0]["present"], ms[0]["leave"]), (["甲乙丙", "丁戊己", "庚辛壬"], ["周駿宥"]))
        self.assertEqual((ms[1]["present"], ms[1]["leave"]), (["甲乙丙", "丁戊己", "庚辛壬", "周駿宥"], []))

    def test_questions_keep_full_text_join_latin_words_and_record_the_answering_unit(self):
        qs = ttt_book.parse_questions(QUESTIONS)
        self.assertEqual([(q["name"], q["no"], q["page"]) for q in qs],
                         [("林琮翰", 1, 1), ("林琮翰", 2, 2), ("丁戊己", 1, 2), ("丁戊己", 3, 2)])
        self.assertEqual(qs[0]["title"], "2026台東博覽會整體規劃：以Slow for Life作為主軸，是否排擠預算？")
        self.assertEqual(qs[0]["dept"], "文化處藝文推廣科")
        self.assertEqual(qs[1]["title"], "鐵花商圈夜間人潮分佈不均。")
        self.assertIsNone(qs[0]["bad"])

    def test_clipped_question_header_drops_both_neighbours_instead_of_merging(self):
        qs = ttt_book.parse_questions(QUESTIONS)
        self.assertIn("下一題編號不連續", qs[2]["bad"])  # 吞了被裁掉的第二題
        self.assertIn("編號不連續", qs[3]["bad"])

    def test_chinese_numerals(self):
        self.assertEqual([ttt_book.cn(x) for x in ("一", "十", "十一", "二十", "二十三")], [1, 10, 11, 20, 23])


class TestTttBookBuild(unittest.TestCase):
    def build(self, withheld=None):
        books = [{"id": "07-02", "path": "/img/download/meeting/meeting20_07/02.pdf", "kind": "regular", "title": "x"},
                 {"id": "07-04", "path": "/img/download/meeting/meeting20_07/04.pdf", "kind": "questions", "title": "y"}]
        texts = {"07-02": MEETINGS, "07-04": QUESTIONS}
        with tempfile.TemporaryDirectory() as tmp:
            logs = []
            out = ttt_book.build(new_conn(tmp, PEOPLE), books, texts, withheld or {}, logs.append)
        return out, logs

    def test_attendance_counts_only_clean_meetings(self):
        (ts, meetings, questions, att, qs, held), logs = self.build()
        self.assertEqual([m["meeting"] for m in meetings], ["預備會", "第1會次", "第2會次"])
        self.assertTrue(any("第3會次" in x and "不是姓名" in x for x in logs))
        self.assertTrue(any("第4會次" in x and "同時在出席與請假" in x for x in logs))
        k, d, url, date = att["p5"][0]
        self.assertEqual(k, "tttattend:7r:p5")
        self.assertEqual((d["meetings"], d["present"], d["leave"]), (3, 1, 2))
        self.assertEqual(url, "https://www.taitungcc.gov.tw/img/download/meeting/meeting20_07/02.pdf#page=1")
        self.assertEqual(date, "2026-05-06")  # 文件中第一次會議，不取誤植年份的最早日期
        self.assertNotIn("p4", att)  # 沒參選 2026
        self.assertEqual(att["p6"][0][1]["present"], 0)

    def test_questions_link_to_the_pdf_page_and_skip_bad_or_withheld_items(self):
        (ts, meetings, questions, att, qs, held), logs = self.build()
        self.assertEqual([k for k, *_ in qs["p1"]], ["tttq:07-04:1:1:p1", "tttq:07-04:2:2:p1"])
        k, d, url, date = qs["p1"][1]
        self.assertEqual(url, "https://www.taitungcc.gov.tw/img/download/meeting/meeting20_07/04.pdf#page=2")
        self.assertEqual((d["session"], d["dept"], d["doc_type"], d["no_date"], date),
                         ("第20屆第7次定期會", "財政及經濟發展處", "書面質詢", True, "2026-05-06"))
        self.assertNotIn("p3", qs)  # 兩題都因編號不連續不收
        (ts, meetings, questions, att, qs, held), logs = self.build({"07-04:1:1": "第三人"})
        self.assertEqual([k for k, *_ in qs["p1"]], ["tttq:07-04:2:2:p1"])
        self.assertEqual(len(held), 1)

    def test_same_name_in_roster_is_not_matched(self):
        books = [{"id": "07-04", "path": "/p.pdf", "kind": "questions", "title": "y"}]
        with tempfile.TemporaryDirectory() as tmp:
            logs = []
            *_, qs, held = ttt_book.build(new_conn(tmp, PEOPLE + [("p9", "林琮翰", True)]), books, {"07-04": QUESTIONS}, {}, logs.append)
        self.assertEqual(qs, {})
        self.assertTrue(any("同名" in x for x in logs))


if __name__ == "__main__":
    unittest.main()
