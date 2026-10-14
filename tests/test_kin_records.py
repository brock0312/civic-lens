import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import kin_book, kin_videos


def row(gid, nth, date, chair, askers, kind="定期會"):
    return (f'<tr id="Item_{gid}"><td class="text-center">第8屆</td><td class="text-center">第{nth}次</td>'
            f'<td class="text-center">{kind}</td><td class="text-center">  {date}</td><td class="text-center"> {chair}</td>'
            f'<td class="text-center"> 某某</td><td class="text-center">\n\n   {askers}\n </td>'
            f'<td><a href="/CouncilManage/AgendaGovMinutes/Detail/{gid}">檢視</a></td></tr>')


G = ["0" * 8 + f"-0000-0000-0000-{i:012d}" for i in range(10)]
# 113-12 定期會有一場官方寫 114-12-11（誤植）；第 3 列沒有質詢議員；主席欄的議員不算質詢議員
GOV_PAGE = "<tbody>" + "".join([
    row(G[0], 4, "113-12-10", "許議員大鴻", "王國代"),
    row(G[1], 4, "113-12-11", "唐議員麗輝", "許玉昭、董森堡、洪成發"),
    row(G[2], 4, "113-12-12", "洪議長允典", ""),
    row(G[3], 4, "114-12-11", "董議員森堡", "歐陽儀雄、唐麗輝"),
    row(G[4], 4, "113-12-13", "陳議員泱瑚", "楊育菡"),
]) + "</tbody>"
DETAILS = {G[0]: '<span class="title title-15">質詢紀錄</span>\n<span class="text" style="white-space: pre-line">\n'
                 '     質詢議員：王議員國代、吳議員佩雯\n\n主席許議員大鴻：\n請王國代王議員。'}

MINUTES_PAGE = "<tbody>" + "".join(
    f'<tr id="Item_{G[i]}"><td>第8屆</td><td>第{nth}次</td><td>{kind}</td><td> {d}</td><td> 洪議長允典</td><td> 某</td>'
    f'<td><a href="/ServerFile/Get/{G[i]}"><span>{title}.pdf</span></a> (283KB)</td></tr>'
    for i, nth, kind, d, title in [
        (1, 1, "定期會", "112-04-20", "第1次會議紀錄"), (2, 1, "定期會", "112-04-21", "第2次會議紀錄"),
        (3, 1, "定期會", "112-04-22", "第一審查委員會會議紀錄"), (4, 2, "臨時會", "112-06-01", "第1次會議紀錄"),
        (5, 2, "臨時會", "112-06-02", "第2次會議紀錄"), (6, 2, "臨時會", "112-06-03", "第3次會議紀錄")]) + "</tbody>"

# pdftotext -layout 的樣子：名單換行、議長副議長職稱在姓與名之間、姓名中間夾空白
PLENARY = ("    金門縣議會第八屆第 1 次定期會第 1 次會議紀錄摘要\n\n一、時間：中華民國 112 年 4 月 20 日上午 9 時\n\n"
           "三、出席：議員 {n} 人\n\n       {names}\n\n四、列席：\n   （一）縣府 23 人\n        陳縣長福海、李副縣長文良\n")
COMMITTEE = "金門縣議會第八屆第一次定期會第 1 審查委員會會議紀錄\n三、出席：\n  出席議員 王 秀 玉 蔡 水 游\n四、列席單位及人員：\n"
TEXTS = {
    G[1]: PLENARY.format(n=4, names="洪議長允典、歐陽副議長儀雄、董議員森\n      堡、王議員秀玉"),
    G[2]: PLENARY.format(n=4, names="洪議長允典、董議員森堡、王議員秀玉"),  # 少一人：不收
    G[3]: COMMITTEE,
    G[4]: PLENARY.format(n=3, names="洪議長允典、王議員秀玉、楊議員育菡"),  # 前議員，遞補者列名之前：照收
    G[5]: PLENARY.format(n=3, names="洪議長允典、王議員秀玉、吳議員佩雯"),
    G[6]: PLENARY.format(n=3, names="洪議長允典、吳議員佩雯、楊議員育菡"),  # 遞補者已列名後又出現前議員：整次不收
}

PEOPLE = [("p1", "洪允典", True, "2022-12-25"), ("p2", "歐陽儀雄", False, "2022-12-25"), ("p3", "董森堡", True, "2022-12-25"),
          ("p4", "王秀玉", True, "2022-12-25"), ("p5", "王國代", True, "2022-12-25"), ("p6", "吳佩雯", True, None),
          ("p7", "唐麗輝", True, "2022-12-25"), ("p8", "許玉昭", False, "2022-12-25"), ("p9", "洪成發", True, "2022-12-25")]


def new_conn(tmp, people=PEOPLE):
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand, since in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "kin_councilor", "district_id": "kin-council-01"},
                    "https://u", "t", date=since)
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "kin-council-01"}, "https://u", "t")
    return conn


def build(people=PEOPLE):
    gov, minutes = kin_book.parse_rows(GOV_PAGE), kin_book.parse_rows(MINUTES_PAGE)
    with tempfile.TemporaryDirectory() as tmp:
        logs = []
        out = kin_book.build(new_conn(tmp, people), gov, minutes, DETAILS, TEXTS, logs.append)
    return out, logs


class TestKinAttendance(unittest.TestCase):
    def test_present_list_strips_titles_and_joins_wrapped_names(self):
        self.assertEqual(kin_book.parse_present(TEXTS[G[1]]), (4, ["洪允典", "歐陽儀雄", "董森堡", "王秀玉"], 0))

    def test_names_run_together_at_a_line_end_are_split_on_titles(self):
        text = PLENARY.format(n=5, names="（依席次排列）洪議長允典、石議員永城\n   董議員森堡、王議員國代\n 歐陽副議長儀雄")
        self.assertEqual(kin_book.parse_present(text), (5, ["洪允典", "石永城", "董森堡", "王國代", "歐陽儀雄"], 2))
        self.assertEqual(kin_book.present_names("董議員森堡某某某"), (["董議員森堡某某某"], 0))  # 切不乾淨：原樣保留，之後擋下

    def test_committee_minutes_are_not_plenary(self):
        self.assertIsNone(kin_book.parse_present(COMMITTEE))

    def test_meeting_whose_list_disagrees_with_stated_count_is_dropped(self):
        (ts, govs, meetings, gf, att), logs = build()
        self.assertEqual([(m["session"], m["date"]) for m in meetings],
                         [("第8屆第1次定期會", "2023-04-20"), ("第8屆第2次臨時會", "2023-06-01"), ("第8屆第2次臨時會", "2023-06-02")])
        self.assertTrue(any("記載出席 4 人，名單讀到 3 個" in x for x in logs))

    def test_former_member_is_accepted_only_before_the_successor_is_listed(self):
        (ts, govs, meetings, gf, att), logs = build()
        self.assertNotIn("2023-06-03", [m["date"] for m in meetings])
        self.assertTrue(any("112-06-03" in x and "對不到名錄的人 楊育菡" in x for x in logs))
        self.assertTrue(any("楊育菡：前議員（吳佩雯遞補前），照收" in x for x in logs))

    def test_attendance_is_present_only_per_session(self):
        (ts, govs, meetings, gf, att), logs = build()
        self.assertEqual([(k, d["meetings"], d["present"], d["leave"], date) for k, d, _, date in att["p4"]],
                         [("kinattend:1r:p4", 1, 1, None, "2023-04-20"), ("kinattend:2t:p4", 2, 2, None, "2023-06-01")])
        self.assertEqual(att["p4"][0][2], f"https://agenda.kmcc.gov.tw/ServerFile/Get/{G[1]}")
        self.assertNotIn("p2", att)  # 沒參選 2026

    def test_replacement_counts_from_first_listed_meeting(self):
        (ts, govs, meetings, gf, att), logs = build()
        self.assertEqual([(d["session"], d["meetings"], d["present"]) for _, d, _, _ in att["p6"]], [("第8屆第2次臨時會", 1, 1)])
        self.assertEqual(sum(d["meetings"] for _, d, _, _ in att["p3"]), 3)  # 原任議員照全部會議算


class TestKinGovMinutes(unittest.TestCase):
    def test_one_fact_per_listed_asker_linking_to_the_detail_page(self):
        (ts, govs, meetings, gf, att), logs = build()
        self.assertEqual([k for k, *_ in gf["p3"]], [f"kingov:{G[1]}:p3"])
        k, d, url, date = gf["p3"][0]
        self.assertEqual(url, f"https://agenda.kmcc.gov.tw/CouncilManage/AgendaGovMinutes/Detail/{G[1]}")
        self.assertEqual((d["session"], d["doc_type"], date), ("第8屆第4次定期會", "縣政總質詢紀錄", "2024-12-11"))
        self.assertEqual(d["councillors"], ["許玉昭", "董森堡", "洪成發"])
        self.assertNotIn("p1", gf)  # 主席欄不算
        self.assertFalse(any(G[2] in k for fs in gf.values() for k, *_ in fs))  # 沒有質詢議員的場次

    def test_detail_page_adds_askers_missing_from_the_list_column(self):
        (ts, govs, meetings, gf, att), logs = build()
        self.assertEqual([k for k, *_ in gf["p6"]], [f"kingov:{G[0]}:p6"])
        self.assertEqual(gf["p5"][0][1]["councillors"], ["王國代", "吳佩雯"])
        self.assertTrue(any("詳細頁列 吳佩雯" in x for x in logs))

    def test_reviewed_override_adds_askers_and_fills_an_empty_row(self):
        govs = kin_book.gov_rows(kin_book.parse_rows(GOV_PAGE), DETAILS, lambda s: None,
                                 askers={G[2]: {"add": ["董森堡"], "not_asker": []}, G[1]: {"add": ["王秀玉"], "not_asker": []}})
        by_id = {g["id"]: g["names"] for g in govs}
        self.assertEqual(by_id[G[2]], ["董森堡"])
        self.assertEqual(by_id[G[1]], ["許玉昭", "董森堡", "洪成發", "王秀玉"])

    def test_detector_flags_uncovered_invitations_and_frequent_speakers_but_never_attaches(self):
        page = ('<span class="title">質詢紀錄</span><span>\n主席唐議員麗輝：\n石永城石議員請發言。\n石議員永城：\n請局長。\n'
                + "王議員秀玉：\n問。\n某局長：\n答。\n" * 3 + "唐議員麗輝：\n下一位。\n" * 3 + "蔡議員其雍：\n問。\n" * 2 + "</span>")
        roster = ["石永城", "王秀玉", "唐麗輝", "蔡其雍"]
        self.assertEqual(kin_book.suspects(page, roster, set()), [("石永城", "被請發言"), ("王秀玉", "發言 3 段"), ("唐麗輝", "發言 3 段")])
        self.assertEqual(kin_book.suspects(page, roster, {"石永城", "王秀玉", "唐麗輝"}), [])
        rows = kin_book.parse_rows(row(G[9], 4, "113-12-10", "唐議員麗輝", "石永城"))
        logs = []
        govs = kin_book.gov_rows(rows, {G[9]: page}, logs.append, askers={G[9]: {"add": [], "not_asker": ["王秀玉"]}},
                                 roster_names=roster)
        self.assertEqual(govs[0]["names"], ["石永城"])  # 待審閱的人不歸屬
        self.assertEqual(logs, [])  # 主席欄（唐麗輝）與審閱過的 not_asker（王秀玉）不再列待審閱
        govs = kin_book.gov_rows(rows, {G[9]: page}, logs.append, askers={}, roster_names=roster)
        self.assertTrue(any("王秀玉 發言 3 段" in x and "待審閱" in x for x in logs))
        self.assertEqual(govs[0]["names"], ["石永城"])

    def test_askers_file_rejects_unknown_decisions_and_long_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.csv"
            p.write_text("detail_guid,name,decision,evidence\ng,王秀玉,add,王秀玉議員請發言。\ng,石永城,not_asker,一句\n", encoding="utf-8")
            self.assertEqual(kin_book.load_askers(p), {"g": {"add": ["王秀玉"], "not_asker": ["石永城"]}})
            p.write_text("detail_guid,name,decision,evidence\ng,王秀玉,maybe,x\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                kin_book.load_askers(p)

    def test_real_askers_file_is_well_formed(self):
        self.assertTrue(all(n for v in kin_book.load_askers().values() for n in v["add"]))

    def test_out_of_session_date_keeps_official_value_but_is_not_a_sort_date(self):
        (ts, govs, meetings, gf, att), logs = build()
        k, d, url, date = gf["p7"][0]
        self.assertIsNone(date)
        self.assertTrue(d["no_date"])
        self.assertIn("官方記載日期 114-12-11", d["title"])

    def test_same_name_in_roster_is_not_matched(self):
        (ts, govs, meetings, gf, att), logs = build(PEOPLE + [("p10", "董森堡", True, "2022-12-25")])
        self.assertNotIn("p3", gf)
        self.assertNotIn("p3", att)
        self.assertTrue(any("同名" in x for x in logs))


class TestKinVideos(unittest.TestCase):
    ITEMS = [{"video_id": "a1", "title": "1131211金門縣議會第八屆第4次定期會-1"},
             {"video_id": "a2", "title": "1131211金門縣議會第八屆第4次定期會-2"},
             {"video_id": "b1", "title": "1131210金門縣議會第八屆第4次定期會"},
             {"video_id": "c1", "title": "1141211金門縣議會第八屆第6次定期會-1"},  # 誤植日期那場不對到別的會期
             {"video_id": "d1", "title": "1131211第八屆第4次定期會第一審查委員會錄影檔"},
             {"video_id": "e1", "title": "12/11/2024 Kinmen County Council 8th Term, 4th Regular Session"}]

    def test_title_parsing(self):
        self.assertEqual(kin_videos.parse_title("1121116金門縣議會第八屆第2次定期會-1(第2段請至影片頁籤觀看)"),
                         {"date": "2023-11-16", "nth": 2, "part": 1})
        self.assertIsNone(kin_videos.parse_title("1150918金門縣議會第八屆第19次臨時會-1"))

    def test_videos_match_by_session_and_date_to_that_days_askers(self):
        govs = kin_book.gov_rows(kin_book.parse_rows(GOV_PAGE), DETAILS, log=lambda s: None)
        vs = kin_videos.match(self.ITEMS, govs)
        self.assertEqual([(v["video_id"], v["part"]) for v in vs], [("b1", None), ("a1", 1), ("a2", 2)])
        self.assertEqual(vs[1]["names"], ["許玉昭", "董森堡", "洪成發"])
        self.assertEqual(vs[0]["names"], ["王國代", "吳佩雯"])
        with tempfile.TemporaryDirectory() as tmp:
            ts, videos, by_pid = kin_videos.build(new_conn(tmp), self.ITEMS, govs)
        self.assertEqual([v["video_id"] for v in by_pid["p3"]], ["a1", "a2"])
        self.assertNotIn("p7", by_pid)  # 唐麗輝只出現在誤植日期那場
        self.assertNotIn("p8", by_pid)  # 沒參選 2026


if __name__ == "__main__":
    unittest.main()
