import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import tnn_videos, txg_videos


def txg_row(title, date, ano=None):
    link = f'<a href="index.asp?url=22&cno=24&ano={ano}&pageno=1" target="_top">{title}</a>' if ano else title
    return (f'<td valign="top" height="35" class="link01">{link}</td>\n<td valign="top">x</td>\n'
            f'<td valign="top" nowrap="nowrap">{date}</td>')


def txg_page(rows, current="14849", last=32):
    pager = (f'<td><a href="index.asp?url=22&cno=24&ano={current}&PageNo=1" target="_top">最前頁</a>｜</td>'
             f'<td>｜<a href="index.asp?url=22&cno=24&ano={current}&PageNo={last}" target="_top">最末頁</a></td>')
    return "\n".join(rows) + pager


TXG_JOINT = "第4屆第8次定期會 市政總質詢(陳俞融、陳淑華等議員聯合質詢)"
TXG_DEPT = "第4屆第8次定期會 業務質詢：都發建設水利部分"
TXG_OLD = "第3屆第8次定期會 業務質詢：民政部分"

TXG_MEMBERS = ('<a href="index.asp?url=22&cno=24" target="_top"><font color="blue">陳淑華</font></a>'
               '<a href="index.asp?url=22&cno=85" target="_top"><font color="blue">楊啓邦</font></a>'
               '<td width="15%" height="35"><font color="blue">張清照</font></td>')


def tnn_block(header, vid, caption):
    return (f'<thead><tr><th colspan="3">{header}</th></tr></thead><tr><td>'
            f'<iframe src="https://www.youtube.com/embed/{vid}" allowfullscreen></iframe>'
            f'<div class="margin-clear" style="padding:0">{caption}</div></td></tr>')


def tnn_page(blocks, pages=2):
    return ("".join(blocks) + "</table>" + "".join(f'<li class="page-item" id="thispage{i}">' for i in range(1, pages + 1)))


TNN_MEMBERS = ("<select name=\"council1tag\"><option value=\"\">全部</option>"
               "<optgroup label='第09選區-安平.南區'><option value='林美燕'>林美燕</option><option value='李啟維'>李啟維</option>"
               "<optgroup label='第12選區-平地原住民'><option value='Ingay Tali穎艾達利'>Ingay Tali穎艾達利</option></select>")


def new_conn(tmp, iso, people):
    """people：[(person_id, name, district_n, 有 2026 candidacy)]；另加一位只參選、沒有議員任職的人。"""
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, n, cand in people:
        district = f"{iso}-council-{n:02d}"
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": f"{iso}_councilor", "district_id": district},
                    "https://u", "t", date="2022-12-25")
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": district}, "https://u", "t")
    upsert_person(conn, "p9", "某市長候選人")
    upsert_fact(conn, "cand:p9", "p9", "candidacy", {"district_id": f"{iso}-mayor"}, "https://u", "t")
    return conn


class TestTxgParse(unittest.TestCase):
    def test_page_rows_use_the_pager_ano_for_the_unlinked_current_row(self):
        rows, last = txg_videos.parse_page(txg_page([txg_row(TXG_JOINT, "2026-09-29"),
                                                     txg_row(TXG_DEPT, "2026-09-02", ano="14742")]))
        self.assertEqual(last, 32)
        self.assertEqual([(r["ano"], r["date"]) for r in rows], [("14849", "2026-09-29"), ("14742", "2026-09-02")])

    def test_titles_give_session_department_and_joint_councillors(self):
        m = txg_videos.parse_title(TXG_JOINT)
        self.assertEqual((m["session"], m["doc_type"], m["dept"], m["councillors"]),
                         ("第4屆第8次定期會", "市政總質詢", None, ["陳俞融", "陳淑華"]))
        m = txg_videos.parse_title(TXG_DEPT)
        self.assertEqual((m["doc_type"], m["dept"], m["title"], m["councillors"]),
                         ("部門質詢", "都發建設水利", "業務質詢（都發建設水利）", []))
        m = txg_videos.parse_title("第4屆第4次定期會 業務質詢：交通地政部分(陳文政、邱愛珊等議員聯合質質詢)")
        self.assertEqual((m["dept"], m["councillors"]), ("交通地政", ["陳文政", "邱愛珊"]))
        self.assertIsNone(txg_videos.parse_title("第4屆第8次定期會 開幕典禮"))
        with self.assertRaises(ValueError):
            txg_videos.parse_title("第4屆第8次定期會 質詢時間")

    def test_videos_keep_term_4_only_and_dedupe_by_ano(self):
        rows = [{"ano": "1", "title": TXG_DEPT, "date": "2026-09-02"}, {"ano": "1", "title": TXG_DEPT, "date": "2026-09-02"},
                {"ano": "2", "title": TXG_OLD, "date": "2022-10-01"}]
        got = txg_videos.parse_videos(rows, "陳淑華")
        self.assertEqual([(v["video_id"], v["councillors"]) for v in got], [("1", ["陳淑華"])])

    def test_members_match_by_name_with_variant_characters_and_unlinked_names(self):
        members = txg_videos.parse_members(TXG_MEMBERS)
        got = txg_videos.match_members([{"person_id": "a", "name": "楊啟邦"}, {"person_id": "b", "name": "張清照"}], members)
        self.assertEqual(got, {"a": ("楊啓邦", "85"), "b": ("張清照", None)})
        with self.assertRaises(ValueError):
            txg_videos.match_members([{"person_id": "c", "name": "王小明"}], members)


class TestTxgRun(unittest.TestCase):
    def test_only_incumbent_candidates_get_facts_once(self):
        people = [("p1", "陳淑華", 6, True), ("p2", "楊啓邦", 1, False), ("p3", "張清照", 2, True)]
        rows = [{"ano": "14849", "title": TXG_JOINT, "date": "2026-09-29"},
                {"ano": "14742", "title": TXG_DEPT, "date": "2026-09-02"}]
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, "txg", people)
            self.assertEqual([t["person_id"] for t in txg_videos.targets(conn)], ["p1", "p3"])
            cache = Path(tmp) / "cache"
            cache.mkdir()
            (cache / "members.html").write_text(TXG_MEMBERS, encoding="utf-8")
            with mock.patch.object(txg_videos, "CACHE", cache), \
                    mock.patch.object(txg_videos, "fetch_member", return_value=rows) as fetch, \
                    mock.patch.object(txg_videos, "now_utc", side_effect=["T1", "T2"]):
                txg_videos.run(conn)
                txg_videos.run(conn)
            self.assertEqual({c.args[0] for c in fetch.call_args_list}, {"24"})
            got = conn.execute("SELECT fact_key, person_id, date, data, source_url, fetched_at FROM fact "
                               "WHERE fact_key LIKE 'tvideo:%' ORDER BY date").fetchall()
            self.assertEqual([(r["fact_key"], r["person_id"], r["fetched_at"]) for r in got],
                             [("tvideo:14742:p1", "p1", "T1"), ("tvideo:14849:p1", "p1", "T1")])
            self.assertEqual(got[1]["source_url"], "https://vod.tccc.gov.tw/index.asp?url=22&cno=24&ano=14849")
            d = json.loads(got[1]["data"])
            self.assertEqual((d["group_size"], d["clip"], d["councillors"]), (2, True, ["陳俞融", "陳淑華"]))

    def test_incremental_fetch_stops_at_a_known_ano_and_merges(self):
        page1 = txg_page([txg_row(TXG_JOINT, "2026-09-29"), txg_row(TXG_DEPT, "2026-09-02", ano="14742")])
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / "cno_24.json").write_text(json.dumps({"rows": [{"ano": "14742", "title": TXG_DEPT,
                                                                      "date": "2026-09-02"}]}), encoding="utf-8")
            with mock.patch.object(txg_videos, "CACHE", cache), \
                    mock.patch.object(txg_videos, "fetch", return_value=page1) as fetch:
                rows = txg_videos.fetch_member("24")
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual([r["ano"] for r in rows], ["14849", "14742"])

    def test_full_fetch_stops_after_the_page_reaching_the_previous_term(self):
        pages = {1: txg_page([txg_row(TXG_DEPT, "2026-09-02", ano="2")], last=3),
                 2: txg_page([txg_row(TXG_OLD, "2022-10-01", ano="1")], last=3)}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(txg_videos, "CACHE", Path(tmp)), \
                mock.patch.object(txg_videos, "fetch", side_effect=lambda p: pages[int(p.rsplit("=", 1)[1])]) as fetch:
            rows = txg_videos.fetch_member("24")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual([r["ano"] for r in rows], ["2", "1"])


TNN_H8 = "2026-09-02【第4屆第8次定期會：市政總質詢】"
TNN_H1 = "2023-06-05【第4屆第1次定期會：市政總質詢】"


class TestTnnParse(unittest.TestCase):
    def test_page_rows_and_last_page(self):
        rows, last = tnn_videos.parse_page(tnn_page([tnn_block(TNN_H8, "6SSZuttYCJk", "李啓維議員市政總質詢")]))
        self.assertEqual(last, 2)
        self.assertEqual(rows, [{"video_id": "6SSZuttYCJk", "header": TNN_H8, "caption": "李啓維議員市政總質詢"}])

    def test_headers(self):
        m = tnn_videos.parse_header(TNN_H8)
        self.assertEqual((m["date"], m["session"], m["doc_type"], m["term"]), ("2026-09-02", "第4屆第8次定期會", "市政總質詢", 4))
        self.assertIsNone(tnn_videos.parse_header("2026-09-02【第4屆第8次定期會：專案報告】"))
        with self.assertRaises(ValueError):
            tnn_videos.parse_header("2026-09-02 市政總質詢")

    def test_videos_need_the_councillor_in_the_caption_term_4_and_unique_ids(self):
        rows = [{"video_id": "A" * 11, "header": TNN_H8, "caption": "李啓維議員市政總質詢"},
                {"video_id": "A" * 11, "header": TNN_H8, "caption": "李啓維議員市政總質詢"},
                {"video_id": "B" * 11, "header": TNN_H1, "caption": "李啟維議員市政總質詢"},
                {"video_id": "C" * 11, "header": TNN_H1, "caption": "林美燕議員市政總質詢"},
                {"video_id": "D" * 11, "header": "2022-06-01【第3屆第8次定期會：市政總質詢】", "caption": "李啟維議員市政總質詢"}]
        got = tnn_videos.parse_videos(rows, "李啟維")
        self.assertEqual([v["video_id"] for v in got], ["B" * 11, "A" * 11])
        self.assertEqual(tnn_videos.video_url("A" * 11), "https://www.youtube.com/watch?v=AAAAAAAAAAA")

    def test_joint_captions_list_the_group(self):
        rows = [{"video_id": "J" * 11, "header": TNN_H8, "caption": "蔡育輝、李中岑、蔡淑惠市政總質詢(聯合質詢)"},
                {"video_id": "K" * 11, "header": TNN_H1, "caption": "郭信良、盧崑福議員市政總質詢（共用時間）"}]
        self.assertEqual([v["councillors"] for v in tnn_videos.parse_videos(rows[:1], "李中岑")], [["蔡育輝", "李中岑", "蔡淑惠"]])
        self.assertEqual([v["councillors"] for v in tnn_videos.parse_videos(rows[1:], "盧崑福")], [["郭信良", "盧崑福"]])
        self.assertEqual([v["councillors"] for v in tnn_videos.parse_videos(
            [{"video_id": "L" * 11, "header": TNN_H8, "caption": "李啓維議員市政總質詢"}], "李啟維")], [["李啟維"]])

    def test_members_match_by_name_and_district(self):
        members = tnn_videos.parse_members(TNN_MEMBERS)
        ts = [{"person_id": "a", "name": "李啓維", "district_n": 9}, {"person_id": "b", "name": "穎艾達利 Ingay Tali", "district_n": 12}]
        self.assertEqual(tnn_videos.match_members(ts, members), {"a": "李啟維", "b": "Ingay Tali穎艾達利"})
        with self.assertRaises(ValueError):
            tnn_videos.match_members([{"person_id": "c", "name": "李啓維", "district_n": 8}], members)


class TestTnnRun(unittest.TestCase):
    def test_only_incumbent_candidates_get_youtube_facts_once(self):
        people = [("p1", "李啓維", 9, True), ("p2", "林美燕", 9, False)]
        rows = [{"video_id": "6SSZuttYCJk", "header": TNN_H8, "caption": "李啓維議員市政總質詢"}]
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, "tnn", people)
            cache = Path(tmp) / "cache"
            cache.mkdir()
            (cache / "members.html").write_text(TNN_MEMBERS, encoding="utf-8")
            with mock.patch.object(tnn_videos, "CACHE", cache), \
                    mock.patch.object(tnn_videos, "fetch_member", return_value=rows) as fetch, \
                    mock.patch.object(tnn_videos, "now_utc", side_effect=["T1", "T2"]):
                tnn_videos.run(conn)
                tnn_videos.run(conn)
            self.assertEqual({c.args[0] for c in fetch.call_args_list}, {"李啟維"})
            got = conn.execute("SELECT fact_key, person_id, date, data, source_url, fetched_at FROM fact "
                               "WHERE fact_key LIKE 'nvideo:%'").fetchall()
            self.assertEqual([(r["fact_key"], r["date"], r["fetched_at"]) for r in got],
                             [("nvideo:6SSZuttYCJk:p1", "2026-09-02", "T1")])
            self.assertEqual(got[0]["source_url"], "https://www.youtube.com/watch?v=6SSZuttYCJk")
            d = json.loads(got[0]["data"])
            self.assertEqual((d["doc_type"], d["session"], d["clip"], d["group_size"]), ("市政總質詢", "第4屆第8次定期會", True, 1))

    def test_incremental_fetch_stops_at_a_known_video(self):
        page1 = tnn_page([tnn_block(TNN_H8, "N" * 11, "李啟維議員市政總質詢"), tnn_block(TNN_H1, "O" * 11, "李啟維議員市政總質詢")])
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / "李啟維.json").write_text(json.dumps({"rows": [{"video_id": "O" * 11, "header": TNN_H1,
                                                                     "caption": "李啟維議員市政總質詢"}]}), encoding="utf-8")
            with mock.patch.object(tnn_videos, "CACHE", cache), \
                    mock.patch.object(tnn_videos, "fetch", return_value=page1) as fetch:
                rows = tnn_videos.fetch_member("李啟維")
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(fetch.call_args[0][0]["council1tag"], "李啟維")
            self.assertEqual([r["video_id"] for r in rows], ["N" * 11, "O" * 11])


if __name__ == "__main__":
    unittest.main()
