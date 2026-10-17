import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import mia_book


def record(body_pages, session="7 次定期會", nth=19, agenda="縣政總質詢", roc="115 年 6 月 3 日", present=None):
    """pdftotext -layout 的樣子：第 1 頁表頭與出席欄，之後每頁以 \\f 分隔、頁底印頁碼。"""
    present = present or "李議長文斌 張副議長淑芬 周議員玉滿\n\n      翁議員杰 温議員俊勇 等 5 名(請假 0 名)"
    first = (f"      苗栗縣議會第 20 屆第 {session}\n\n       第 {nth} 次會議             {agenda}\n\n\n"
             f"時   間：民國 {roc}上午 9 時 45 分至 12 時 05 分\n\n地   點：本會議事廳\n\n"
             f"出席議員:{present}\n\n列   席:苗栗縣政府鍾縣長東錦率各局處長等人\n\n主   席:張副議長淑芬\n")
    pages = [first + body_pages[0]] + body_pages[1:]
    return "\f".join(p + f"\n                       {i + 1}\n" for i, p in enumerate(pages))


def turn(label, text):
    return f"{label}:\n\n    {text}\n\n"


GOV = record([
    turn("主席(張副議長淑芬)", "現在召開第 19 次會議，今天上午的議程是縣政總質詢，首先請周玉滿議員進行縣政總質詢。"),
    turn("周議員玉滿質詢", "縣長、各局處首長，" + "今天質詢的議題。" * 30)
    + turn("鍾縣長東錦答覆", "謝謝議員。"),
    turn("周議員玉滿質詢", "謝謝縣長。" * 10 + "主席(張副議長淑芬)繼續請溫俊勇議員和翁杰議員進行聯合總質詢。")
    + turn("温議員俊勇質詢", "主席、縣長，" + "本席關心交通。" * 30)
    + turn("翁議員杰質詢", "接著請教處長。" * 30),
    turn("禹耀東議員質詢", "我借一分鐘。" * 40)  # 沒有主席點名：不掛
    + turn("主席(張副議長淑芬)", "接著請李文斌議長進行縣政總質詢。")  # 點名之後沒有本人質詢標籤：不掛
    + turn("主席(張副議長淑芬)", "請張淑芬副議長進行縣政總質詢。")
    + turn("張副議長淑芬質詢", "我改為書面質詢。"),  # 只說一句：不算口頭質詢
])

PEOPLE = [("p1", "李文斌", True, "2022-12-25"), ("p2", "張淑芬", True, "2022-12-25"), ("p3", "周玉滿", True, "2022-12-25"),
          ("p4", "翁杰", True, "2022-12-25"), ("p5", "温俊勇", True, "2022-12-25"), ("p6", "鄭聚然", True, None),
          ("p7", "禹耀東", False, "2022-12-25")]


def new_conn(tmp):
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand, since in PEOPLE:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "mia_councilor", "district_id": "mia-council-01"},
                    "https://u", "t", date=since)
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "mia-council-01"}, "https://u", "t")
    return conn


def build(items, texts):
    with tempfile.TemporaryDirectory() as tmp:
        logs = []
        out = mia_book.build(new_conn(tmp), items, texts, logs.append, url=lambda cid, page=None: f"https://x/{cid}.pdf#page={page}")
    return out, logs


class TestMiaNames(unittest.TestCase):
    def test_title_inside_the_name_is_removed(self):
        self.assertEqual(mia_book.present_names(1, ["李議長文斌", "張副議長淑芬", "周議員玉滿", "翁議員杰"]),
                         ["李文斌", "張淑芬", "周玉滿", "翁杰"])
        self.assertEqual(mia_book.asker(1, "周議員玉滿質詢"), "周玉滿")
        self.assertEqual(mia_book.asker(1, "禹耀東議員質詢"), "禹耀東")
        self.assertEqual(mia_book.asker(1, "張副議長淑芬質詢"), "張淑芬")
        self.assertIsNone(mia_book.asker(1, "鍾縣長東錦答覆"))

    def test_names_run_together_are_split_on_titles(self):
        self.assertEqual(mia_book.present_names(1, ["張副議長淑芬鄭議員秋風"]), ["張淑芬", "鄭秋風"])

    def test_official_typos_are_fixed_only_for_the_reviewed_key(self):
        self.assertEqual(mia_book.present_names(1274, ["張副議長淑"]), ["張淑芬"])
        self.assertNotEqual(mia_book.present_names(1275, ["張副議長淑"]), ["張淑芬"])
        self.assertEqual(mia_book.asker(802, "農楊議員恭林質詢"), "楊恭林")
        self.assertIsNone(mia_book.asker(803, "農楊議員恭林質詢"))


class TestMiaGov(unittest.TestCase):
    def test_attaches_only_when_chair_call_and_own_label_agree(self):
        (ts, recs, meetings, gf, att), logs = build([(10, "第20屆第7次定期會-第19次會議")], {10: GOV})
        k, d, url, date = gf["p3"][0]
        self.assertEqual((k, d["page"], url, date), ("miagov:10:p3", 2, "https://x/10.pdf#page=2", "2026-06-03"))
        self.assertEqual(d["title"], "縣政總質詢紀錄（會議紀錄第 2 頁起）")
        self.assertNotIn("p7", gf)  # 沒參選，且沒有點名
        self.assertTrue(any("禹耀東 有質詢標籤 1 段但主席沒有點名" in x for x in logs))
        self.assertNotIn("p1", gf)
        self.assertTrue(any("主席點名 李文斌，之後沒有本人質詢標籤" in x for x in logs))
        self.assertNotIn("p2", gf)
        self.assertTrue(any("張淑芬 被點名後本人發言只有" in x for x in logs))

    def test_joint_interpellation_attaches_each_listed_member_with_the_group(self):
        (ts, recs, meetings, gf, att), logs = build([(10, "第20屆第7次定期會-第19次會議")], {10: GOV})
        for pid in ("p4", "p5"):
            d = gf[pid][0][1]
            self.assertEqual((d["councillors"], d["page"]), (["温俊勇", "翁杰"], 3))
            self.assertIn("聯合質詢：温俊勇、翁杰", d["title"])

    def test_link_page_is_first_own_label_even_when_called_only_after_a_break(self):
        text = record([
            turn("主席(張副議長淑芬)", "首先請周玉滿議員進行縣政總質詢。") + turn("周議員玉滿質詢", "本席先講。" * 40),
            turn("翁議員杰質詢", "我接著周議員的時間先講。" * 20),  # 還沒被點名就開講
            turn("主席(張副議長淑芬)", "現在休息十分鐘。"),
            turn("主席(張副議長淑芬)", "繼續開會，請翁杰議員進行縣政總質詢。") + turn("翁議員杰質詢", "繼續剛才的議題。" * 30),
        ])
        (ts, recs, meetings, gf, att), logs = build([(10, "第20屆第7次定期會-第19次會議")], {10: text})
        k, d, url, date = gf["p4"][0]
        self.assertEqual((d["page"], url), (2, "https://x/10.pdf#page=2"))

    def test_department_report_days_are_not_collected(self):
        text = GOV.replace("縣政總質詢\n", "交通工務處工作報告\n", 1)
        (ts, recs, meetings, gf, att), logs = build([(10, "第20屆第7次定期會-第3次會議")], {10: text})
        self.assertEqual(gf, {})

    def test_year_typo_is_kept_as_official_date_but_not_used_as_fact_date(self):
        items = [(10 + i, f"第20屆第7次定期會-第{15 + i}次會議") for i in range(3)]
        texts = {10: record(["x\n"], nth=15, roc="115 年 5 月 28 日"), 11: GOV.replace("115 年 6 月 3 日", "114 年 6 月 3 日"),
                 12: record(["x\n"], nth=17, roc="115 年 6 月 4 日")}
        (ts, recs, meetings, gf, att), logs = build(items, texts)
        k, d, url, date = gf["p3"][0]
        self.assertIsNone(date)
        self.assertTrue(d["no_date"])
        self.assertIn("官方記載日期 114-06-03", d["title"])


class TestMiaAttendance(unittest.TestCase):
    def meetings(self, specs):
        items, texts = [], {}
        for i, (roc, present) in enumerate(specs):
            items.append((100 + i, f"第20屆第7次定期會-第{i + 1}次會議"))
            texts[100 + i] = record(["x\n"], nth=i + 1, agenda="討論提案", roc=roc, present=present)
        return build(items, texts)

    def test_list_must_match_stated_count_and_every_name_must_resolve(self):
        (ts, recs, meetings, gf, att), logs = self.meetings([
            ("115 年 5 月 18 日", "李議長文斌 周議員玉滿 等 2 名(請假 3 名)"),
            ("115 年 5 月 19 日", "李議長文斌 周議員玉滿 等 3 名(請假 2 名)"),  # 人數不符
            ("115 年 5 月 20 日", "李議長文斌 周議員玉滿 王議員小明 等 3 名(請假 2 名)"),  # 對不到名錄
            ("115 年 5 月 21 日", "李議長文斌 周議員玉滿"),  # 沒有記載人數
        ])
        self.assertEqual([m["cid"] for m in meetings], [100])
        self.assertTrue(any("記載 3 名，名單讀到 2 個" in x for x in logs))
        self.assertTrue(any("對不到名錄的人 王小明" in x for x in logs))
        self.assertTrue(any("沒有記載人數" in x for x in logs))
        k, d, url, date = att["p3"][0]
        self.assertEqual((k, d["meetings"], d["present"], d["leave"], url, date),
                         ("miaattend:7r:p3", 1, 1, None, "https://x/100.pdf#page=None", "2026-05-18"))

    def test_former_member_is_accepted_only_before_the_cutoff(self):
        (ts, recs, meetings, gf, att), logs = self.meetings([
            ("115 年 7 月 20 日", "李議長文斌 徐議員永煌 等 2 名(請假 0 名)"),
            ("115 年 8 月 3 日", "李議長文斌 徐議員永煌 等 2 名(請假 0 名)"),
        ])
        self.assertEqual([m["cid"] for m in meetings], [100])
        self.assertTrue(any("115-08-03" in x and "對不到名錄的人 徐永煌" in x for x in logs))

    def test_meetings_before_named_lists_are_not_counted(self):
        (ts, recs, meetings, gf, att), logs = self.meetings([("114 年 3 月 16 日", "李議長文斌 周議員玉滿 等 2 名(請假 0 名)")])
        self.assertEqual(meetings, [])

    def test_replacement_counts_from_first_listed_meeting(self):
        (ts, recs, meetings, gf, att), logs = self.meetings([
            ("115 年 5 月 18 日", "李議長文斌 等 1 名(請假 0 名)"),
            ("115 年 5 月 19 日", "李議長文斌 鄭議員聚然 等 2 名(請假 0 名)"),
            ("115 年 5 月 20 日", "李議長文斌 等 1 名(請假 0 名)"),
        ])
        self.assertEqual([(d["meetings"], d["present"]) for _, d, _, _ in att["p6"]], [(2, 1)])
        self.assertEqual([(d["meetings"], d["present"]) for _, d, _, _ in att["p1"]], [(3, 3)])


if __name__ == "__main__":
    unittest.main()
