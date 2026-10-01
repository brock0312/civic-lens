import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from etl.db import open_db, upsert_person
from etl.sources import tcc_videos
from etl.sources.tcc_videos import parse_list, parse_segments, run, write_video

SAMPLE = json.loads((Path(__file__).parent / "fixtures" / "tcc_videos_sample.json").read_text(encoding="utf-8"))
GENERAL = "36f899ab-94ec-4102-bdd5-a55fa89cdd22"   # 市政總質詢，分段「第N組」
DEPT = "a1b99608-bad0-4b68-9bba-c7259e0dd700"      # 警政衛生部門質詢，分段「第N質詢組」
NO_SEG = "9f8c1e2f-8e8b-4f0b-b07c-12f94654e28b"    # 沒有分段
IDENTITY = {"徐立信": ("p1", "x"), "洪健益": ("p2", "x"), "劉耀仁": ("p3", "x")}


def new_conn(tmp):
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for name, (pid, _) in IDENTITY.items():
        upsert_person(conn, pid, name)
    return conn


def fake_get(path):
    if path == "/Front/Query/GetList":
        return SAMPLE["GetList"]
    endpoint, vid = path.rsplit("/", 1)[1].split("?id=")
    return SAMPLE["videos"][vid][endpoint]


class TestParse(unittest.TestCase):
    def test_parse_list_keeps_only_term14_oral_interpellations(self):
        videos = parse_list(SAMPLE["GetList"])
        self.assertEqual([v["video_id"] for v in videos], [GENERAL, DEPT, NO_SEG])
        self.assertEqual(videos[0], {
            "video_id": GENERAL, "date": "2026-09-11", "list_title": "第14屆第08次定期大會市政總質詢",
            "session": "第14屆第08次定期大會", "doc_type": "市政總質詢", "dept": None,
        })
        self.assertEqual((videos[1]["doc_type"], videos[1]["dept"]), ("部門質詢", "警政衛生"))

    def test_parse_list_rejects_unknown_title_format(self):
        item = {**SAMPLE["GetList"][0], "Title": "第14屆第01次臨時大會市政總質詢"}
        with self.assertRaises(ValueError):
            parse_list([item])

    def test_segment_named_group_n_is_seekable(self):
        segs = parse_segments(SAMPLE["videos"][GENERAL]["Segment_Read"])
        self.assertEqual([(s["group"], s["seekable"]) for s in segs], [(13, True), (14, True), (15, True)])
        self.assertEqual(segs[1]["councillors"], ["洪健益", "劉耀仁"])
        self.assertAlmostEqual(segs[1]["start_sec"], 3215.07, places=1)

    def test_segment_named_interpellation_group_n_is_not_seekable(self):
        segs = parse_segments(SAMPLE["videos"][DEPT]["Segment_Read"])
        self.assertEqual([(s["group"], s["seekable"]) for s in segs], [(7, False), (8, False), (9, False), (10, False)])

    def test_segment_name_trailing_newline_is_stripped(self):
        segs = parse_segments([{"Name": "第8組：侯漢廷\r\n", "VideoTime": 1.5}])
        self.assertEqual((segs[0]["councillors"], segs[0]["seekable"]), (["侯漢廷"], True))

    def test_duplicate_segment_of_same_group_keeps_earliest_start(self):
        segs = parse_segments([
            {"Name": "第1組：苗博雅,林亮君", "VideoTime": 648.98},
            {"Name": "第1組：苗博雅,林亮君", "VideoTime": 648.55},
            {"Name": "第2組：顏若芳", "VideoTime": 4084.9},
        ])
        self.assertEqual([(s["group"], s["start_sec"]) for s in segs], [(1, 648.55), (2, 4084.9)])

    def test_duplicate_group_with_different_members_raises(self):
        with self.assertRaises(ValueError):
            parse_segments([{"Name": "第1組：苗博雅", "VideoTime": 1}, {"Name": "第1組：林亮君", "VideoTime": 2}])


class TestWrite(unittest.TestCase):
    def test_same_group_writes_one_fact_per_mapped_councillor(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp)
            video = parse_list(SAMPLE["GetList"])[0]
            n = write_video(conn, video, parse_segments(SAMPLE["videos"][GENERAL]["Segment_Read"]), IDENTITY, "t")

            self.assertEqual(n, 3)  # 第15組侯漢廷沒有對照
            rows = {r["fact_key"]: r for r in conn.execute("SELECT * FROM fact")}
            self.assertEqual(set(rows), {f"ivideo:{GENERAL}:13:p1", f"ivideo:{GENERAL}:14:p2", f"ivideo:{GENERAL}:14:p3"})
            r = rows[f"ivideo:{GENERAL}:14:p2"]
            self.assertEqual((r["kind"], r["date"]), ("interpellation", "2026-09-11"))
            self.assertEqual(r["source_url"], f"https://tccvideo.tcc.gov.tw/Front/VideoContent/Index?id={GENERAL}&num=14")
            data = json.loads(r["data"])
            self.assertEqual(data["title"], "市政總質詢 第14組")
            self.assertEqual((data["group_size"], data["councillors"], data["seekable"], data["dept"]),
                             (2, ["洪健益", "劉耀仁"], True, None))

    def test_unseekable_group_links_to_video_without_num(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp)
            video = parse_list(SAMPLE["GetList"])[1]
            write_video(conn, video, parse_segments(SAMPLE["videos"][DEPT]["Segment_Read"]), IDENTITY, "t")

            r = conn.execute("SELECT * FROM fact").fetchone()
            self.assertEqual(r["fact_key"], f"ivideo:{DEPT}:8:p1")
            self.assertEqual(r["source_url"], f"https://tccvideo.tcc.gov.tw/Front/VideoContent/Index?id={DEPT}")
            self.assertEqual(json.loads(r["data"])["title"], "部門質詢（警政衛生）第8組")


class TestRun(unittest.TestCase):
    def _run(self, conn, get=fake_get):
        with mock.patch.object(tcc_videos, "load_identity", return_value=IDENTITY), \
             mock.patch.object(tcc_videos, "MIN_LIST_TOTAL", len(SAMPLE["GetList"])), \
             mock.patch.object(tcc_videos, "get", side_effect=get) as m:
            run(conn)
        return [c.args[0] for c in m.call_args_list]

    def test_video_without_segments_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp)
            self._run(conn)
            vids = {r[0] for r in conn.execute("SELECT json_extract(data, '$.video_id') FROM fact")}
            self.assertEqual(vids, {GENERAL, DEPT})

    def test_second_run_skips_videos_already_in_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp)
            self._run(conn)
            paths = self._run(conn)
            self.assertEqual(paths, ["/Front/Query/GetList",
                                     f"/Front/VideoContent/Read?id={NO_SEG}", f"/Front/VideoContent/Segment_Read?id={NO_SEG}"])

    def test_raises_when_getlist_shrinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp)
            with self.assertRaises(ValueError):
                self._run(conn, get=lambda path: SAMPLE["GetList"][:-1])


if __name__ == "__main__":
    unittest.main()
