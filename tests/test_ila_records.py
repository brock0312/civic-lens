import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import ila_videos


def row(vid, title, date, desc=None):
    font = '<font style="x">'
    return (f'<table><tr><td>{font}<strong>1</strong></font></td><td>'
            f'<a href="vod_show_mp4_play.asp?id={vid}&rule=1&film_spec=MP4">\n {font}<strong>{title}</strong></font></a>'
            f'{font}<br />\n 開會日期: </font>{font} {date} </font><br />\n'
            f'{font} 說明: </font>{font} {desc or title} </font></td></tr></table>')


LIST = (row(12939, "015林議員岳賢-第20屆第07次定期大會-第26次會議-縣長施政總質詢及答復", "2026/05/13")
        + row(10448, "015林議員岳賢-第19屆第08次大會-第14次會議-地政處、農業處業務報告", "2022/10/05")
        + "<td>&nbsp;共<font color='#A84A6B' size=1>2</font>頁</td>")


def r(vid, title, date, desc=None):
    return {"id": vid, "title": title, "date": date, "desc": desc or title}


def new_conn(tmp, people):
    """people：[(person_id, name, 有 2026 candidacy, 任職起日)]，都是宜蘭縣議員。"""
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand, since in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:ila:{pid}", pid, "office", {"office": "ila_councilor", "district_id": "ila-council-01"},
                    "https://u", "t", date=since)
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "ila-council-01"}, "https://u", "t")
    return conn


PEOPLE = [("p1", "林岳賢", True, "2022-12-25"), ("p2", "張勝德", True, "2022-12-25"),
          ("p3", "孫湯玉惠 aly saku", True, "2022-12-25"), ("p4", "林佩螢", True, "2022-12-25"),
          ("p5", "王小明", True, "2022-12-25"), ("p6", "王小明", True, "2022-12-25"), ("p7", "黃惠慈", True, "2025-04-01")]


class TestIlaParse(unittest.TestCase):
    def test_list_rows_dates_descriptions_and_page_count(self):
        rows, pages = ila_videos.parse_list(LIST)
        self.assertEqual(pages, 2)
        self.assertEqual(rows[0], r(12939, "015林議員岳賢-第20屆第07次定期大會-第26次會議-縣長施政總質詢及答復", "2026-05-13"))
        self.assertEqual([x["date"] for x in rows], ["2026-05-13", "2022-10-05"])

    def test_title_parses_roles_compound_surnames_and_joint_meetings(self):
        t = ila_videos.parse_title("015林議員岳賢-第20屆第07次定期大會-第26次會議-縣長施政總質詢及答復")
        self.assertEqual((t["seat"], t["name"], t["role"], t["session"], t["meeting"], t["topic"]),
                         ("015", "林岳賢", "議員", "第20屆第7次定期會", 26, "縣長施政總質詢及答復"))
        self.assertEqual(ila_videos.parse_title("007陳副議長漢鍾-第20屆第08次定期會-第15次會議-警察局業務報告")["name"], "陳漢鍾")
        self.assertEqual(ila_videos.parse_title("002孫湯議員玉惠-第20屆第08次定期會-第09次會議-民政處業務報告")["name"], "孫湯玉惠")
        j = ila_videos.parse_title("022呂議員惠卿-第20屆第02次大會-第28、29次會議-縣長施政總質詢及答復")
        self.assertEqual((j["session"], j["meeting"], j["meeting_label"]), ("第20屆第2次定期會", 28, "第28、29次會議"))
        self.assertEqual(ila_videos.parse_title("015林議員岳賢-第19屆第08次大會-第14次會議-地政處業務報告")["term"], 19)

    def test_ceremony_speeches_and_unknown_formats_are_not_clips(self):
        self.assertIsNone(ila_videos.parse_title("第20屆第08次定期會-張議長勝德開幕典禮致詞"))
        self.assertIsNone(ila_videos.parse_title("015林議員岳賢-第19屆第03次大會第31次會議業務質詢及答復【縣長施政總質詢及答復】"))

    def test_queries_cover_each_role_and_compound_surnames_for_long_names(self):
        self.assertEqual(ila_videos.queries("林岳賢"), ["林議員岳賢", "林副議長岳賢", "林議長岳賢"])
        self.assertIn("孫湯議員玉惠", ila_videos.queries("孫湯玉惠 aly saku"))

    def test_links_go_to_the_council_play_page(self):
        self.assertEqual(ila_videos.play_url(12939),
                         "https://mod.ilcc.gov.tw/mod/front2016/vod_show_mp4_play.asp?id=12939&rule=1&film_spec=MP4")


class TestIlaBuild(unittest.TestCase):
    def build(self, listings):
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, PEOPLE)
            ts, by_pid = ila_videos.build(conn, listings, logs.append)
            n, stale = ila_videos.write_videos(conn, by_pid, "2026-10-15T00:00:00Z")
            facts = {f[0]: tuple(f[1:]) for f in conn.execute(
                "SELECT fact_key, person_id, date, source_url, json_extract(data, '$.seq') FROM fact WHERE fact_key LIKE 'ilavideo:%'")}
        return by_pid, logs, facts

    def test_clips_go_only_to_the_councillor_named_in_title_and_description(self):
        by_pid, logs, facts = self.build({
            "林議員岳賢": [
                r(12939, "015林議員岳賢-第20屆第07次定期大會-第26次會議-縣長施政總質詢及答復", "2026-05-13"),
                r(12601, "015林議員岳賢-第20屆第06次大會-第27次會議-縣長施政總質詢及答復", "2025-11-20"),
                r(12605, "015林議員岳賢-第20屆第06次大會-第28次會議-縣長施政總質詢及答復", "2025-11-20"),
                r(12000, "015林議員岳賢-第20屆第05次大會-第10次會議-警察局業務報告", "2025-05-01",
                  desc="004林議員佩螢-第20屆第05次大會-第10次會議-警察局業務報告"),  # 說明欄是別人
                r(10448, "015林議員岳賢-第19屆第08次大會-第14次會議-地政處業務報告", "2022-12-30"),  # 第 19 屆
                r(12100, "004林議員佩螢-第20屆第05次大會-第11次會議-社會處業務報告", "2025-05-05"),  # 查詢撈到別人
            ],
            "張議長勝德": [
                r(12996, "第20屆第08次定期會-張議長勝德開幕典禮致詞", "2026-10-01"),
                r(11583, "029張議長勝德-第20屆第03次大會-第30次會議-縣長施政總質詢及答復", "2024-05-20"),
            ],
            "孫湯議員玉惠": [r(13068, "002孫湯議員玉惠-第20屆第08次定期會-第09次會議-民政處業務報告", "2026-10-07")],
            "林議員佩螢": [r(12098, "010沈議員信雄螢-第20屆第05次大會-第11次會議-社會處業務報告", "2025-05-05")],  # 名錄沒有
            "王議員小明": [r(11001, "001王議員小明-第20屆第02次大會-第05次會議-農業處業務報告", "2023-11-03")],  # 名錄同名
            "黃議員惠慈": [r(12010, "029黃議員惠慈-第20屆第05次大會-第04次會議-教育處業務報告", "2025-04-29"),
                       r(11000, "029黃議員惠慈-第20屆第02次大會-第04次會議-教育處業務報告", "2023-11-01")],  # 上任前
        })
        self.assertEqual([v["id"] for v in by_pid["p1"]], [12601, 12605, 12939])
        self.assertEqual([v["id"] for v in by_pid["p2"]], [11583])
        self.assertEqual([v["id"] for v in by_pid["p3"]], [13068])
        self.assertEqual([v["id"] for v in by_pid["p7"]], [12010])
        self.assertEqual(set(by_pid), {"p1", "p2", "p3", "p7"})
        self.assertTrue(any("id=12000" in x and "說明欄" in x for x in logs))
        self.assertTrue(any("id=12100" in x and "林佩螢" in x for x in logs))
        self.assertTrue(any("id=12996" in x and "格式不明" in x for x in logs))
        self.assertTrue(any("id=12098" in x and "名錄沒有此人" in x for x in logs))
        self.assertTrue(any("王小明" in x and "名錄同名" in x for x in logs))
        self.assertEqual(facts["ilavideo:12939:p1"],
                         ("p1", "2026-05-13", ila_videos.play_url(12939), 726))
        self.assertEqual(facts["ilavideo:12605:p1"][3], 628)  # 同日依會議次序
        self.assertEqual(len(facts), 6)

    def test_rerun_deletes_clips_no_longer_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, PEOPLE)
            first = {"林議員岳賢": [r(12939, "015林議員岳賢-第20屆第07次定期大會-第26次會議-縣長施政總質詢及答復", "2026-05-13")]}
            ila_videos.write_videos(conn, ila_videos.build(conn, first, lambda _: None)[1], "t")
            self.assertEqual(ila_videos.write_videos(conn, {}, "t"), (0, 1))


if __name__ == "__main__":
    unittest.main()
