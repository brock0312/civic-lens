import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import hsz_book, hsz_videos

BOOKS = """
<li class="download-detail download-li02 download-li02--style">
    第11屆第22次臨時會議事錄</li>
<li class="download-detail download-li03">
    <a href="/upload/79/2026081415130658085新竹市議會--第11屆第22次臨時會.pdf" target="_blank" title="x"> (pdf)</a>
<li class="download-detail download-li02 download-li02--style">
    第10屆第8次定期會暨第22-24次臨時會(上冊)</li>
<li class="download-detail download-li03">
    <a href="/upload/79/2024062610294875217第10屆第8次定期會暨第22-24次臨時會(上冊).pdf" target="_blank"> (pdf)</a>
<a href="?pn=5&mid=79&key=&cchk=" title="5">5</a>
"""

# pdftotext -layout 的樣子：表頭月份與日期分行、「-」與「—」都是請假、跨頁的頁尾、合計列
TABLE = [
    "  (三)議員出缺席表 ······ 147\n中華民國 115 年 5 月 4 日（星期一）上午 10 時\n",
    "  （三）新竹市議會第 11 屆第 22 次臨時會議員出缺席表\n"
    "       5 5 5               合計\n    日期 月 月 月\n姓名     4 5 6            出 請\n       日日日               席 假\n"
    " 1 張 峻 Ο Ο Ο               3\n 2 甲乙丙 — Ο -               1    2\n"
    " 3 丁戊己 Ο Ο Ο               2    1\n"  # 合計和標記不一致
    " 4 庚辛壬 Ο Ο                 2\n"  # 少一天
    "                          附錄 147\n"
    " 5 周駿宥 Ο Ο Ο               3\n"
    "合 出 席 4 3 3\n計 請 假 1 1\n附註：（Ο）係指出席（—）係指請假\n",
    "  （四）新竹市議會第 11 屆第 21 次臨時會議員出缺席表\n       4 4\n    日期 月 月\n姓名     9 10\n"
    " 1 張 峻 Ο Ο    2\n詢 人：被裁掉的格首\n合 出 席 1 1\n附註：\n",
]

QUESTIONS = """
<ul class="proposal-information-content__box01 flex">
  <li class="proposal-detail proposal-li01 meeting-li04">第11屆</li>
  <li class="proposal-detail proposal-li02 meeting-li01">第6次定期會</li>
  <li class="proposal-detail proposal-li04">114.11.21</li>
  <li class="proposal-detail proposal-li04 inter-li02">甲乙丙</li>
  <li class="proposal-detail proposal-li08 meeting-li03">
    <a href="/upload/41/2026042716401961382市24、25--甲乙丙、張峻(民進黨團聯合質詢).pdf" target="_blank"> (pdf)</a></li>
</ul>
<ul class="proposal-information-content__box01 flex">
  <li class="proposal-detail proposal-li01 meeting-li04">第11屆</li>
  <li class="proposal-detail proposal-li02 meeting-li01">第1次定期會</li>
  <li class="proposal-detail proposal-li04">112.05.30</li>
  <li class="proposal-detail proposal-li04 inter-li02">陳治雄</li>
  <li class="proposal-detail proposal-li08 meeting-li03">
    <a href="/upload/41/2024061211591599870de9167ad-4e82.pdf" target="_blank"> (pdf)</a></li>
</ul>
<ul class="proposal-information-content__box01 flex">
  <li class="proposal-detail proposal-li01 meeting-li04">第11屆</li>
  <li class="proposal-detail proposal-li02 meeting-li01">第6次定期會</li>
  <li class="proposal-detail proposal-li04">114.11.22</li>
  <li class="proposal-detail proposal-li04 inter-li02">庚辛壬</li>
  <li class="proposal-detail proposal-li08 meeting-li03">
    <a href="/upload/41/2026042716570388484市33--庚辛壬.pdf" target="_blank"> (pdf)</a></li>
</ul>
<a href="?pn=3&mid=41&cc=11&c=24&m=&member=&cchk=" title="3">3</a>
"""

VIDEOS = (
    '<section class="video-content__list"><iframe src="https://www.youtube.com/embed/Xb8Degsaca4" title="x"></iframe>'
    '<div class="video-text-box"><h3 class="video-text__tittle">市政總質詢：甲乙丙、張峻、陳治雄</h3><div>'
    '<span class="video-content-date">115.06.09</span><span class="video-content-category">第11屆第7次定期會</span></div></div></section>'
    '<section class="video-content__list"><iframe src="https://www.youtube.com/embed/KfQId7nikDQ" title="x"></iframe>'
    '<div class="video-text-box"><h3 class="video-text__tittle">單位業務質詢 周駿宥 甲乙丙-2</h3><div>'
    '<span class="video-content-date">114.06.18</span><span class="video-content-category">第11屆第5次定期會</span></div></div></section>'
    '<section class="video-content__list"><iframe src="https://www.youtube.com/embed/aaaaaaaaaaa" title="x"></iframe>'
    '<div class="video-text-box"><h3 class="video-text__tittle">審議提案</h3><div>'
    '<span class="video-content-date">115.07.13</span><span class="video-content-category">第11屆第24次臨時會</span></div></div></section>'
    '<a href="?pn=55&mid=85&cc=11&m=&c=&y=&mon=&key=" title="55">55</a>'
)


def new_conn(tmp, people):
    """people：[(person_id, name, 有 2026 candidacy)]，都是新竹市議員。"""
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:hsz-council-2022:{pid}", pid, "office", {"office": "hsz_councilor", "district_id": "hsz-council-01"},
                    "https://u", "t", date="2022-12-25")
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "hsz-council-01"}, "https://u", "t")
    return conn


PEOPLE = [("p1", "張峻", True), ("p2", "甲乙丙", True), ("p3", "丁戊己", True), ("p4", "庚辛壬", False), ("p5", "周駿宥", True)]


class TestHszAttendance(unittest.TestCase):
    def test_books_keep_current_term_and_read_last_page(self):
        books = hsz_book.parse_books(BOOKS)
        self.assertEqual([b["title"] for b in books], ["第11屆第22次臨時會議事錄"])
        self.assertEqual(books[0]["name"], "2026081415130658085新竹市議會--第11屆第22次臨時會")
        self.assertEqual(hsz_book.last_page(BOOKS), 5)

    def test_table_reads_days_dates_and_rows(self):
        t = hsz_book.parse_attendance(TABLE)[0]
        self.assertEqual((t["session"], t["page"], t["days"], t["dates"]), ("第11屆第22次臨時會", 2, 3, [(5, 4), (5, 5), (5, 6)]))
        self.assertEqual([r["name"] for r in t["rows"]], ["張峻", "甲乙丙", "丁戊己", "庚辛壬", "周駿宥"])
        self.assertEqual(t["rows"][1], {"no": 2, "name": "甲乙丙", "marks": "—Ο-", "present": 1, "leave": 2})
        self.assertEqual(t["bad"], [])

    def test_rows_must_match_days_and_totals(self):
        rows = hsz_book.parse_attendance(TABLE)[0]["rows"]
        self.assertIsNone(hsz_book.check_row(rows[1], 3))
        self.assertIn("不一致", hsz_book.check_row(rows[2], 3))
        self.assertIn("表上 3 天", hsz_book.check_row(rows[3], 3))

    def test_header_may_list_a_day_off_that_the_totals_skip(self):
        header = ["       10 10 10", "    日期 月 月 月", "姓名            出 請", "        2 3 5     席 假"]
        self.assertEqual(hsz_book._header_dates(header, 2), [(10, 2), (10, 3), (10, 5)])
        self.assertIsNone(hsz_book._header_dates(header, 4))

    def test_year_is_the_most_common_one_inside_the_term(self):
        texts = ["109 年 5 月 15 日 109 年 5 月 15 日 109年5月15日", "112 年 5 月 15 日（星期一）"]
        self.assertEqual(hsz_book._year(texts, 5, 15, today="2026-10-08"), 2023)
        self.assertIsNone(hsz_book._year(texts + ["113 年 5 月 15 日"], 5, 15, today="2026-10-08"))  # 並列不猜
        self.assertIsNone(hsz_book._year(["沒有日期"], 5, 15))

    def test_unrecognised_line_inside_a_table_is_flagged(self):
        self.assertEqual(hsz_book.parse_attendance(TABLE)[1]["bad"], ["詢 人：被裁掉的格首"])

    def test_attendance_facts_only_for_candidates_with_clean_rows(self):
        books = [{"title": "第11屆第22次臨時會議事錄", "path": "/upload/79/x.pdf", "name": "x"}]
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, PEOPLE)
            logs = []
            ts, tables, att, qs = hsz_book.build(conn, books, {"x": TABLE}, [], logs.append)
        self.assertEqual([t["session"] for t in tables], ["第11屆第22次臨時會"])  # 第 21 次整表不收
        self.assertEqual(sorted(att), ["p1", "p2", "p5"])  # p3 合計不一致、p4 沒參選
        key, data, url, date = att["p2"][0]
        self.assertEqual(key, "hszattend:22t:p2")
        self.assertEqual((data["meetings"], data["present"], data["leave"], date), (3, 1, 2, "2026-05-04"))
        self.assertTrue(url.endswith("/upload/79/x.pdf#page=2"))
        self.assertTrue(any("第11屆第21次臨時會" in x and "整表不收" in x for x in logs))
        self.assertTrue(any("丁戊己" in x and "不一致" in x for x in logs))


class TestHszQuestions(unittest.TestCase):
    def test_listing_rows_and_malformed_rows(self):
        qs = hsz_book.parse_questions(QUESTIONS)
        self.assertEqual(qs[0], {"term": "第11屆", "session": "第11屆第6次定期會", "date": "2025-11-21", "name": "甲乙丙",
                                 "path": "/upload/41/2026042716401961382市24、25--甲乙丙、張峻(民進黨團聯合質詢).pdf"})
        with self.assertRaises(ValueError):
            hsz_book.parse_questions('<ul class="proposal-information-content__box01 flex"><li>第11屆</li></ul>')

    def test_question_facts_link_each_listed_candidate_only(self):
        qs = [{**q, "doc_type": "市政總質詢"} for q in hsz_book.parse_questions(QUESTIONS)]
        with tempfile.TemporaryDirectory() as tmp:
            logs = []
            ts, tables, att, out = hsz_book.build(new_conn(tmp, PEOPLE), [], {}, qs, logs.append)
        self.assertEqual(sorted(out), ["p2"])  # 陳治雄不在名錄、庚辛壬沒參選
        key, data, url, date = out["p2"][0]
        self.assertEqual(key, "hszq:2026042716401961382:p2")
        self.assertEqual((data["doc_type"], data["dept"], data["title"], date), ("質詢紀錄", "市政總質詢", "市政總質詢紀錄（PDF）", "2025-11-21"))
        self.assertTrue(url.startswith("https://www.hsinchu-cc.gov.tw/upload/41/2026042716401961382%E5%B8%82"))
        self.assertTrue(any("陳治雄" in x for x in logs))


class TestHszVideos(unittest.TestCase):
    def test_titles_with_colon_or_spaces_and_part_suffix(self):
        self.assertEqual(hsz_videos.parse_title("市政總質詢：施乃如、劉崇顯、陳啓源"),
                         {"doc_type": "市政總質詢", "names": ["施乃如", "劉崇顯", "陳啓源"]})
        self.assertEqual(hsz_videos.parse_title("市政總質詢 吳旭豐 劉崇顯 林盈徹-2"),
                         {"doc_type": "市政總質詢", "names": ["吳旭豐", "劉崇顯", "林盈徹"]})
        self.assertEqual(hsz_videos.parse_title("單位業務質詢 ：李國璋、陳慶齡")["names"], ["李國璋", "陳慶齡"])
        self.assertEqual(hsz_videos.parse_title("單位業務質詢；彭昆耀、徐美惠")["names"], ["彭昆耀", "徐美惠"])
        # 註「(書面)」的人沒有在影片中質詢；括號內另列的姓名不收；黨團聯合質詢的註記去掉
        self.assertEqual(hsz_videos.parse_title("市政總質詢：吳國寶 (書面)、黃文政、林慈愛(書面)")["names"], ["黃文政"])
        self.assertEqual(hsz_videos.parse_title("市政總質詢：劉康彥、孫鍚洲(李國璋、張祖琰)")["names"], ["劉康彥", "孫鍚洲"])
        self.assertEqual(hsz_videos.parse_title("市政總質詢：徐美惠 鍾淑英聯合質詢 、楊玲宜 林盈徹(民進黨團聯合質詢)")["names"],
                         ["徐美惠", "鍾淑英", "楊玲宜", "林盈徹"])
        self.assertIsNone(hsz_videos.parse_title("審議提案"))
        self.assertIsNone(hsz_videos.parse_title("1、議員報到 2、預備會議 （2）抽籤決定議員質詢順序"))
        with self.assertRaises(ValueError):
            hsz_videos.parse_title("市政總質詢延會")

    def test_videos_are_assigned_to_resolved_candidates(self):
        items, last = hsz_videos.parse_page(VIDEOS)
        self.assertEqual(last, 55)
        self.assertEqual(items[0]["date"], "2026-06-09")
        with tempfile.TemporaryDirectory() as tmp:
            logs = []
            ts, by_pid = hsz_videos.build(new_conn(tmp, PEOPLE), items, logs.append)
        self.assertEqual(sorted(by_pid), ["p1", "p2", "p5"])
        self.assertEqual([v["video_id"] for v in by_pid["p2"]], ["KfQId7nikDQ", "Xb8Degsaca4"])
        self.assertEqual(by_pid["p5"][0]["names"], ["周駿宥", "甲乙丙"])
        self.assertTrue(any("陳治雄" in x for x in logs))


if __name__ == "__main__":
    unittest.main()
