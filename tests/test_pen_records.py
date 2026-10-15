import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import pen_videos

STREAMS = "\n".join([
    "liIUFGNfLvs\t[1151006AM]第五審查委員會縣政總質詢",  # 說明欄沒有排定議員
    "TDRwZLNMM0U\t[1140520AM]第一、二審查委員會縣政總質詢",
    "4s8hXoBxUKU\t[1151001AM]宋昀芝議員、藍凱元副議長縣政總質詢",
    "bTpJrS3CXig\t[1150924AM]蘇育德議員縣政總質詢",
    "bTpJrS3CXig\t[1150924AM]蘇育德議員縣政總質詢",  # 重複列出只收一次
    "tHsXtGonHbc\t[1151006PM]審查議案",
    "FmWqKeHRMlc\t[1140515AM]莊光大議員、呂黃春金議員縣政總質詢",
    "lz_dPp64sq8\t[1140509AM]吳政杰議員、蘇育德議員縣政總質詢",
    "old00000001\t[1140428AM]蘇育德議員縣政總質詢",  # 收錄期間以前
    "dcA092PqLgk\t澎湖縣議會第19屆第04次定期會_藍凱元、陳佩真、宋昀芝縣政總質詢(1091123AM) 1/2",
    "pm000000001\t[1150924PM]王小明議員縣政總質詢",  # 名錄同名
])
DESC_TDR = ("第20屆第05次定期會第24次會議\n\n縣政總質詢\n\n第一審查委員會：\n09：00－09：20\u3000呂黃春金議員\n"
            "09：20－09：40\u3000陳佩真議員\n09：40－10：00\u3000召集人許育愷議員\n休息二十分鐘\n第二審查委員會\n"
            "10:40-11:00\u3000歐中慨議員\n11:00-11:20\u3000副召集人宋昀芝議員\n11:20-11:40\u3000藍凱元副議長\n\n議長總結\n"
            "11:40-12:00\u3000議長總結\n12:00-12:10\u3000宋昀芝、陳佩真\n")
DESC_LII = "第20屆第8次定期會第28次會議\n\n縣政總質詢\n09：00－10：00\u3000第五審查委員會\n10：20－11：20\u3000議長總結"
PLAYLISTS = "PLx8\t第20屆第8次定期會\nPLx5\t第20屆第05次定期會\nPLt\t第20屆第23次臨時會\n"


def new_conn(tmp, people):
    """people：[(person_id, name, 有 2026 candidacy, 任職起日)]，都是澎湖縣議員。"""
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand, since in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:pen:{pid}", pid, "office", {"office": "pen_councilor", "district_id": "pen-council-01"},
                    "https://u", "t", date=since)
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "pen-council-01"}, "https://u", "t")
    return conn


PEOPLE = [("p1", "蘇育德", True, "2022-12-25"), ("p2", "吳政杰", True, "2022-12-25"), ("p3", "呂黃春金", True, "2022-12-25"),
          ("p4", "宋昀芝", True, "2022-12-25"), ("p5", "藍凱元", False, "2022-12-25"), ("p8", "陳佩真", True, "2022-12-25"),
          ("p6", "王小明", True, "2022-12-25"), ("p7", "王小明", True, "2022-12-25")]


class TestPenTitles(unittest.TestCase):
    def test_single_and_two_named_councillors_with_roc_date(self):
        self.assertEqual(pen_videos.parse_title("[1150924AM]蘇育德議員縣政總質詢"),
                         {"date": "2026-09-24", "pm": False, "names": ["蘇育德"], "committee": None})
        self.assertEqual(pen_videos.parse_title("[1151001PM]宋昀芝議員、藍凱元副議長縣政總質詢"),
                         {"date": "2026-10-01", "pm": True, "names": ["宋昀芝", "藍凱元"], "committee": None})
        self.assertEqual(pen_videos.parse_title("[1140515AM]莊光大議員、呂黃春金議員縣政總質詢")["names"], ["莊光大", "呂黃春金"])

    def test_non_interpellation_titles_are_ignored(self):
        self.assertIsNone(pen_videos.parse_title("[1151006PM]審查議案"))
        self.assertIsNone(pen_videos.parse_title("澎湖縣議會第19屆第04次定期會_藍凱元、陳佩真、宋昀芝縣政總質詢(1091123AM) 1/2"))

    def test_committee_titles_defer_names_to_the_description(self):
        self.assertEqual(pen_videos.parse_title("[1151002AM]第一、二審查委員會縣政總質詢"),
                         {"date": "2026-10-02", "pm": False, "names": [], "committee": "第一、二審查委員會"})

    def test_titles_with_unrecognisable_name_parts_raise(self):
        with self.assertRaises(ValueError):
            pen_videos.parse_title("[1151002AM]蘇育德、吳政杰議員縣政總質詢")  # 每個片段都要有職稱，不猜


class TestPenDescriptions(unittest.TestCase):
    def test_slots_under_committee_headings_with_convener_prefix_and_both_colon_styles(self):
        logs = []
        slots = pen_videos.parse_description(DESC_TDR, logs.append)
        self.assertEqual([(s["committee"], s["start"], s["end"], s["name"]) for s in slots], [
            ("第一審查委員會", "09:00", "09:20", "呂黃春金"), ("第一審查委員會", "09:20", "09:40", "陳佩真"),
            ("第一審查委員會", "09:40", "10:00", "許育愷"), ("第二審查委員會", "10:40", "11:00", "歐中慨"),
            ("第二審查委員會", "11:00", "11:20", "宋昀芝"), ("第二審查委員會", "11:20", "11:40", "藍凱元")])
        # 議長總結不收也不吵；其他無法辨識的時段印 log，不猜
        self.assertEqual(len(logs), 1)
        self.assertIn("宋昀芝、陳佩真", logs[0])

    def test_description_without_named_slots_gives_nothing(self):
        logs = []
        self.assertEqual(pen_videos.parse_description(DESC_LII, logs.append), [])
        self.assertTrue(any("第五審查委員會" in s for s in logs))

    def test_slot_before_any_committee_heading_is_not_attributed(self):
        logs = []
        self.assertEqual(pen_videos.parse_description("09：00－09：20　陳佩真議員", logs.append), [])
        self.assertEqual(len(logs), 1)


class TestPenBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cache = Path(self.tmp) / "cache"
        cache.mkdir()
        (cache / "yt_streams.tsv").write_text(STREAMS, encoding="utf-8")
        (cache / "yt_playlists.tsv").write_text(PLAYLISTS, encoding="utf-8")
        (cache / "playlist_PLx8.tsv").write_text("4s8hXoBxUKU\tx\nbTpJrS3CXig\tx\n", encoding="utf-8")
        (cache / "playlist_PLx5.tsv").write_text("FmWqKeHRMlc\tx\nlz_dPp64sq8\tx\nTDRwZLNMM0U\tx\n", encoding="utf-8")
        (cache / "desc").mkdir()
        (cache / "desc" / "TDRwZLNMM0U.txt").write_text(DESC_TDR, encoding="utf-8")
        (cache / "desc" / "liIUFGNfLvs.txt").write_text(DESC_LII, encoding="utf-8")
        patcher = mock.patch.object(pen_videos, "CACHE", cache)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_items_are_named_interpellations_from_may_2025_with_session_from_playlists(self):
        logs = []
        items = pen_videos.load_items(logs.append)
        self.assertEqual([i["video_id"] for i in items],
                         ["TDRwZLNMM0U", "4s8hXoBxUKU", "bTpJrS3CXig", "FmWqKeHRMlc", "lz_dPp64sq8", "pm000000001"])
        self.assertEqual([i["nth"] for i in items], [5, 8, 8, 5, 5, None])
        self.assertEqual(items[0]["names"], ["呂黃春金", "陳佩真", "許育愷", "歐中慨", "宋昀芝", "藍凱元"])
        self.assertTrue(any("liIUFGNfLvs" in s and "沒有排定質詢議員" in s for s in logs))
        self.assertTrue(any("pm000000001" in s and "會期留空" in s for s in logs))

    def test_videos_go_to_each_named_candidate_whole_name_only(self):
        conn = new_conn(self.tmp, PEOPLE)
        logs = []
        ts, by_pid = pen_videos.build(conn, pen_videos.load_items(lambda s: None), logs.append)
        self.assertEqual({p: [v["video_id"] for v in vs] for p, vs in by_pid.items()},
                         {"p1": ["lz_dPp64sq8", "bTpJrS3CXig"], "p2": ["lz_dPp64sq8"], "p3": ["FmWqKeHRMlc", "TDRwZLNMM0U"],
                          "p4": ["TDRwZLNMM0U", "4s8hXoBxUKU"], "p8": ["TDRwZLNMM0U"]})
        # 藍凱元沒參選、王小明同名、莊光大沒有任職 fact、許育愷與歐中慨不在名錄：都不收
        self.assertTrue(any("莊光大 名錄沒有此人" in s for s in logs))
        self.assertTrue(any("王小明 名錄同名" in s for s in logs))
        self.assertTrue(any("許育愷 名錄沒有此人" in s for s in logs))

    def test_replacement_councillor_only_from_taking_office(self):
        conn = new_conn(self.tmp, [("p1", "蘇育德", True, "2025-06-01")])
        _, by_pid = pen_videos.build(conn, pen_videos.load_items(lambda s: None), lambda s: None)
        self.assertEqual([v["video_id"] for v in by_pid["p1"]], ["bTpJrS3CXig"])

    def test_write_marks_shared_videos_and_removes_stale_rows(self):
        conn = new_conn(self.tmp, PEOPLE)
        upsert_fact(conn, "penvideo:gone:p1", "p1", "interpellation", {}, "https://u", "t", date="2025-05-01")
        _, by_pid = pen_videos.build(conn, pen_videos.load_items(lambda s: None), lambda s: None)
        n, stale = pen_videos.write_videos(conn, by_pid, "2026-10-15T00:00:00Z")
        self.assertEqual((n, stale), (8, 1))
        row = conn.execute("SELECT date, source_url, data FROM fact WHERE fact_key = 'penvideo:FmWqKeHRMlc:p3'").fetchone()
        d = json.loads(row["data"])
        self.assertEqual((row["date"], row["source_url"]), ("2025-05-15", "https://www.youtube.com/watch?v=FmWqKeHRMlc"))
        self.assertEqual((d["councillors"], d["joint"], d["whole"], d["dept"], d["session"], d["seq"]),
                         (["莊光大", "呂黃春金"], True, True, "第5次定期會", "第20屆第5次定期會", 0))
        single = json.loads(conn.execute("SELECT data FROM fact WHERE fact_key = 'penvideo:bTpJrS3CXig:p1'").fetchone()["data"])
        self.assertEqual((single["joint"], single["group_size"], single["title"]), (False, 1, "縣政總質詢（上午）"))
        slot = json.loads(conn.execute("SELECT data FROM fact WHERE fact_key = 'penvideo:TDRwZLNMM0U:p4'").fetchone()["data"])
        self.assertEqual((slot["title"], slot["committee"], slot["slots"], slot["seq"]),
                         ("第二審查委員會縣政總質詢（上午）", "第二審查委員會", ["11:00–11:20"], 1100))
        self.assertNotIn("whole", slot)

    def test_same_day_order_is_half_day_then_scheduled_slot(self):
        v = {"pm": True, "slots": {"甲": [{"start": "09:40"}]}}
        self.assertEqual(pen_videos.seq_of(v, "甲"), 10940)
        self.assertEqual(pen_videos.seq_of({"pm": False, "slots": {}}, "乙"), 0)


if __name__ == "__main__":
    unittest.main()
