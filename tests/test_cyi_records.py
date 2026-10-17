import tempfile
import unittest
from pathlib import Path
from unittest import mock

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import cyi_book

TOC = ("    嘉義市議會第 11 屆第 7 次定期會\n                目      錄\n\n口頭質詢及答覆\n\n"
       "（1）第 9 次會議市政總質詢及答覆（115 年 4 月 30 日）………1107\n\n"
       "（2）第 10 次會議市政總質詢及答覆（115 年 5 月 4 日）………1108\n")


def oral_book(pages, toc=TOC):
    """pdftotext -layout 的樣子：封面、章目錄，之後每頁頁首「口頭質詢及答覆 1107」（偶數頁「1108 口頭質詢及答覆」）。"""
    body = [(f"   口頭質詢及答覆    {n}\n" if n % 2 else f"{n}   口頭質詢及答覆\n") + p for n, p in pages]
    return "\f".join(["  封面\n", toc] + body)


LONG = "本席要請教市長有關停車的問題，" * 20  # 300 字
P9 = ("\n        第 9 次會議市政總質詢及答覆\n                              115.04.30\n"
      "議員鄭光宏質詢：\n  " + LONG + "\n建設處長羅資政答覆：\n  報告議員，我們會處理。\n"
      "議員黃盈智質詢：\n  我補充一句。\n")
P10 = ("\n        第 10 次會議市政總質詢及答覆\n                              115.05.04\n"
       "議員黃盈智質詢：\n  " + LONG + "\n文化局長謝育哲答覆：\n  好。\n議員黃盈智質詢：\n  " + LONG + "\n")


def att_words(names, present, leave, xs=None, title="嘉義市議會第11屆第7次定期會議員出席表", first="115.04.20"):
    """出席表的 bbox 字：直排姓名（每字一個 word）、逐日列日期、合計出席／請假兩列；leave 的 None 是留白。"""
    xs = xs or [150 + 17 * i for i in range(len(names))]
    words = [(270, 80, title), (60, 100, "議員姓名")]
    for x, n in zip(xs, names):
        words += [(x, 105 + 12 * k, ch) for k, ch in enumerate(n)]
    words += [(40, 150, first), (90, 150, "第1次會議")]
    words += [(100, 700, "出席")] + [(x, 700, str(v)) for x, v in zip(xs, present)]
    words += [(100, 720, "請假")] + [(x, 720, str(v)) for x, v in zip(xs, leave) if v is not None]
    return words


class TestCyiOral(unittest.TestCase):
    def test_each_councillor_links_the_page_of_their_longest_run(self):
        ms = cyi_book.parse_oral(3462, oral_book([(1107, P9), (1108, P10)]), log=lambda s: None)
        self.assertEqual([(m["no"], m["date"], m["printed"], m["page"]) for m in ms], [(9, "2026-04-30", 1107, 3), (10, "2026-05-04", 1108, 4)])
        self.assertEqual(set(ms[0]["askers"]), {"鄭光宏"})  # 黃盈智在第 9 次只補充一句（不足 200 字）
        self.assertEqual(ms[0]["askers"]["鄭光宏"][:2], (3, 1107))
        page, printed, chars = ms[1]["askers"]["黃盈智"]
        self.assertEqual((page, printed), (4, 1108))
        self.assertEqual(chars, 2 * len(LONG))  # 中間只有官員答覆：同一段，答覆字數不計

    def test_meeting_whose_heading_disagrees_with_the_chapter_toc_is_dropped(self):
        logs = []
        ms = cyi_book.parse_oral(3462, oral_book([(1107, P9), (1109, P10)]), log=logs.append)  # 目錄寫第 10 次在 1108 頁
        self.assertEqual([m["no"] for m in ms], [9])
        self.assertTrue(any("第 10 次會議標題" in x and "與章目錄" in x for x in logs))

    def test_book_without_oral_chapter_yields_nothing(self):
        self.assertEqual(cyi_book.parse_oral(3462, "封面\f市政府各單位工作報告 811\n內容\n"), [])

    def test_reviewed_label_typo_is_fixed_only_for_its_key(self):
        text = oral_book([(1107, P9.replace("議員鄭光宏質詢：", "議鄭光宏質詢："))])
        with mock.patch.dict(cyi_book.NAME_FIX, {(3462, 3, "議鄭光宏質詢："): "鄭光宏"}):
            self.assertIn("鄭光宏", cyi_book.parse_oral(3462, text, log=lambda s: None)[0]["askers"])
            self.assertEqual(cyi_book.parse_oral(3463, text, log=lambda s: None)[0]["askers"], {})

    def test_renamed_labels_merge_into_one_run_only_for_their_keys(self):
        p10 = P10.replace("議員黃盈智質詢：", "議員舊名甲質詢：", 1).replace("議員黃盈智質詢：", "議員舊名乙質詢：")
        text = oral_book([(1107, P9), (1108, p10)])
        with mock.patch.dict(cyi_book.LABEL_ALIAS, {(3462, "舊名甲"): "黃盈智", (3462, "舊名乙"): "黃盈智"}):
            askers = cyi_book.parse_oral(3462, text, log=lambda s: None)[1]["askers"]
            self.assertEqual((set(askers), askers["黃盈智"][2]), ({"黃盈智"}, 2 * len(LONG)))  # 兩種寫法接成同一段
            self.assertEqual(set(cyi_book.parse_oral(3463, text, log=lambda s: None)[1]["askers"]), {"舊名甲", "舊名乙"})


class TestCyiAttendance(unittest.TestCase):
    def test_vertical_names_are_assembled_by_column_and_totals_matched_by_x(self):
        cols, first = cyi_book.parse_attendance(att_words(["黃盈智", "王浩", "蘇澤峰"], [30, 30, 24], [0, 0, 6]))
        self.assertEqual(cols, {"黃盈智": (30, 0), "王浩": (30, 0), "蘇澤峰": (24, 6)})
        self.assertEqual(first, "2026-04-20")

    def test_blank_leave_counts_as_zero_and_month_day_dates_take_the_title_year(self):
        cols, first = cyi_book.parse_attendance(att_words(["黃盈智", "王浩"], [5, 4], [None, 1], first="6月20日"), year="114")
        self.assertEqual((cols, first), ({"黃盈智": (5, 0), "王浩": (4, 1)}, "2025-06-20"))

    def test_inconsistent_totals_reject_the_whole_table(self):
        with self.assertRaisesRegex(ValueError, "出席＋請假不一致"):
            cyi_book.parse_attendance(att_words(["黃盈智", "王浩", "蘇澤峰"], [35, 35, 35], [0, 1, 17]))

    def test_name_character_off_every_column_rejects_the_table(self):
        words = att_words(["黃盈智", "王浩"], [5, 5], [0, 0]) + [(158, 130, "戴")]
        with self.assertRaisesRegex(ValueError, "對不到唯一一欄"):
            cyi_book.parse_attendance(words)

    def test_leave_number_without_a_column_rejects_the_table(self):
        words = att_words(["黃盈智", "王浩"], [5, 4], [0, 1]) + [(200, 720, "1")]
        with self.assertRaisesRegex(ValueError, "對不到唯一一欄"):
            cyi_book.parse_attendance(words)


PEOPLE = [("p1", "黃盈智", True), ("p2", "王浩", True), ("p3", "鄭光宏", False), ("p4", "蘇澤峰", True)]


def build(books, words):
    with tempfile.TemporaryDirectory() as tmp:
        conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
        for pid, name, cand in PEOPLE:
            upsert_person(conn, pid, name)
            upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "cyi_councilor", "district_id": "cyi-council-01"}, "https://u", "t")
            if cand:
                upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "cyi-council-01"}, "https://u", "t")
        logs = []
        with mock.patch.object(cyi_book, "page_words", lambda p0, name, page: words[page]):
            out = cyi_book.build(conn, books, logs.append)
    return out, logs


class TestCyiBuild(unittest.TestCase):
    def test_facts_go_to_candidates_only_and_unknown_columns_reject_the_table(self):
        att_page = "  議員出、缺席一覽表   1619\n   嘉義市議會第11屆第7次定期會議員出席表\n"
        bad_page = "  議員出、缺席一覽表   1617\n   嘉義市議會第11屆114年第3次臨時會議員出席表\n"
        text = oral_book([(1107, P9), (1108, P10)]) + "\f" + att_page + "\f" + bad_page
        words = {5: att_words(["黃盈智", "王浩", "鄭光宏"], [30, 29, 30], [0, 1, 0]),
                 6: att_words(["黃盈智", "王小明"], [5, 5], [0, 0], title="嘉義市議會第11屆114年第3次臨時會議員出席表", first="6月20日")}
        (ts, meetings, tables, gov, att), logs = build([(3462, "_admin/_upload/Announce/3462/file/下冊.pdf", "下冊.pdf", text)], words)
        k, d, url, date = gov["p1"][0]
        self.assertEqual((k, date, d["page"], d["printed_page"]), ("cyigov:7r-10:p1", "2026-05-04", 4, 1108))
        self.assertEqual(d["title"], "市政總質詢紀錄（第 10 次會議，本人發言自議事錄第 1108 頁起）")
        self.assertTrue(url.startswith("https://www.cycc.gov.tw/_admin/_upload/Announce/3462/file/%E4%B8%8B%E5%86%8A.pdf#page=4"))
        self.assertNotIn("p3", gov)  # 鄭光宏沒有參選
        self.assertEqual([t["session"] for t in tables], ["第11屆第7次定期會"])  # 鄭光宏在名錄（沒參選，不寫），王小明對不到
        self.assertTrue(any("對不到名錄的欄 王小明" in x for x in logs))
        k, d, url, date = att["p2"][0]
        self.assertEqual((k, d["meetings"], d["present"], d["leave"], date), ("cyiattend:7r:p2", 30, 29, 1, "2026-04-20"))
        self.assertTrue(url.endswith("#page=5"))
        self.assertNotIn("p4", att)  # 不在表上：不寫

    def test_slugs(self):
        self.assertEqual(cyi_book.slug("第11屆第7次定期會"), "7r")
        self.assertEqual(cyi_book.slug("第11屆114年第4次臨時會"), "114-4t")


if __name__ == "__main__":
    unittest.main()
