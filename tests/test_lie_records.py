import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import lie_videos

INDEX = """<div class="list_box"><span>第一選區 南竿鄉</span><ul class="box">
<li><a href="https://www.mtcc.gov.tw//ch/news/7176?clid=1">
  <div class="list_imgbox"><img src="x.jpg" alt="副議長\t 林明揚\t" /></div>
  <div class="name">副議長\t 林明揚\t</div></a></li>
<li><a href="https://www.mtcc.gov.tw//ch/news/7176?clid=7">
  <div class="list_imgbox"><img src="x.jpg" alt="議員 陳書建" /></div>
  <div class="name">議員 陳書建</div></a></li>
</ul></div>"""


def row(mcid, date, title):
    return (f"<div class='newsbox'><a href='https://www.mtcc.gov.tw//ch/Detail/7176?mcid={mcid}&webaid='   title='連至{title}'>"
            f"<div class='news_line'><div class='date'>{date}</div><div class='news_font'>{title}</div><div class='like'>48</div></div></a></div>")


LIST = ("<div class='newslist'>" + row(112242, "2026-06-22", "第八屆第七次定期大會縣政總質詢")
        + row(108527, "2025-11-28", "第八屆第六次定期大會縣長施政報告質詢")
        + row(100001, "2022-06-01", "第七屆第八次定期大會縣政總質詢")
        + "</div><div class='page'>目前在第 1 頁 / 共有<p> 41 </p>筆 | 5 頁 </div>")


def item(mcid, title, yt_titles, published="2026-06-22"):
    return {"mcid": mcid, "published": published, "title": title, "youtube": [f"v{i}" for i in range(len(yt_titles))],
            "yt_titles": yt_titles}


def new_conn(tmp, people):
    """people：[(person_id, name, 有 2026 candidacy, 任職起日)]，都是連江縣議員。"""
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand, since in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:lie:{pid}", pid, "office", {"office": "lie_councilor", "district_id": "lie-council-01"},
                    "https://u", "t", date=since)
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "lie-council-01"}, "https://u", "t")
    return conn


PEOPLE = [("p1", "陳書建", True, "2022-12-25"), ("p2", "林明揚", True, "2022-12-25"), ("p3", "張永江", False, "2022-12-25"),
          ("p4", "王小明", True, "2022-12-25"), ("p5", "王小明", True, "2022-12-25"), ("p6", "曹爾章", True, "2025-01-01")]


class TestLieParse(unittest.TestCase):
    def test_index_names_come_from_link_text_without_titles(self):
        self.assertEqual(lie_videos.parse_index(INDEX), [(1, "林明揚"), (7, "陳書建")])

    def test_list_rows_and_page_count(self):
        items, pages = lie_videos.parse_list(LIST)
        self.assertEqual(pages, 5)
        self.assertEqual([i["mcid"] for i in items], [112242, 108527, 100001])
        self.assertEqual(items[1], {"mcid": 108527, "published": "2025-11-28", "title": "第八屆第六次定期大會縣長施政報告質詢"})

    def test_title_keeps_only_term_eight_and_rejects_unknown_formats(self):
        self.assertEqual(lie_videos.parse_title("第八屆第七次定期大會縣政總質詢"),
                         {"nth": 7, "session": "第8屆第7次定期大會", "kind": "縣政總質詢"})
        self.assertEqual(lie_videos.parse_title("第八屆第六次定期大會縣長施政報告質詢")["kind"], "縣長施政報告質詢")
        self.assertEqual(lie_videos.parse_title("第八屆第六次定期大會總質詢")["kind"], "縣政總質詢")  # 官方漏寫「縣政」
        self.assertIsNone(lie_videos.parse_title("第七屆第八次定期大會縣政總質詢"))
        with self.assertRaises(ValueError):
            lie_videos.parse_title("第八屆第一次臨時大會專案報告")

    def test_detail_url_is_the_council_page_not_youtube(self):
        self.assertEqual(lie_videos.detail_url(112242), "https://www.mtcc.gov.tw/ch/Detail/7176?mcid=112242")


class TestLieTitleCheck(unittest.TestCase):
    NAMES = {"陳書建", "林明揚", "曹爾章"}

    def test_titles_naming_the_owner_pass(self):
        self.assertEqual(lie_videos.check_titles("陳書建", ["連江縣議會第8屆第7次定期大會總質詢-陳書建議員", None], self.NAMES), "ok")

    def test_titles_without_names_are_unverified(self):
        self.assertEqual(lie_videos.check_titles("陳書建", ["縣政總質詢", None], self.NAMES), "none")
        self.assertEqual(lie_videos.check_titles("陳書建", [], self.NAMES), "none")

    def test_titles_naming_someone_else_fail(self):
        self.assertEqual(lie_videos.check_titles("陳書建", ["總質詢-林明揚議員"], self.NAMES), "mismatch")
        self.assertEqual(lie_videos.check_titles("陳書建", ["總質詢-陳書建議員", "總質詢-曹爾章議員"], self.NAMES), "mismatch")


class TestLieBuild(unittest.TestCase):
    def build(self, councillors):
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, PEOPLE)
            ts, by_pid = lie_videos.build(conn, councillors, logs.append)
            n, stale = lie_videos.write_videos(conn, by_pid, "2026-10-15T00:00:00Z")
            facts = conn.execute("SELECT fact_key, person_id, date, source_url FROM fact WHERE fact_key LIKE 'lievideo:%'").fetchall()
        return by_pid, logs, [tuple(f) for f in facts]

    def test_items_go_to_the_resolved_candidate_and_wrong_or_ambiguous_ones_are_skipped(self):
        by_pid, logs, facts = self.build([
            {"clid": 7, "name": "陳書建", "items": [
                item(112242, "第八屆第七次定期大會縣政總質詢", ["總質詢-陳書建議員"]),
                item(108527, "第八屆第六次定期大會縣長施政報告質詢", [None], "2025-11-28"),
                item(108600, "第八屆第五次定期大會縣政總質詢", ["總質詢-林明揚議員"], "2025-06-15"),  # 標題點名別人
                item(108700, "第八屆第五次定期大會縣政總質詢", ["總質詢-陳書建議員"], "2025-06-15"),  # 也列在林明揚
            ]},
            {"clid": 1, "name": "林明揚", "items": [item(108700, "第八屆第五次定期大會縣政總質詢", [], "2025-06-15")]},
            {"clid": 3, "name": "張永江", "items": [item(108800, "第八屆第一次定期大會縣政總質詢", [])]},  # 沒參選
            {"clid": 9, "name": "王小明", "items": [item(108900, "第八屆第一次定期大會縣政總質詢", [])]},  # 名錄同名
            {"clid": 10, "name": "李大華", "items": [item(109000, "第八屆第一次定期大會縣政總質詢", [])]},  # 名錄沒有
            {"clid": 6, "name": "曹爾章", "items": [item(109100, "第八屆第一次定期大會縣政總質詢", [], "2023-11-18")]},  # 上任前
        ])
        self.assertEqual([v["mcid"] for v in by_pid["p1"]], [108527, 112242])  # 依會期排序
        self.assertEqual([v["verified"] for v in by_pid["p1"]], [False, True])
        self.assertEqual(set(by_pid), {"p1"})
        self.assertTrue(any("mcid=108600" in x and "點名其他議員" in x for x in logs))
        self.assertTrue(any("mcid=108700" in x and "多位議員" in x for x in logs))
        self.assertTrue(any("王小明：名錄同名" in x for x in logs))
        self.assertTrue(any("李大華：名錄沒有此人" in x for x in logs))
        self.assertIn(("lievideo:112242:p1", "p1", "2026-06-22", "https://www.mtcc.gov.tw/ch/Detail/7176?mcid=112242"), facts)
        self.assertEqual(len(facts), 2)


if __name__ == "__main__":
    unittest.main()
