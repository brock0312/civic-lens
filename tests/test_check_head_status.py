import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_head_status as c  # noqa: E402


def row(date, title, s="342329"):
    return (f'<tr><td><span>{date}</span></td><td><span>民政司</span></td><td><span>'
            f'<a href="News_Content.aspx?n=4&s={s}" title="{title}">{title}</a></span></td></tr>')


class CheckHeadStatus(unittest.TestCase):
    def test_ila_unchanged(self):
        self.assertIsNone(c.check_ila("<h2>代理縣長 林茂盛</h2><p>副縣長</p>"))

    def test_ila_acting_name_changed(self):
        self.assertIn("找不到", c.check_ila("<h2>代理縣長 王小明</h2>"))

    def test_ila_expected_text_missing(self):
        self.assertIn("找不到", c.check_ila("<h2>縣長 林姿妙</h2>"))

    def test_hsz_unchanged_and_acting_appears(self):
        self.assertIsNone(c.check_hsz("<p>市長簡介 姓名：高虹安</p>"))
        self.assertIn("代理", c.check_hsz("<p>代理市長 邱臣遠 高虹安</p>"))
        self.assertIn("找不到", c.check_hsz("<p>市長簡介</p>"))

    def test_news_hits_by_keyword_name_and_date(self):
        page = (row("115-10-05", "內政部停止縣長停止職務") + row("115-10-05", "王某某出席活動", "2")
                + row("115-10-05", "道路改善", "3") + row("115-09-01", "內政部停止縣長停止職務", "4"))
        hits = c.news_hits(page, ["王某某"], "2026-10-02")
        self.assertEqual([t for t, _ in hits], ["內政部停止縣長停止職務", "王某某出席活動"])
        self.assertTrue(hits[0][1].startswith("https://www.moi.gov.tw/News_Content.aspx"))


if __name__ == "__main__":
    unittest.main()
