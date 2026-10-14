import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import kee_videos


def card(href, title, when, session="第20屆第8次定期會", kind="市長施政總質詢"):
    """stream3.php 一張影片卡片的樣子（title 屬性尾巴帶「(另開新視窗)」，偶有 tab）。"""
    return (f' <a href="{href}" target="new" data-width="1080" title="{title}(另開新視窗)">\n'
            f'<div class="s19"><div class="s20"><div class="text1">\n            {when}<br/>\n            {session}<br/>\n'
            f'            {kind}<br/>\n            {title[:12]}...\n            </div></div></div></a>\n')


AK = "https://streamak0104vod.akamaized.net/"
LISTING = "<main id=\"main\">" + "".join([
    card(AK + "1151005Q_20_W0950_何淑萍.mp4", "何淑萍議員", "2026-10-05 09:50"),
    # 早期檔名沒有姓名；檔名日期誤植（11510020Q）時一律以卡片文字為準
    card(AK + "1120519Q_20_W1430.mp4", "何淑萍議員", "2023-05-19 14:30", "第20屆第1次定期會"),
    card(AK + "11510020Q_20_W1540_呂美玲.mp4", "呂美玲議員", "2026-10-02 15:40"),
    card(AK + "1150603Q_20_W1100_楊秀玉 .mp4", "楊秀玉副議長", "2025-06-03 11:00", "第20屆第5次定期會"),
    card(AK + "1151002Q_20_W1101_民進黨團聯合_施偉政、許睿慈.mp4", "民進黨團聯合_施偉政議員、許睿慈議員", "2026-10-02 11:00"),
    card(AK + "1141119Q_20_W0950_民進黨團聯.mp4", "民民進黨團聯合_張之豪議員,施偉政議員,張顥瀚議員", "2025-11-19 09:50", "第20屆第6次定期會"),
    card(AK + "1131118Q_20_W0950.mp4", "林旻勳議員暨跨黨派政團聯合_呂美玲議員,何淑萍議員", "2024-11-18 09:50", "第20屆第4次定期會"),
    card(AK + "1130603Q_20_W1430.mp4", "民進黨團聯合_施偉政議員(因本市北寧路發生重大坍方事件,民進黨團改以書面總質詢,請市府極力救災.)",
         "2024-06-03 14:30", "第20屆第3次定期會"),
    card(AK + "1120526Q_20_W0950.mp4", "王小明議員", "2023-05-26 09:50", "第20屆第1次定期會"),  # 名錄同名
]) + "</main>"


def new_conn(tmp, people):
    """people：[(person_id, name, 有 2026 candidacy, 任職起日)]，都是基隆市議員。"""
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand, since in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:kee:{pid}", pid, "office", {"office": "kee_councilor", "district_id": "kee-council-01"},
                    "https://u", "t", date=since)
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "kee-council-01"}, "https://u", "t")
    return conn


PEOPLE = [("p1", "何淑萍", True, "2022-12-25"), ("p2", "呂美玲", True, "2022-12-25"), ("p3", "施偉政", True, "2022-12-25"),
          ("p4", "許睿慈", False, "2022-12-25"), ("p5", "楊秀玉", True, "2022-12-25"), ("p6", "張之豪", True, "2022-12-25"),
          ("p7", "林旻勳", True, "2024-12-01"),  # 假設的遞補：上任前的影片不收
          ("p8", "王小明", True, "2022-12-25"), ("p9", "王小明", True, "2022-12-25")]


class TestKeeListing(unittest.TestCase):
    def test_listing_takes_date_and_names_from_card_text_not_filename(self):
        items = kee_videos.parse_listing(LISTING)
        self.assertEqual(len(items), 9)
        nameless = items[1]
        self.assertEqual((nameless["label"], nameless["date"], nameless["time"], nameless["nth"]),
                         ("何淑萍議員", "2023-05-19", "14:30", 1))
        self.assertEqual(items[2]["date"], "2026-10-02")  # 檔名 11510020 誤植
        self.assertEqual(items[2]["session"], "第20屆第8次定期會")
        # 網址百分比編碼（中文與檔名中的空白），才能直接當連結
        self.assertEqual(items[3]["url"], AK + "1150603Q_20_W1100_%E6%A5%8A%E7%A7%80%E7%8E%89%20.mp4")
        self.assertEqual(items[0]["kind"], "市長施政總質詢")

    def test_unknown_card_format_raises(self):
        with self.assertRaises(ValueError):
            kee_videos.parse_listing(card(AK + "x.mp4", "甲乙議員", "2026/10/05", "第20屆第8次定期會"))
        with self.assertRaises(ValueError):
            kee_videos.parse_listing(card(AK + "x.mp4", "甲乙議員", "2026-10-05 09:50", "第20屆第1次臨時會"))


class TestKeeLabels(unittest.TestCase):
    def test_single_councillor_and_deputy_speaker(self):
        self.assertEqual(kee_videos.parse_label("何淑萍議員"), {"names": ["何淑萍"], "joint": False, "caucus": ""})
        self.assertEqual(kee_videos.parse_label("楊秀玉副議長")["names"], ["楊秀玉"])

    def test_caucus_joint_rows_list_every_named_participant(self):
        self.assertEqual(kee_videos.parse_label("民進黨團聯合_施偉政議員、許睿慈議員"),
                         {"names": ["施偉政", "許睿慈"], "joint": True, "caucus": "民進黨團"})
        self.assertEqual(kee_videos.parse_label("民民進黨團聯合_張之豪議員,曾怡芳議員,吳驊珈議員")["names"], ["張之豪", "曾怡芳", "吳驊珈"])
        self.assertEqual(kee_videos.parse_label("\t民進黨團聯合_施偉政議員,吳驊珈議,張顥瀚議員\t")["names"], ["施偉政", "吳驊珈", "張顥瀚"])
        self.assertEqual(kee_videos.parse_label("民進黨團聯合_張之豪議員")["joint"], True)
        cross = kee_videos.parse_label("林旻勳議員暨跨黨派政團聯合_張耿輝議員,呂美玲議員")
        self.assertEqual(cross, {"names": ["林旻勳", "張耿輝", "呂美玲"], "joint": True, "caucus": "跨黨派政團"})
        self.assertEqual(kee_videos.parse_label("張芳麗議員暨跨黨派政團聯合-呂美玲議員")["names"], ["張芳麗", "呂美玲"])
        self.assertEqual(kee_videos.parse_label("呂美玲議員暨跨黨派政團聯合")["names"], ["呂美玲"])

    def test_written_notice_and_nameless_rows_are_not_guessed(self):
        with self.assertRaises(ValueError):
            kee_videos.parse_label("民進黨團聯合_陳宜議員,張之豪議員(因本市北寧路發生重大坍方事件,民進黨團改以書面總質詢,請市府極力救災.)")
        with self.assertRaises(ValueError):
            kee_videos.parse_label("民進黨團聯合")
        with self.assertRaises(ValueError):
            kee_videos.parse_label("民進黨團聯合_施偉政議員(另案說明文字很長)")


class TestKeeAssign(unittest.TestCase):
    def build(self, extra=""):
        items = kee_videos.parse_listing(LISTING + extra)
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, PEOPLE)
            ts, by_pid = kee_videos.build(conn, items, logs.append)
            n, stale = kee_videos.write_videos(conn, by_pid, "2026-10-14T00:00:00Z")
            facts = conn.execute("SELECT fact_key, person_id, date, data, source_url FROM fact WHERE fact_key LIKE 'keevideo:%'").fetchall()
        return by_pid, logs, facts

    def test_joint_rows_go_to_each_resolved_candidate_and_unknowns_are_logged(self):
        by_pid, logs, facts = self.build()
        self.assertEqual(len(by_pid["p1"]), 3)  # 個人 2 支＋跨黨派聯合 1 支
        self.assertEqual([v["date"] for v in by_pid["p3"]], ["2025-11-19", "2026-10-02"])  # 書面註記那場不收
        self.assertNotIn("p4", by_pid)  # 沒參選 2026
        self.assertNotIn("p8", by_pid)
        self.assertNotIn("p9", by_pid)  # 名錄同名
        self.assertNotIn("p7", by_pid)  # 上任前的影片
        self.assertTrue(any("張顥瀚：名錄沒有此人" in x for x in logs))
        self.assertTrue(any("王小明：名錄同名" in x for x in logs))
        self.assertTrue(any("書面" in x for x in logs))
        joint = [v for v in by_pid["p6"]][0]
        self.assertEqual(kee_videos.title_of(joint), "市長施政總質詢（民進黨團聯合質詢：張之豪、施偉政、張顥瀚）")
        self.assertEqual(kee_videos.title_of(by_pid["p5"][0]), "市長施政總質詢")

    def test_same_url_listed_twice_is_one_fact_per_person(self):
        dup = card(AK + "1151005Q_20_W0950_何淑萍.mp4", "何淑萍議員、何淑萍議員", "2026-10-05 09:50")
        by_pid, logs, facts = self.build(dup)
        self.assertEqual(len(by_pid["p1"]), 3)
        keys = [f["fact_key"] for f in facts]
        self.assertEqual(len(keys), len(set(keys)))
        f = next(f for f in facts if f["fact_key"] == "keevideo:1151005Q_20_W0950_何淑萍.mp4:p1")
        self.assertEqual(f["date"], "2026-10-05")
        self.assertTrue(f["source_url"].startswith(AK) and "何" not in f["source_url"])
        self.assertIn('"mp4": true', f["data"])
        self.assertIn('"clip": true', f["data"])


if __name__ == "__main__":
    unittest.main()
