import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import hsq_book

U = "https://www.hcc.gov.tw/upload/web_program/"


def link(path, text):
    return f'<li><a href="{U}{path}" download="{text}.pdf" title="{text} .pdf">{text} </a></li>'


DETAIL = ('<h2 class="intro-title">第20屆第7次定期會</h2><table><tbody>'
          '<tr class="membertable-list"><th scope="row" colspan="2" class="">質詢內容</th></tr>'
          '<tr>\n<td class="membertable--width">議長</td>\n<td><ul>'
          + link("2026/08/18/01張議長鎮榮書面質詢資料_113533.pdf", "張鎮榮 議長質詢")
          + link("2026/08/18/議長致詞     1150417_113653.pdf", "張鎮榮 議長致詞") + '</ul></td>\n</tr>'
          '<tr>\n<td class="membertable--width">縣長致詞</td>\n<td><ul>'
          + link("2026/08/18/縣長_113720.pdf", "楊文科縣長致詞") + '</ul></td>\n</tr>'
          '<tr>\n<td class="membertable--width">副議長</td>\n<td><ul>'
          + link("2026/08/18/02王副議長炳漢_113212.pdf", "王炳漢 副議長質詢") + '</ul></td>\n</tr>'
          '<tr>\n<td class="membertable--width">議員</td>\n<td><ul>'
          + link("2026/08/18/03邱靖雅議員_113749.pdf", "邱靖雅")
          + link("2026/08/18/11吳傳地、何建樺、張珈源議員   質詢稿   1150506_113943.pdf", "張珈源 、何建樺、吳傳地聯合質詢")
          + link("2026/08/18/25張良印書面質詢資料_114301.pdf", "張良印")
          + link("2026/08/18/17陳柏誠_114110.pdf", "陳栢誠")  # 檔名錯字，照連結文字
          + link("2026/08/18/26鄭昱芸_145856.pdf", " ")  # 連結文字空白
          + link("2026/08/18/28彭余美玲_114331.pdf", "彭余美玲")  # 封面與連結文字不同
          + '</ul></td>\n</tr></tbody></table>')

COVER = ("新竹縣議會第 20 屆第 7 次定期會\n\n\n  縣 政 總 質 詢 會 議 記 錄\n\n\n   質詢議員：{askers}\n\n\n\n    記   錄：羅文君\n"
         "    校   閱：\n\n             1\n主席（張議長鎮榮）：          記錄：羅文君\n\n  現在開始 50 分鐘是議員的質詢時間，現在請議員發言。\n")
TEXTS = {
    U + "2026/08/18/01張議長鎮榮書面質詢資料_113533.pdf": "\f\f\f",
    U + "2026/08/18/02王副議長炳漢_113212.pdf": COVER.format(askers="王副議長炳漢"),
    U + "2026/08/18/03邱靖雅議員_113749.pdf": COVER.format(askers="邱靖雅議員"),
    U + "2026/08/18/11吳傳地、何建樺、張珈源議員   質詢稿   1150506_113943.pdf": COVER.format(askers="吳議員傳地 何議員建樺 張議員珈源"),
    U + "2026/08/18/25張良印書面質詢資料_114301.pdf": "\f \f",
    U + "2026/08/18/17陳柏誠_114110.pdf": COVER.format(askers="陳議員栢誠"),
    U + "2026/08/18/26鄭昱芸_145856.pdf": COVER.format(askers="鄭議員昱芸"),
    U + "2026/08/18/28彭余美玲_114331.pdf": COVER.format(askers="彭余議員美玲 鄭議員朝鐘"),
}


def rec(path, title):
    return (f'<div class="schedule-content__list">\n <a href="{U}{path}" download="{title}紀錄.pdf" class="schedule-link" '
            f'title="{title}紀錄.pdf">>{title}</a>\n<div class="schedule-date"><p class="schedule-year">2026</p></div>\n'
            f'<p class="schedule-title">{title}</p>\n<div class="record-btn"><a href="{U}{path}" download="{title}.pdf" '
            f'class="icon--2" title="下載">下載</a></div>\n</div>')


RECORDS_PAGE = "".join([
    rec("2026/09/24/第62次程序委員會_143822.pdf", "第20屆第62次程序委員會議紀錄"),
    rec("2023/03/01/m1.pdf", "第20屆第1次臨時會第1次會議"),
    rec("2023/03/02/m2.pdf", "第20屆第1次臨時會第2次會議"),
    rec("2023/03/03/m3.pdf", "第20屆第1次臨時會第3次會議"),
    rec("2023/05/01/m4.pdf", "第20屆第1次定期會開幕典禮及預備會議"),
    rec("2023/05/02/m5.pdf", "第20屆第1次定期會第1次會"),
    rec("2023/05/02/m6.pdf", "第20屆第1次定期會第1次會上午"),  # 和 m5 同一會議時間：重複
    rec("2023/05/03/m7.pdf", "第20屆第1次定期會第2次會"),
    rec("2023/05/04/m8.pdf", "第20屆第1次定期會第3次會"),
])

MINUTES = ("        新 竹 縣 議 會 第 20 屆 第 {nth} 次 {kind}\n                第 1 次會議紀要\n"
           "會議時間：中華民國 {y} 年 {m} 月 {d} 日（星期五）{hh} 時 5 分\n會議地點：本會議事堂\n出席議員：\n  {names}\n"
           "列席人員：\n 縣政府：\n   民政處處長：某某某\n主 席：張議長鎮榮\n")


def minutes(names, d, nth=1, kind="臨 時 會", m=3, hh=15):
    return MINUTES.format(nth=nth, kind=kind, y=112, m=m, d=d, hh=hh, names=names)


TEXTS.update({
    U + "2023/03/01/m1.pdf": minutes("張鎮榮、邱靖雅、何建樺、\n  鄭昱芸、王炳漢", 1),  # 前議員，遞補者列名前：照收
    U + "2023/03/02/m2.pdf": minutes("張鎮榮、邱靖雅、陳星宏、\n  王炳漢", 2),  # 遞補者第一次列名
    U + "2023/03/03/m3.pdf": minutes("張鎮榮、邱靖雅、陳星宏、鄭昱芸", 3),  # 遞補後又出現前議員：整次不收
    U + "2023/05/01/m4.pdf": minutes("張鎮榮、邱靖雅、何建樺陳星宏、王炳漢", 1, kind="定 期 會", m=5),  # 行尾漏頓號：不收
    U + "2023/05/02/m5.pdf": minutes("張鎮榮、邱靖雅、何建樺、陳星宏、王炳漢", 2, kind="定 期 會", m=5, hh=9),
    U + "2023/05/02/m6.pdf": minutes("張鎮榮、邱靖雅、何建樺、陳星宏、王炳漢", 2, kind="定 期 會", m=5, hh=9),
    U + "2023/05/03/m7.pdf": minutes("張鎮榮、何建樺、陳星宏、王炳漢、無名氏", 3, kind="定 期 會", m=5),  # 名錄沒有此人：不收
    U + "2023/05/04/m8.pdf": minutes("張鎮榮、何建樺、陳星宏", 4, nth=2, kind="定 期 會", m=5),  # 表頭會期與清單不同：不收
})

PEOPLE = [("p1", "張鎮榮", False, "2022-12-25"), ("p2", "王炳漢", True, "2022-12-25"), ("p3", "邱靖雅", True, "2022-12-25"),
          ("p4", "何建樺", True, "2022-12-25"), ("p5", "張珈源", True, "2022-12-25"), ("p6", "吳傳地", True, "2022-12-25"),
          ("p7", "張良印", True, "2022-12-25"), ("p8", "陳栢誠", True, None), ("p9", "陳星宏", True, None),
          ("p10", "彭余美玲", True, "2022-12-25")]


def new_conn(tmp, people=PEOPLE):
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand, since in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "hsq_councilor", "district_id": "hsq-council-01"},
                    "https://u", "t", date=since)
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "hsq-council-01"}, "https://u", "t")
    return conn


def build(people=PEOPLE, former=None):
    details = [hsq_book.parse_detail(DETAIL)]
    records = hsq_book.parse_records(RECORDS_PAGE)
    old = hsq_book.FORMER
    hsq_book.FORMER = {"鄭昱芸": "陳星宏"} if former is None else former
    try:
        with tempfile.TemporaryDirectory() as tmp:
            logs = []
            out = hsq_book.build(new_conn(tmp, people), details, records, TEXTS, logs.append)
    finally:
        hsq_book.FORMER = old
    return out, logs


class TestHsqQuestions(unittest.TestCase):
    def test_detail_skips_speeches_and_reads_names_from_link_text(self):
        session, items = hsq_book.parse_detail(DETAIL)
        self.assertEqual(session, "第20屆第7次定期會")
        self.assertEqual([(i["role"], i["names"]) for i in items], [
            ("議長", ["張鎮榮"]), ("副議長", ["王炳漢"]), ("議員", ["邱靖雅"]), ("議員", ["張珈源", "何建樺", "吳傳地"]),
            ("議員", ["張良印"]), ("議員", ["陳栢誠"]), ("議員", []), ("議員", ["彭余美玲"])])

    def test_link_name_variants(self):
        self.assertEqual(hsq_book.link_names("張珈源 &何建樺&吳傳地"), ["張珈源", "何建樺", "吳傳地"])
        self.assertEqual(hsq_book.link_names("呂宛庭 上官秋燕  聯合質詢"), ["呂宛庭", "上官秋燕"])
        self.assertEqual(hsq_book.link_names("張鎮榮 議長"), ["張鎮榮"])
        self.assertEqual(hsq_book.link_names(" "), [])

    def test_cover_askers_are_split_on_titles(self):
        self.assertEqual(hsq_book.pdf_askers(COVER.format(askers="吳議員傳地 何議員建樺 張議員珈源")), ["吳傳地", "何建樺", "張珈源"])
        self.assertEqual(hsq_book.pdf_askers(COVER.format(askers="邱靖雅議員")), ["邱靖雅"])
        self.assertEqual(hsq_book.pdf_askers(COVER.format(askers="上官議員秋燕、彭余議員美玲")), ["上官秋燕", "彭余美玲"])
        self.assertIsNone(hsq_book.pdf_askers("沒有封面"))

    def test_askers_fall_back_to_the_chair_announcement_when_there_is_no_cover(self):
        text = ("主席(張議長鎮榮)：          記錄：陳詩吟\n  現在開始 150 分鐘是張珈源議員、何建樺議員、\n 吳傳地議員聯合質詢的時間，"
                "現在就請張議員開始質詢。\n張議員珈源：\n")
        self.assertEqual(hsq_book.pdf_askers(text), ["張珈源", "何建樺", "吳傳地"])
        self.assertEqual(hsq_book.pdf_askers("主席(張議長鎮榮)： 記錄：某\n 現在是林昭錡議員的質詢時間，請林議員開始質\n 詢。"), ["林昭錡"])
        self.assertEqual(hsq_book.pdf_askers("主席(張議長鎮榮)： 記錄：某\n 現在起一個小時是吳菊花議員質詢的時間"), ["吳菊花"])
        self.assertEqual(hsq_book.pdf_askers(COVER.format(askers="劉建民議員、林秉君議員\n     （聯合質詢）")), ["劉建民", "林秉君"])
        self.assertEqual(hsq_book.pdf_askers(COVER.format(askers="楊 議員 昌 德")), ["楊昌德"])

    def test_cover_typo_of_a_variant_character_still_matches(self):
        session, items = hsq_book.parse_detail(DETAIL)
        texts = {**TEXTS, U + "2026/08/18/17陳柏誠_114110.pdf": COVER.format(askers="陳議員柏誠")}
        docs = hsq_book.question_docs([(session, items)], texts, lambda s: None)
        self.assertIn(["陳栢誠"], [d["names"] for d in docs])

    def test_transcripts_and_scans_become_link_facts_for_each_listed_councillor(self):
        (ts, docs, meetings, qf, att), logs = build()
        k, d, url, date = qf["p4"][0]
        self.assertEqual(k, "hsqq:2026-08-18-113943:p4")
        self.assertEqual((d["doc_type"], d["session"], d["no_date"]), ("縣政總質詢紀錄", "第20屆第7次定期會", True))
        self.assertEqual(d["title"], "縣政總質詢紀錄（聯合質詢：張珈源、何建樺、吳傳地）（PDF）")
        self.assertTrue(url.startswith(U) and "%E8%B3%AA%E8%A9%A2%E7%A8%BF" in url and " " not in url)
        self.assertEqual([k for k, *_ in qf["p5"]], ["hsqq:2026-08-18-113943:p5"])
        self.assertEqual([k for k, *_ in qf["p6"]], ["hsqq:2026-08-18-113943:p6"])
        k, d, url, date = qf["p7"][0]
        self.assertEqual((d["doc_type"], d["scanned"], d["title"]), ("質詢資料", True, "質詢資料（PDF，掃描檔）"))
        self.assertEqual(qf["p8"][0][1]["doc_type"], "縣政總質詢紀錄")  # 檔名錯字不影響
        self.assertEqual(qf["p2"][0][1]["doc_type"], "縣政總質詢紀錄")  # 副議長
        self.assertNotIn("p1", qf)  # 議長沒參選；致詞不收

    def test_unattributable_or_mismatched_documents_are_skipped(self):
        (ts, docs, meetings, qf, att), logs = build()
        self.assertNotIn("p10", qf)
        self.assertTrue(any("彭余美玲" in x and "封面質詢議員 彭余美玲、鄭朝鐘 與連結文字不同" in x for x in logs))
        self.assertTrue(any("連結文字沒有姓名" in x for x in logs))
        self.assertEqual(len(docs), 6)

    def test_joint_document_with_an_unresolvable_name_is_skipped_for_everyone(self):
        people = [p for p in PEOPLE if p[1] != "吳傳地"]
        (ts, docs, meetings, qf, att), logs = build(people)
        self.assertNotIn("p4", qf)
        self.assertNotIn("p5", qf)
        self.assertTrue(any("吳傳地：名錄沒有此人" in x for x in logs))

    def test_question_sort_date_is_the_session_start(self):
        (ts, docs, meetings, qf, att), logs = build()
        self.assertIsNone(qf["p3"][0][3])  # 第 7 次定期會沒有紀要
        records = hsq_book.parse_records(RECORDS_PAGE)
        self.assertEqual(hsq_book.session_starts(records, TEXTS),
                         {"第20屆第1次臨時會": "2023-03-01", "第20屆第1次定期會": "2023-05-01", "第20屆第2次定期會": "2023-05-04"})

    def test_same_name_in_roster_is_not_matched(self):
        (ts, docs, meetings, qf, att), logs = build(PEOPLE + [("p11", "邱靖雅", True, "2022-12-25")])
        self.assertNotIn("p3", qf)
        self.assertNotIn("p3", att)
        self.assertTrue(any("同名" in x for x in logs))


class TestHsqAttendance(unittest.TestCase):
    def test_record_list_keeps_plenary_minutes_only(self):
        titles = [r["title"] for r in hsq_book.parse_records(RECORDS_PAGE)]
        self.assertEqual(len(titles), 8)
        self.assertNotIn("第20屆第62次程序委員會議紀錄", titles)

    def test_minutes_parse_joins_wrapped_lists(self):
        m = hsq_book.parse_minutes(TEXTS[U + "2023/03/01/m1.pdf"])
        self.assertEqual(m, {"session": "第20屆第1次臨時會", "date": "2023-03-01", "time": "15:05",
                             "names": ["張鎮榮", "邱靖雅", "何建樺", "鄭昱芸", "王炳漢"]})
        self.assertIsNone(hsq_book.parse_minutes("第62次程序委員會議紀錄\n出席委員：某某\n"))

    def test_bad_meetings_are_excluded_with_reasons(self):
        (ts, docs, meetings, qf, att), logs = build()
        self.assertEqual([(m["session"], m["date"]) for m in meetings],
                         [("第20屆第1次臨時會", "2023-03-01"), ("第20屆第1次臨時會", "2023-03-02"), ("第20屆第1次定期會", "2023-05-02")])
        joined = "\n".join(logs)
        self.assertIn("2023-03-03 15:05） 名單有對不到名錄的人 鄭昱芸", joined)
        self.assertIn("非姓名的詞 ['何建樺陳星宏']", joined)
        self.assertIn("視為重複", joined)
        self.assertIn("無名氏（名錄沒有此人）", joined)
        self.assertIn("表頭會期 第20屆第2次定期會 與清單標題不同", joined)
        self.assertIn("鄭昱芸：前議員（陳星宏遞補前），照收", joined)

    def test_minutes_without_a_time_or_attendee_footer_still_parse(self):
        text = ("新 竹 縣 議 會 第 20 屆 第 1 次 定 期 會\n 第 11 次 會 議 紀 要\n會議時間：中華民國 112 年 5 月 19 日（星期五）\n"
                "出席議員：\n  張鎮榮、王炳漢\n今日議程：\n 上   午：縣政總質詢\n")
        m = hsq_book.parse_minutes(text)
        self.assertEqual((m["date"], m["time"], m["names"]), ("2023-05-19", None, ["張鎮榮", "王炳漢"]))
        self.assertEqual(hsq_book.parse_minutes(text.replace("（星期五）", "〈星期五〉10 時")).get("time"), "10:00")

    def test_meeting_dated_before_the_term_is_excluded(self):
        records = hsq_book.parse_records(rec("2023/05/09/x.pdf", "第20屆第1次定期會第1次會"))
        texts = {U + "2023/05/09/x.pdf": minutes("張鎮榮", 5, kind="定 期 會", m=5).replace("112 年", "111 年")}
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp)
            self.assertEqual(hsq_book.collect_meetings(records, texts, hsq_book.roster_index(conn, "hsq_councilor"), logs.append), [])
        self.assertIn("任期前", logs[0])
        self.assertEqual(hsq_book.session_starts(records, texts), {})

    def test_former_member_unknown_without_mapping_excludes_the_meeting(self):
        (ts, docs, meetings, qf, att), logs = build(former={})
        self.assertNotIn("2023-03-01", [m["date"] for m in meetings])

    def test_attendance_is_present_only_per_session(self):
        (ts, docs, meetings, qf, att), logs = build()
        self.assertEqual([(k, d["meetings"], d["present"], d["leave"], date) for k, d, _, date in att["p4"]],
                         [("hsqattend:1t:p4", 2, 1, None, "2023-03-01"), ("hsqattend:1r:p4", 1, 1, None, "2023-05-02")])
        self.assertTrue(att["p4"][0][2].startswith(U + "2023/03/01/m1.pdf"))
        self.assertTrue(all(d["from_lists"] and d["duty"] is None for fs in att.values() for _, d, _, _ in fs))
        self.assertNotIn("p1", att)  # 沒參選 2026

    def test_replacement_counts_from_first_listed_meeting(self):
        (ts, docs, meetings, qf, att), logs = build()
        self.assertEqual([(d["session"], d["meetings"], d["present"]) for _, d, _, _ in att["p9"]],
                         [("第20屆第1次臨時會", 1, 1), ("第20屆第1次定期會", 1, 1)])
        self.assertEqual(att.get("p8"), None)  # 從未列名的遞補者沒有出席 fact
        self.assertEqual(sum(d["meetings"] for _, d, _, _ in att["p3"]), 3)


if __name__ == "__main__":
    unittest.main()
