import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import khh_videos
from etl.sources.khh_videos import match_members, parse_search, parse_title, targets

SRC = "202609KCC0408R1150923143208VIDEOmp4"


def item(title, source=SRC, gid="80", start="1701", name="邱俊憲", date=None):
    return {"title": title, "source": f"{source}?start={start}", "owner_group": gid, "in": start, "name": name,
            "date": date or title[:9]}


DEPT_TITLE = "115-09-23 14:32:08 第4屆第8次定期會 警消衛環部門業務報告與質詢"


class TestParseTitle(unittest.TestCase):
    def test_department_interpellation(self):
        self.assertEqual(parse_title(DEPT_TITLE), {
            "session": "第4屆第8次定期會", "doc_type": "部門質詢", "dept": "警消衛環", "title": "部門質詢（警消衛環）",
            "term": 4})

    def test_chinese_numerals_and_general_interpellation(self):
        m = parse_title("112-05-30 09:00:00 第四屆第一次定期會 市政總質詢")
        self.assertEqual((m["session"], m["doc_type"], m["dept"]), ("第4屆第1次定期會", "市政總質詢", None))
        m = parse_title("115-09-01 09:00:00 第4屆第8次定期會 市長施政報告與質詢")
        self.assertEqual(m["doc_type"], "施政報告質詢")

    def test_abbreviated_city_planning_committee_is_normalised(self):
        m = parse_title("112-11-01 10:55:52 第四屆第二次定期會 都委員會業務報告與質詢")
        self.assertEqual(m["dept"], "都市計畫委員會")

    def test_readings_are_not_interpellations(self):
        self.assertIsNone(parse_title("115-08-04 10:00:00 第四屆第六次臨時會 二、三讀會"))

    def test_unknown_interpellation_format_raises(self):
        with self.assertRaises(ValueError):
            parse_title("115-09-23 14:32:08 第4屆第8次定期會 質詢時間")


class TestParseSearch(unittest.TestCase):
    def test_one_row_per_video_preferring_the_councillor_channel(self):
        items = [item(DEPT_TITLE, gid="2"), item(DEPT_TITLE, gid="80")]
        got = parse_search(items, "邱俊憲", "80")
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["gid"], got[0]["start_sec"], got[0]["date"]), ("80", 1701, "2026-09-23"))
        self.assertEqual(khh_videos.video_url(got[0]), f"https://ivod.kcc.gov.tw/watch/80/{SRC}?start=1701")

    def test_duplicate_marks_keep_the_earliest_start(self):
        items = [item(DEPT_TITLE, start="2864"), item(DEPT_TITLE, start="1701")]
        self.assertEqual([v["start_sec"] for v in parse_search(items, "邱俊憲", "80")], [1701])

    def test_falls_back_to_council_channel_when_councillor_copy_is_missing(self):
        self.assertEqual(parse_search([item(DEPT_TITLE, gid="2")], "邱俊憲", "80")[0]["gid"], "2")

    def test_filters_other_speakers_previous_term_and_readings(self):
        items = [
            item(DEPT_TITLE, name="邱俊"),  # 搜尋可能是部分比對
            item("111-10-12 10:51:50 第三屆第八次定期會 教育部門業務報告與質詢", source="old"),
            item("115-08-04 10:00:00 第四屆第六次臨時會 二、三讀會", source="read"),
        ]
        self.assertEqual(parse_search(items, "邱俊憲", "80"), [])


def new_conn(tmp):
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, district, cand in [("p1", "邱俊憲", "khh-council-05", True), ("p2", "康裕成", "khh-council-07", False),
                                      ("p3", "高忠德 Takiludun．Anu", "khh-council-14", True)]:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "khh_councilor", "district_id": district},
                    "https://u", "t", date="2022-12-25")
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": district}, "https://u", "t")
    upsert_person(conn, "p4", "陳其邁")
    upsert_fact(conn, "cand:p4", "p4", "candidacy", {"district_id": "khh-mayor"}, "https://u", "t")
    return conn


MEMBERS = [{"gid": "80", "title": "邱俊憲議員", "regionName": "第05選區"},
           {"gid": "33", "title": "康裕成議長", "regionName": "第07選區"},
           {"gid": "135", "title": "高忠德議員", "regionName": "第14選區"}]


class TestRun(unittest.TestCase):
    def test_targets_are_only_kaohsiung_councillors_running_in_2026(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp)
            self.assertEqual([t["person_id"] for t in targets(conn)], ["p1", "p3"])
            self.assertEqual(match_members(targets(conn), MEMBERS), {"p1": ("邱俊憲", "80"), "p3": ("高忠德", "135")})

    def test_unmatched_member_raises(self):
        with self.assertRaises(ValueError):
            match_members([{"person_id": "p9", "name": "邱俊憲", "district_n": 6}], MEMBERS)

    def test_run_writes_deep_linked_facts_once(self):
        searches = {"邱俊憲": [item(DEPT_TITLE)], "高忠德": []}
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp)
            cache = Path(tmp) / "cache"
            cache.mkdir()
            (cache / "members.json").write_text(json.dumps(MEMBERS), encoding="utf-8")
            with mock.patch.object(khh_videos, "CACHE", cache), \
                    mock.patch.object(khh_videos, "fetch_member", side_effect=lambda n, g, full=False: searches[n]), \
                    mock.patch.object(khh_videos, "now_utc", side_effect=["T1", "T2"]):
                khh_videos.run(conn)
                khh_videos.run(conn)
            rows = conn.execute("SELECT fact_key, person_id, kind, date, data, source_url, fetched_at FROM fact "
                                "WHERE fact_key LIKE 'kvideo:%'").fetchall()
            self.assertEqual(len(rows), 1)
            r = rows[0]
            self.assertEqual((r["fact_key"], r["person_id"], r["kind"], r["date"], r["fetched_at"]),
                             (f"kvideo:{SRC}:p1", "p1", "interpellation", "2026-09-23", "T1"))
            self.assertEqual(r["source_url"], f"https://ivod.kcc.gov.tw/watch/80/{SRC}?start=1701")
            d = json.loads(r["data"])
            self.assertEqual((d["video_id"], d["dept"], d["start_sec"], d["seekable"], d["group_size"]),
                             (SRC, "警消衛環", 1701, True, 1))


class TestFetchMember(unittest.TestCase):
    def test_incremental_fetch_asks_for_recent_dates_and_merges(self):
        import datetime
        old = item(DEPT_TITLE, source="A")
        new = item(DEPT_TITLE, source="B")
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / "search_80.json").write_text(json.dumps({"through": "2026-09-30", "items": [old]}), encoding="utf-8")
            with mock.patch.object(khh_videos, "CACHE", cache), \
                    mock.patch.object(khh_videos, "post", return_value=[new]) as post:
                got = khh_videos.fetch_member("邱俊憲", "80", today=datetime.date(2026, 10, 3))
            form = post.call_args[0][1]
            self.assertEqual((form["dateRange[start]"], form["dateRange[end]"]), ("2026-08-01", "2026-10-03"))
            self.assertEqual([i["source"].split("?")[0] for i in got], ["A", "B"])
            self.assertEqual(json.loads((cache / "search_80.json").read_text())["through"], "2026-10-03")


if __name__ == "__main__":
    unittest.main()
