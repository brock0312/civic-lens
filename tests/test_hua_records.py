import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import hua_book, hua_videos

BOOKS = """
<div class="card-title"><a class="naz" role="button"><span class="font_blod"><img src="images/icon01.gif" alt="" /> 第20屆第六次定期大會暨第16、17、18次臨時大會議事錄_上冊 <span class="color_brown">( 2026-09-22</span> )</span></a></div>
<a style="width: 250px;" class="button" href="upfile/20260922155504-147.pdf" target="_blank">下載議事錄pdf文件</a>
<div class="card-title"><a class="naz" role="button"><span class="font_blod"><img src="images/icon01.gif" alt="" /> 第20屆第六次定期大會暨第16、17、18次臨時大會議事錄_下冊 <span class="color_brown">( 2026-09-22</span> )</span></a></div>
<a style="width: 250px;" class="button" href="upfile/20260922155154-162.pdf" target="_blank">下載議事錄pdf文件</a>
<div class="card-title"><a class="naz" role="button"><span class="font_blod"><img src="images/icon01.gif" alt="" /> 第20屆第19、20次臨時大會_議事錄 <span class="color_brown">( 2026-08-25</span> )</span></a></div>
<a style="width: 250px;" class="button" href="upfile/20260825083951-100.pdf" target="_blank">下載議事錄pdf文件</a>
"""

# pdftotext -raw 的樣子：頁首、全形空白的姓名、換行時黏在一起的兩個名字、列席之後的議員請假、分組審查會議
MEETINGS = [
    "目錄\n（一）一讀會議······8\n",
    "8 會議紀錄\n花蓮縣議會第 20 屆第 6 次定期大會會議紀錄\n一讀會會議紀錄\n"
    "時間：中華民國 114 年 10 月 31 日（五）上午 9 時 30 分\n地點：本會議事廳\n"
    "出席：張 峻、甲乙丙、丁戊己\n庚辛壬\n請假：周駿宥\n列席：饒代理秘書長忠\n主席：張議長峻\n",
    "會議紀錄 9\n第 2 次會議紀錄\n時間：中華民國 114 年 11 月 3 日（星期一）上午 9 時整\n"
    "出席：張 峻、甲乙丙丁戊己、庚辛壬\n列席：民政處\n本會陳秘書長德惠\n請假：周議員駿宥、建設處處長某某\n主席：張議長峻\n"
    "分組審查會議紀錄\n民政（第一）審查委員會第1 次會議紀錄\n時間：中華民國 114 年 11 月 4 日\n出席：金議員淑敏\n",
    "花蓮縣議會第 20 屆第 16 次臨時大會會議紀錄\n一讀會會議紀錄\n時間：中華民國 114 年８月 11 日（星期一）上午 9 時 30 分\n"
    "出席：張 峻、甲乙丙、丁戊己、周駿宥\n請假：\n列席：某\n請假：人事處吳處長賢惠\n主席：張議長峻\n"
    "一讀會會議紀錄\n時間：中華民國 114 年 9 月 1 日\n出席：張 峻\n",
]

QUESTIONS = [
    "雜項\n質 詢 人：不收 類 別：不在章內\n",
    "口頭質詢 799\n花蓮縣議會第 20 屆第 6 次定期大會口頭質詢\n"
    "質 詢 人：甲乙丙、 類 別：原住民行政處\n丁戊己、周駿宥\n"
    "質詢事項：有關補助原住民社工員（師）實施計畫，原\n住民族委員會 115 年無編列預算。\n"
    "答覆事項：一、經費 1,006 萬元。\n答 覆 人：原住民行政處處長某某\n"
    "質 詢 人：甲乙丙、丁戊己、\n周駿宥 類 別：教育處\n質詢事項：請提供 Roblox\nApp 風險。\n答覆事項：好。\n",
    "800 口頭質詢\n質 詢 人：張 峻 類 別：花蓮縣\n環境保護局\n質詢事項：垃圾火災問題。\n答 覆 人：局長\n"
    "花蓮縣議會第 20 屆第 6 次定期大會書面質詢\n質 詢 人：庚辛壬 類 別：建設處\n質詢事項：說明住宅計畫。\n答覆事項：好。\n",
]

INDEX = [
    "議員質詢索引表 45\n花蓮縣議會第 20 屆第 6 次定期大會議員質詢索引表\n姓名 頁 碼\n張 峻\n95、96、97\n98\n甲乙丙 -\n",
    "46 議員質詢索引表\n姓名 頁 碼\n哈尼．\n噶照\n387、388\n金淑敏 209\n",
    "工作報告暨業務探討 51\n主席張議長峻\n周駿宥 12\n",
]


def new_conn(tmp, people):
    """people：[(person_id, name, 有 2026 candidacy)]，都是花蓮縣議員。"""
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "hua_councilor", "district_id": "hua-council-01"},
                    "https://u", "t", date="2022-12-25")
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "hua-council-01"}, "https://u", "t")
    return conn


PEOPLE = [("p1", "張峻", True), ("p2", "甲乙丙", True), ("p3", "丁戊己", True), ("p4", "庚辛壬", False),
          ("p5", "周駿宥", True), ("p6", "哈尼．噶照 Hani Kacaw", True), ("p7", "金淑敏", True), ("p8", "金淑敏", True)]


class TestHuaBookParse(unittest.TestCase):
    def test_books_skip_the_second_volume_of_reports(self):
        self.assertEqual([(b["id"], b["date"]) for b in hua_book.parse_books(BOOKS)],
                         [("20260922155504-147", "2026-09-22"), ("20260825083951-100", "2026-08-25")])

    def test_meetings_read_plenary_lists_only_and_skip_committee_records(self):
        ms = hua_book.parse_meetings(MEETINGS)
        self.assertEqual([(m["session"], m["meeting"], m["page"], m["date"]) for m in ms],
                         [("第20屆第6次定期大會", "一讀會", 2, "2025-10-31"), ("第20屆第6次定期大會", "第2次", 3, "2025-11-03"),
                          ("第20屆第16次臨時大會", "一讀會", 4, "2025-08-11")])
        self.assertEqual(ms[0]["present"], ["張峻", "甲乙丙", "丁戊己", "庚辛壬"])
        self.assertEqual(ms[0]["leave"], ["周駿宥"])

    def test_leave_after_attendees_keeps_only_councillors(self):
        ms = hua_book.parse_meetings(MEETINGS)
        self.assertEqual(ms[1]["leave"], ["周駿宥"])
        self.assertEqual(ms[2]["leave"], [])  # 列席之後的「人事處吳處長賢惠」不是議員

    def test_second_first_reading_under_one_session_heading_is_not_attributed(self):
        self.assertNotIn("2025-09-01", [m["date"] for m in hua_book.parse_meetings(MEETINGS)])

    def test_glued_names_split_only_into_a_unique_roster_cut(self):
        roster = {"甲乙丙": ["p2"], "丁戊己": ["p3"], "甲乙": ["px"], "丙丁戊己": ["py"]}
        self.assertEqual(hua_book.resolve_token("甲乙丙丁戊己", roster), (None, "名錄沒有此人"))  # 兩種切法，不收
        del roster["甲乙"]
        self.assertEqual(hua_book.resolve_token("甲乙丙丁戊己", roster), (["p2", "p3"], None))
        self.assertEqual(hua_book.resolve_token("黃鈴蘭", {"黃玲蘭": ["p9"]}), (None, "名錄沒有此人"))

    def test_questions_handle_wrapped_askers_wrapped_categories_and_page_headers(self):
        qs = hua_book.parse_questions(QUESTIONS)
        self.assertEqual([(q["doc_type"], q["names"], q["dept"], q["page"], q["n"]) for q in qs], [
            ("口頭質詢答覆", ["甲乙丙", "丁戊己", "周駿宥"], "原住民行政處", 2, 0),
            ("口頭質詢答覆", ["甲乙丙", "丁戊己", "周駿宥"], "教育處", 2, 1),
            ("口頭質詢答覆", ["張峻"], "花蓮縣環境保護局", 3, 0),
            ("書面質詢", ["庚辛壬"], "建設處", 3, 1)])
        self.assertEqual(qs[0]["title"], "有關補助原住民社工員（師）實施計畫，原住民族委員會 115 年無編列預算。")
        self.assertEqual(qs[1]["title"], "請提供 Roblox App 風險。")
        self.assertEqual(qs[0]["session"], "第20屆第6次定期大會")

    def test_index_joins_wrapped_names_and_ignores_empty_entries(self):
        e = hua_book.parse_index(INDEX)
        self.assertEqual([(x["name"], x["pages"], x["pdf_page"]) for x in e],
                         [("張峻", [95, 96, 97, 98], 1), ("甲乙丙", [], 1), ("哈尼．噶照", [387, 388], 2), ("金淑敏", [209], 2)])


class TestHuaBookBuild(unittest.TestCase):
    def build(self, withheld=None):
        books = [{"title": "x", "date": "2026-09-22", "id": "f1"}]
        texts = {"f1": MEETINGS + QUESTIONS + INDEX}
        with tempfile.TemporaryDirectory() as tmp:
            logs = []
            out = hua_book.build(new_conn(tmp, PEOPLE), books, texts, withheld or {}, logs.append)
        return out, logs

    def test_attendance_counts_present_and_leave_per_session_for_candidates(self):
        (ts, meetings, att, qs, tr, held), logs = self.build()
        self.assertEqual(len(meetings), 3)
        rows = {k: d for k, d, url, date in att["p5"]}
        self.assertEqual(rows["hlccattend:6r:p5"]["meetings"], 2)
        self.assertEqual((rows["hlccattend:6r:p5"]["present"], rows["hlccattend:6r:p5"]["leave"]), (0, 2))
        self.assertEqual((rows["hlccattend:16t:p5"]["present"], rows["hlccattend:16t:p5"]["meetings"]), (1, 1))
        self.assertEqual(att["p5"][0][2], "https://www.hlcc.gov.tw/upfile/f1.pdf#page=2")
        self.assertNotIn("p4", att)  # 沒參選 2026
        self.assertNotIn("p7", att)  # 名錄同名

    def test_questions_go_to_every_resolved_asker_with_a_page_link(self):
        (ts, meetings, att, qs, tr, held), logs = self.build()
        keys = [k for k, *_ in qs["p2"]]
        self.assertEqual(keys, ["hlccq:f1:6:0:p2", "hlccq:f1:6:1:p2"])
        k, d, url, date = qs["p5"][0]
        self.assertEqual(url, "https://www.hlcc.gov.tw/upfile/f1.pdf#page=6")
        self.assertEqual((d["doc_type"], d["dept"], date, d["no_date"]), ("口頭質詢答覆", "原住民行政處", "2025-10-31", True))
        self.assertNotIn("p4", qs)

    def test_withheld_items_are_not_written(self):
        (ts, meetings, att, qs, tr, held), logs = self.build({"f1:6:0": "第三人"})
        self.assertEqual([k for k, *_ in qs["p2"]], ["hlccq:f1:6:1:p2"])
        self.assertEqual(len(held), 1)

    def test_transcript_index_links_to_the_index_page(self):
        (ts, meetings, att, qs, tr, held), logs = self.build()
        k, d, url, date = tr["p6"][0]
        self.assertEqual((k, url), ("hlcctr:f1:p6", "https://www.hlcc.gov.tw/upfile/f1.pdf#page=9"))
        self.assertEqual(d["title"], "第6次定期大會質詢（錄音）紀錄：議員質詢索引表列 2 頁（議事錄第 387–388 頁）")
        self.assertNotIn("p2", tr)  # 「甲乙丙 -」沒有頁碼
        self.assertTrue(any("金淑敏" in x and "同名" in x for x in logs))


class TestHuaVideos(unittest.TestCase):
    def test_title_gives_session_date_and_listed_askers_only(self):
        t = "花蓮縣議會第20屆第6次定期大會-2025年11月28日上午議程：縣政總質詢-魏嘉賢議員(緊急動議)、楊華美議員(蔡依靜議員補充)、徐雪玉副議長。"
        self.assertEqual(hua_videos.parse_title(t), {"term": 20, "session": "第20屆第6次定期大會", "date": "2025-11-28",
                                                     "half": "上午", "names": ["魏嘉賢", "楊華美", "徐雪玉"]})
        self.assertIsNone(hua_videos.parse_title("花蓮縣議會第20屆第8次定期大會-2026年10月7日下午議程：觀光處、財政處工作報告業務探討及意見交換。"))
        with self.assertRaises(ValueError):
            hua_videos.parse_title("花蓮縣議會第20屆第6次定期大會：縣政總質詢-甲議員")

    def test_videos_are_assigned_to_resolved_askers(self):
        page = ('<span class="font_blod">花蓮縣議會第20屆第7次定期大會-2026年6月1日上午議程：縣政總質詢-甲乙丙議員、黃鈴蘭議員、哈尼.噶照議員。\n</span>'
                '<a class="naz" href="https://youtu.be/wzEcGeiN2YM" target="_blank">')
        items = hua_videos.parse_page(page)
        with tempfile.TemporaryDirectory() as tmp:
            logs = []
            ts, by_pid = hua_videos.build(new_conn(tmp, PEOPLE), items, logs.append)
        self.assertEqual(sorted(by_pid), ["p2", "p6"])
        self.assertEqual(by_pid["p6"][0]["names"], ["甲乙丙", "黃鈴蘭", "哈尼.噶照"])
        self.assertTrue(any("黃鈴蘭" in x for x in logs))


if __name__ == "__main__":
    unittest.main()
