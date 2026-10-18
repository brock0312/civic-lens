import unittest

from etl.sources import nan_minutes as nm


def page(body, when="時間：中華民國 114 年 6 月 2 日（星期二）上午 10 時"):
    return f"第 7 次會議\n{when}\n出席：\n （如簽到簿）\n主席：議 員 簡千翔\n{body}\n散會：下午 12 時 05 分"


class ParsePages(unittest.TestCase):
    def test_joint_with_line_break_and_romanized_name(self):
        p = page("二、縣政總質詢\n 洪明科議員、林芳伃議員、蔡宗智議員、石慶龍 Rungquan‧Lhkatafatu 議員\n"
                 " 全文才議員、林儒暘議員、莊士傑議員、簡千翔議員\n 等 8 位議員聯合質詢。\n三、議員建議事項：如附件。")
        got = nm.parse_pages([p])
        self.assertEqual(got[0]["names"][3:5], ["石慶龍", "全文才"])
        self.assertEqual((got[0]["date"], got[0]["meeting"], len(got[0]["names"])), ("2025-06-02", 7, 8))

    def test_numbered_item_and_missing_title_suffix(self):
        got = nm.parse_pages([page("二、縣政總質詢：\n(一)甲乙丙、丁戊己等 2 位議員聯合質詢。\n(二)庚辛議員質詢。")])
        self.assertEqual(got[0]["names"], ["甲乙丙", "丁戊己"])

    def test_count_mismatch_and_other_formats_not_taken(self):
        logs = []
        self.assertEqual(nm.parse_pages([page("二、縣政總質詢\n 甲乙丙議員、丁戊己議員等 3 位議員聯合質詢。")], logs.append), [])
        self.assertEqual(nm.parse_pages([page("二、縣政總質詢：\n(一)甲乙丙議員、丁戊己議員\n 共同聯合質詢。")], logs.append), [])
        self.assertEqual(len(logs), 2)

    def test_not_a_minutes_page(self):
        self.assertEqual(nm.parse_pages(["縣政總質詢由甲乙丙議員、丁戊己議員等 2 位議員聯合質詢。"]), [])

    def test_book_session(self):
        self.assertEqual(nm.book_session("目 錄\n南投縣議會第二十屆第五次定期會議事錄\n"), "第20屆第5次定期會")


if __name__ == "__main__":
    unittest.main()
