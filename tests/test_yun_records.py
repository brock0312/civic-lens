import tempfile
import unittest
from pathlib import Path
from unittest import mock

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import yun_videos


def item(vid, n):
    return (f"<div id='prj_{vid}' class='box box-solid know myMOUSE col-sm-3'><p id='know_text_{n}'>x</p></div>"
            f"<div id='prj_{vid}' class='list'></div>")  # 頁面上每支影片出現兩次（方塊與清單檢視）


def search(ids, total=None):
    return (f'<a style="font-size: 24px;">總計({len(ids) if total is None else total})</a>'
            + "".join(item(v, i) for i, v in enumerate(ids)))


def speaker(name, t):
    return (f"<p id='know_text_0'style='margin-left: 4.5px'  class='know_title' data-toggle='tooltip' title='{name}'>{name}</p>"
            f"<p class='time' style='margin-left: 4.5px' id='know_time_0' >{t}</p></div>")


def play(title, stamp, speakers):
    return (f'<div class="col-sm-12" id="video_title">\n    <font style="text-align: left;">\n  {title}</font>\n\n\n'
            f'    <font style="float:right;" >{stamp}</font>\n    </div>'
            + "".join(speaker(n, t) for n, t in speakers))


def p(title, day, seq, speakers, session=""):
    return {"title": title, "date": day, "seq": seq, "session": session, "speakers": speakers}


def new_conn(tmp, people):
    """people：[(person_id, name, 有 2026 candidacy, 任職起日)]，都是雲林縣議員。"""
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand, since in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:yun:{pid}", pid, "office", {"office": "yun_councilor", "district_id": "yun-council-01"},
                    "https://u", "t", date=since)
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "yun-council-01"}, "https://u", "t")
    return conn


PEOPLE = [("p1", "江文登", True, "2022-12-25"), ("p2", "王又民", False, "2022-12-25"), ("p3", "黃凱", True, "2022-12-25"),
          ("p4", "王小明", True, "2022-12-25"), ("p5", "王小明", True, "2022-12-25"), ("p6", "林新任", True, "2026-03-01")]


class TestYunParse(unittest.TestCase):
    def test_search_lists_each_video_once_in_page_order(self):
        self.assertEqual(yun_videos.parse_search(search([24184, 24171, 6507])), [24184, 24171, 6507])
        self.assertEqual(yun_videos.parse_search(search([])), [])

    def test_search_with_more_results_than_listed_raises(self):
        with self.assertRaises(ValueError):
            yun_videos.parse_search(search([24184], total=60))

    def test_play_page_gives_title_recording_time_session_and_every_speaker_segment(self):
        got = yun_videos.parse_play(play("115.9.30第20屆第8次定期會-縣政總質詢16", "2026-09-30T09:06:30+08:00",
                                         [("簡慈坊", "00:01:41"), ("江文登", "00:50:08"), ("江文登", "01:27:15")]))
        self.assertEqual(got, p("115.9.30第20屆第8次定期會-縣政總質詢16", "2026-09-30", 90630,
                                [("簡慈坊", "00:01:41"), ("江文登", "00:50:08"), ("江文登", "01:27:15")], "第8次定期會"))
        odd = yun_videos.parse_play(play("115.8.3雲林縣議會第20屆第21.22.23次臨時會", "2025-05-25 04:11:00", []))
        self.assertEqual((odd["date"], odd["seq"], odd["session"]), ("2025-05-25", 41100, "第21.22.23次臨時會"))
        self.assertIsNone(yun_videos.parse_play("<html>維護中</html>"))

    def test_links_go_to_the_council_play_page_and_search_by_speaker(self):
        self.assertEqual(yun_videos.play_url(24171), "http://msr.ylcc.gov.tw/portal/temp_3_G.php?id=24171")
        self.assertIn("group=5", yun_videos.search_url("江文登"))
        self.assertIn("S_d=2025-05-01", yun_videos.search_url("江文登"))


class TestYunBuild(unittest.TestCase):
    def build(self, searches, plays):
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, PEOPLE)
            ts, by_pid = yun_videos.build(conn, searches, plays, logs.append)
            yun_videos.write_videos(conn, by_pid, "2026-10-15T00:00:00Z")
            facts = {f[0]: tuple(f[1:]) for f in conn.execute(
                "SELECT fact_key, person_id, date, source_url, json_extract(data, '$.seq'), json_extract(data, '$.starts') "
                "FROM fact WHERE fact_key LIKE 'yunvideo:%'")}
        return by_pid, logs, facts

    def test_procedural_meetings_are_not_listed_even_when_the_councillor_speaks(self):
        plays = {1: p("第8次定期會-第2次程序委員會", "2026-09-29", 90000, [("江文登", "00:05:00")]),
                 2: p("第4次定期會-(閉會)", "2026-06-01", 90000, [("江文登", "00:05:00")]),
                 3: p("第8次定期會-縣政總質詢3", "2026-09-30", 90000, [("江文登", "00:10:00")])}
        by_pid, _, _ = self.build({"江文登": [1, 2, 3]}, plays)
        self.assertEqual([v["id"] for v in by_pid["p1"]], [3])

    def test_videos_go_only_to_councillors_named_in_the_speaker_list_with_all_their_start_times(self):
        plays = {
            1: p("縣政總質詢16", "2026-09-30", 90630, [("江文登", "01:27:15"), ("王又民", "00:23:55"), ("江文登", "00:50:08")]),
            2: p("縣政總質詢13", "2026-09-30", 140000, [("黃凱", "00:10:00"), ("江文登", "00:30:00")]),
            3: p("第2次臨時會-建設委員會", "2026-09-29", 90000, [("黃凱", "00:05:00")]),  # 查詢撈到、清單沒有江文登
            4: p("第4次定期會", "2025-04-30", 90000, [("江文登", "00:01:00")]),  # 2025-05 以前
            5: p("臨時會", "2026-02-01", 90000, [("林新任", "00:01:00"), ("黃凱君", "00:02:00")]),  # 林新任上任前
            6: p("臨時會", "2026-03-02", 90000, [("林新任", "00:01:00"), ("王小明", "00:03:00")]),
            7: None,
        }
        by_pid, logs, facts = self.build(
            {"江文登": [1, 2, 3, 4], "黃凱": [2, 3, 5, 7], "林新任": [5, 6], "王小明": [6]}, plays)
        self.assertEqual([v["id"] for v in by_pid["p1"]], [1, 2])
        self.assertEqual(by_pid["p1"][0]["starts"], ["00:50:08", "01:27:15"])
        self.assertEqual([v["id"] for v in by_pid["p3"]], [3, 2])  # 黃凱君不是黃凱
        self.assertEqual([v["id"] for v in by_pid["p6"]], [6])
        self.assertEqual(set(by_pid), {"p1", "p3", "p6"})  # 王又民沒參選；王小明名錄同名
        self.assertTrue(any("id=3" in x and "沒有此人" in x for x in logs))
        self.assertTrue(any("黃凱君" in x and "名錄沒有此人" in x for x in logs))
        self.assertTrue(any("王小明" in x and "名錄同名" in x for x in logs))
        self.assertTrue(any("id=7" in x and "格式不明" in x for x in logs))
        self.assertEqual(facts["yunvideo:1:p1"],
                         ("p1", "2026-09-30", yun_videos.play_url(1), 90630, '["00:50:08","01:27:15"]'))
        self.assertEqual(facts["yunvideo:2:p1"][3], 140000)  # 同日依錄影時刻
        self.assertEqual(len(facts), 5)

    def test_rerun_deletes_videos_no_longer_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, PEOPLE)
            plays = {1: p("縣政總質詢16", "2026-09-30", 90630, [("江文登", "00:50:08")])}
            yun_videos.write_videos(conn, yun_videos.build(conn, {"江文登": [1]}, plays, lambda _: None)[1], "t")
            self.assertEqual(yun_videos.write_videos(conn, {}, "t"), (0, 1))

    def test_name_fix_attaches_misprinted_speaker_only_on_listed_videos(self):
        fix = {(8, "江文燈"): "江文登"}
        plays = {8: p("第5次定期會-教育委員會", "2025-05-16", 140000, [("江文燈", "00:03:41"), ("黃凱", "00:05:49")]),
                 9: p("第5次定期會-民政委員會", "2025-05-16", 150000, [("江文燈", "00:24:05")])}
        with mock.patch.object(yun_videos, "NAME_FIX", fix):
            by_pid, logs, facts = self.build({"江文登": [], "黃凱": [8]}, plays)  # 本人查詢撈不到誤植的影片
        self.assertEqual([(v["id"], v["starts"]) for v in by_pid["p1"]], [(8, ["00:03:41"])])
        self.assertEqual(set(facts), {"yunvideo:8:p1", "yunvideo:8:p3"})
        self.assertEqual([x for x in logs if "江文燈" in x], ["yun_videos：發言議員「江文燈」名錄沒有此人，不收"])  # id=9 沒列，照舊不收

    def test_load_reads_play_pages_of_name_fix_videos(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(yun_videos, "CACHE", Path(tmp)), \
                mock.patch.object(yun_videos, "NAME_FIX", {(2, "江文燈"): "江文登"}):
            (Path(tmp) / "search").mkdir()
            (Path(tmp) / "play").mkdir()
            (Path(tmp) / "search" / "江文登.html").write_text(search([]), encoding="utf-8")
            with self.assertRaises(ValueError):
                yun_videos.load(["江文登"])
            (Path(tmp) / "play" / "2.html").write_text(play("縣政總質詢", "2025-06-12T09:02:01+08:00", []), encoding="utf-8")
            self.assertEqual(yun_videos.load(["江文登"])[1][2]["date"], "2025-06-12")

    def test_load_refuses_to_build_without_every_cached_search(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(yun_videos, "CACHE", Path(tmp)), \
                mock.patch.object(yun_videos, "NAME_FIX", {}):
            (Path(tmp) / "search").mkdir()
            (Path(tmp) / "play").mkdir()
            (Path(tmp) / "search" / "江文登.html").write_text(search([1]), encoding="utf-8")
            (Path(tmp) / "play" / "1.html").write_text(play("縣政總質詢16", "2026-09-30T09:06:30+08:00", []), encoding="utf-8")
            searches, plays = yun_videos.load(["江文登"])
            self.assertEqual((searches, plays[1]["date"]), ({"江文登": [1]}, "2026-09-30"))
            with self.assertRaises(ValueError):
                yun_videos.load(["江文登", "黃凱"])


if __name__ == "__main__":
    unittest.main()
