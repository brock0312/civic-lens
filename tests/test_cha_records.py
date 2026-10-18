import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import cha_book, cha_videos


def garble(text):
    """反向模擬第 2、4、5 次定期會電子書的錯碼：中文字 Big5 序號 +436、A1 列標點 +499、ASCII +1。"""
    out = []
    for c in text:
        if ord(c) < 0x80:
            out.append(chr(ord(c) + 1) if 0x20 <= ord(c) < 0x7E else c)
            continue
        b = c.encode("cp950")
        col = b[1] - 0x40 if b[1] < 0x7F else b[1] - 0xA1 + 63
        seq = (b[0] - 0xA1) * 157 + col
        out.append(chr(seq + (499 if b[0] == 0xA1 else 436)))
    return "".join(out)


def day(date_roc, opening, body, closing="散會：下午1時50分"):
    return f"第 4 次會議：{date_roc} II 詳紀錄 記錄：某某 主席(謝議長典霖)：各位好。今天的議程是縣政質詢，{opening}{body}{closing}"


TURN = "{}：問一下工務處。 許工務處長俊宏：謝謝議員。 "
PAGES = [
    "目錄",
    day("114 年 10 月 28 日",
        "質詢的議員依序是賴清美議員個人質詢；周君綾議員、楊妙月議員聯合質詢及李成濟議員個人質詢。首先請賴清美議員發言。",
        TURN.format("賴議員清美") * 4, closing=""),
    # 下一頁：周君綾稍早有一段「針對同一問題」的補充發言，接著李成濟（其實是周君綾那組之前的補充），再來才是周君綾、楊妙月的時段
    TURN.format("周議員君綾") + TURN.format("賴議員清美") + "主席(劉議員淑芳)：接下來是周君綾議員、楊妙月議員聯合質詢。",
    TURN.format("楊議員妙月") * 2 + TURN.format("周議員君綾") * 5 + TURN.format("楊議員妙月") * 3,
    TURN.format("李議員成濟") + "報告主席，本席改採書面質詢。主席(劉議員淑芳)：好。" + TURN.format("王議員小明") * 9 + "散會：下午1時51分",
    day("114 年 10 月 29 日", "出席議員有陳一惇議員個人質詢。", TURN.format("陳議員一惇") * 3),
]
PEOPLE = [("p1", "賴清美", True), ("p2", "周君綾", True), ("p3", "楊妙月", False), ("p4", "李成濟", True),
          ("p5", "王小明", True), ("p6", "陳一惇", True), ("p7", "陳一惇", False)]


def new_conn(tmp, people=PEOPLE):
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "cha_councilor", "district_id": "cha-council-01"},
                    "https://u", "t", date="2022-12-25")
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "cha-council-01"}, "https://u", "t")
    return conn


def build(pages=PAGES, people=PEOPLE, names=None, videos=None, written=False):
    books = [{"id": "no20_r06_t1418", "nth": 6}, {"id": "no20_r03_t0708", "nth": 3}]
    with tempfile.TemporaryDirectory() as tmp:
        logs = []
        out = cha_book.build(new_conn(tmp, people), books, {"no20_r06_t1418": pages}, logs.append,
                             names=names or {}, videos=videos or {})
    return (out[-1] if written else out[:-1]), logs  # written：只回「改採書面質詢」facts


GARBLED_DAY = PAGES[:1] + [day("114 年 11 月 3 日", "質詢議員有陳摙摙議員、楊竣程議員聯合質詢。",
                               TURN.format("陳議員摙摙") * 3 + TURN.format("楊議員竣程") * 3)]
GARBLED_PEOPLE = PEOPLE + [("p11", "陳銌銌", True), ("p12", "楊竣程", True)]
GARBLED_NAMES = {("no20_r06_t1418", "陳摙摙"): {"name": "陳銌銌", "pages": {2}}}


class TextLayerTest(unittest.TestCase):
    def test_garbled_pages_decode_to_big5_text_and_normal_pages_are_untouched(self):
        s = "第 5 次會議：114年5月8日 張議員春洋：東海大學檢驗的地方在哪裡？"
        self.assertEqual(cha_book.decode(garble(s)), s)
        self.assertEqual(cha_book.decode(s), s)

    def test_characters_outside_big5_become_replacement_and_never_match(self):
        raw = garble("陳玉") + chr(300) + garble("議員")  # 300：低於標點區、不是任何字
        self.assertEqual(cha_book.decode(raw), "陳玉�議員")

    def test_search_config_strings_with_invalid_json_escapes_are_parsed(self):
        js = '﻿var textForPages = ["", "a\\"b\\ c", "第\\n二"];\nvar x = ["no"];'
        self.assertEqual(cha_book.parse_pages(js), ["", 'a"b c', "第\n二"])

    def test_page_link_uses_the_ebook_page_index(self):
        self.assertEqual(cha_book.book_url("no20_r06_t1418", 911),
                         "https://ep.chcc.gov.tw/content/meetings/no20_r06_t1418/mobile/index.html#p=911")


class OpeningTest(unittest.TestCase):
    def test_groups_keep_joint_members_together_and_drop_connectives(self):
        t = "今天的議程是縣政質詢，質詢的議員依序是賴清美議員個人質詢；周君綾議員、楊妙月議員聯合質詢及李成濟議員個人質詢。首先請"
        self.assertEqual(cha_book.opening_groups(t), [["賴清美"], ["周君綾", "楊妙月"], ["李成濟"]])

    def test_variant_wordings_of_the_list(self):
        self.assertEqual(cha_book.opening_groups("議程是縣政質詢。質詢議員：洪子超議員個人質詢，凃淑媚議員、陳榮妹議員聯合質詢。首先"),
                         [["洪子超"], ["凃淑媚", "陳榮妹"]])
        self.assertEqual(cha_book.opening_groups("今天的議程是縣政質詢。白玉如議員個人質詢，詹琬惠議員、洪子超議員聯合質詢。現在的時間是"),
                         [["白玉如"], ["詹琬惠", "洪子超"]])
        self.assertEqual(cha_book.opening_groups("出席議員有劉珊伶議員、藍駿宇議員聯合質詢。林小琪議員個人質詢。誰要先講"),
                         [["劉珊伶", "藍駿宇"], ["林小琪"]])

    def test_tomorrow_agenda_at_the_end_of_the_day_is_not_a_list(self):
        self.assertEqual(cha_book.opening_groups("主席：各位好。" + "內文" * 500 + "明天的議程仍然是縣政質詢，質詢議員有王小明議員個人質詢"), [])

    def test_chair_label_is_not_a_speaker_label(self):
        chunks = [(10, "主席(劉議員淑芳)：好。劉議員淑芳：謝謝。")]
        self.assertEqual(cha_book.events(chunks, {"劉淑芳": ["劉淑芳"]}), [(10, "劉淑芳")])


class AttributionTest(unittest.TestCase):
    def test_each_listed_speaker_links_to_the_start_of_their_own_slot(self):
        (ts, entries, by_pid), _ = build()
        pages = {pid: [(d["page"], date, url) for _, d, url, date in facts] for pid, facts in by_pid.items()}
        self.assertEqual(pages["p1"], [(2, "2025-10-28", cha_book.book_url("no20_r06_t1418", 2))])
        # 周君綾在第 3 頁的補充發言之後隔著別組議員（賴清美），本人時段從第 4 頁起
        self.assertEqual(pages["p2"][0][0], 4)

    def test_joint_title_lists_the_group_and_the_ebook_page(self):
        (_, _, by_pid), _ = build()
        _, d, _, _ = by_pid["p2"][0]
        self.assertEqual(d["title"], "縣政質詢紀錄（聯合質詢：周君綾、楊妙月；議事錄電子書第 4 頁起）")
        self.assertEqual(d["session"], "第20屆第6次定期會")
        self.assertEqual(d["councillors"], ["周君綾", "楊妙月"])

    def test_non_candidates_are_not_written(self):
        (_, _, by_pid), _ = build()
        self.assertNotIn("p3", by_pid)

    def test_listed_councillor_who_switched_to_written_questions_is_skipped(self):
        (_, _, by_pid), logs = build()
        self.assertNotIn("p4", by_pid)
        self.assertTrue(any("李成濟 本人發言只有 1 段" in s for s in logs))

    def test_frequent_unlisted_speaker_is_only_logged(self):
        (_, _, by_pid), logs = build()
        self.assertNotIn("p5", by_pid)
        self.assertTrue(any("王小明 發言 9 段但不在質詢名單" in s for s in logs))

    def test_same_name_in_roster_is_not_matched(self):
        (_, entries, by_pid), logs = build()
        self.assertIn("陳一惇", [e["name"] for e in entries])
        self.assertNotIn("p6", by_pid)
        self.assertTrue(any("陳一惇：名錄同名" in s for s in logs))

    def test_garbled_name_is_not_matched(self):
        pages = PAGES[:1] + [day("114 年 10 月 29 日", "質詢議員有�淑媚議員個人質詢。", TURN.format("�議員淑媚") * 3)]
        (_, entries, by_pid), logs = build(pages)
        self.assertEqual(by_pid, {})
        self.assertTrue(any("�淑媚：名錄沒有此人" in s for s in logs))

    def test_scanned_book_is_skipped(self):
        _, logs = build()
        self.assertTrue(any("no20_r03_t0708 掃描影像" in s for s in logs))

    def test_partner_who_switched_to_written_is_left_out_of_the_title(self):
        pages = PAGES[:1] + [day("114 年 10 月 30 日", "質詢議員有曹嘉豪議員、黃正盛議員聯合質詢。",
                                 TURN.format("曹議員嘉豪") * 3 + "主席(劉議員淑芳)：黃正盛議員書面質詢。")]
        people = PEOPLE + [("p13", "曹嘉豪", True), ("p14", "黃正盛", True)]
        (_, _, by_pid), _ = build(pages, people)
        _, d, _, _ = by_pid["p13"][0]
        self.assertEqual(d["title"], "縣政質詢紀錄（議事錄電子書第 2 頁起）")
        self.assertEqual(d["councillors"], ["曹嘉豪"])
        self.assertNotIn("p14", by_pid)

    def test_variant_glyph_in_the_record_matches_the_roster_name(self):
        pages = PAGES[:1] + [day("114 年 11 月 3 日", "質詢議員有陳玉姫議員個人質詢。", TURN.format("陳議員玉姫") * 3)]
        (_, _, by_pid), _ = build(pages, PEOPLE + [("p8", "陳玉姬", True)])
        self.assertEqual([d["page"] for _, d, _, _ in by_pid["p8"]], [2])
        self.assertEqual(by_pid["p8"][0][1]["councillors"], ["陳玉姬"])

    def test_roster_person_named_with_variant_glyph_matches_the_official_spelling(self):
        # 人工確認後 person 名是中選會寫法「陳玉姫」，議事錄寫官網寫法「陳玉姬」
        pages = PAGES[:1] + [day("114 年 11 月 3 日", "質詢議員有陳玉姬議員個人質詢。", TURN.format("陳議員玉姬") * 3)]
        (_, _, by_pid), _ = build(pages, PEOPLE + [("p8", "陳玉姫", True)])
        self.assertEqual([d["page"] for _, d, _, _ in by_pid["p8"]], [2])


DESC = ("彰化縣議會第20屆第8次定期會 \n日期：115年10月06日 \n議程：\n    縣政質詢\n    莊陞漢議員\n    許雅琳議員\n    陳一惇議員\n\n"
        "本直播影音非經當事人同意不得錄製剪輯播放，如有上述情形，其責任由轉錄剪輯播放者自行負責。")


class NameTableTest(unittest.TestCase):
    def test_reviewed_garbled_name_is_recovered_when_page_and_video_agree(self):
        (_, _, by_pid), _ = build(GARBLED_DAY, GARBLED_PEOPLE, GARBLED_NAMES, {"2025-11-03": {"陳銌銌", "楊竣程"}})
        _, d, _, _ = by_pid["p11"][0]
        self.assertEqual(d["page"], 2)
        self.assertEqual(d["title"], "縣政質詢紀錄（聯合質詢：陳銌銌、楊竣程；議事錄電子書第 2 頁起）")

    def test_recovery_is_refused_without_the_name_in_that_days_video(self):
        (_, _, by_pid), logs = build(GARBLED_DAY, GARBLED_PEOPLE, GARBLED_NAMES, {"2025-11-03": {"楊竣程"}})
        self.assertNotIn("p11", by_pid)
        self.assertTrue(any("陳摙摙→陳銌銌：當天影片說明欄沒有列此名" in s for s in logs))

    def test_recovery_is_refused_when_the_reviewed_page_differs(self):
        names = {("no20_r06_t1418", "陳摙摙"): {"name": "陳銌銌", "pages": {9}}}
        (_, _, by_pid), logs = build(GARBLED_DAY, GARBLED_PEOPLE, names, {"2025-11-03": {"陳銌銌"}})
        self.assertNotIn("p11", by_pid)
        self.assertTrue(any("第 2 頁不在人工清單" in s for s in logs))

    def test_unrecovered_garbled_names_are_not_shown_in_a_joint_title(self):
        pages = PAGES[:1] + [day("114 年 11 月 3 日", "質詢議員有陳摙摙議員、楊竣程議員聯合質詢。", TURN.format("楊議員竣程") * 3)]
        (_, _, by_pid), _ = build(pages, GARBLED_PEOPLE)
        _, d, _, _ = by_pid["p12"][0]
        self.assertEqual(d["councillors"], ["楊竣程"])
        self.assertNotIn("摙", d["title"])

    def test_real_names_file_is_well_formed(self):
        names = cha_book.load_names()
        self.assertTrue(names)
        for (book, garbled), v in names.items():
            self.assertNotEqual(garbled, v["name"])
            self.assertTrue(book.startswith("no20_r"))

    def test_names_file_rejects_rows_without_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "n.csv"
            path.write_text("book,page,garbled,name,evidence\nno20_r05_t13,940,x芝樺,温芝樺,\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cha_book.load_names(path)


class VideoTest(unittest.TestCase):
    def test_description_gives_date_and_questioners(self):
        self.assertEqual(cha_videos.parse_description(DESC), {"date": "2026-10-06", "names": ["莊陞漢", "許雅琳", "陳一惇"]})

    def test_early_descriptions_with_spaced_labels_parse(self):
        d = DESC.replace("日期", "日 期").replace("議程", "議 程")
        self.assertEqual(cha_videos.parse_description(d)["date"], "2026-10-06")

    def test_non_interpellation_days_are_skipped(self):
        self.assertIsNone(cha_videos.parse_description(DESC.replace("縣政質詢", "議案審查")))
        self.assertIsNone(cha_videos.parse_description("日期：115年10月06日 議程：縣政質詢"))

    def test_title_pattern_accepts_regular_sessions_with_or_without_date(self):
        self.assertTrue(cha_videos.TITLE.match("彰化縣議會第20屆第8次定期會(115年10月06日)"))
        self.assertTrue(cha_videos.TITLE.match("彰化縣議會第20屆第4次定期會"))
        self.assertIsNone(cha_videos.TITLE.match("彰化縣議會第20屆第19、20次臨時會(115年03月20日)"))
        self.assertIsNone(cha_videos.TITLE.match("彰化縣議會第19屆第8次定期會(111年10月06日)"))

    def test_on_ebook_days_people_who_did_not_question_orally_get_no_video(self):
        items = [{"video_id": "a", "nth": 6, "title": "x"}, {"video_id": "b", "nth": 8, "title": "y"}]
        descs = {"a": DESC.replace("115年10月06日", "114年10月28日"), "b": DESC}
        vs = cha_videos.videos(items, descs, covered={"2025-10-28"}, skipped={("2025-10-28", "許雅琳"), ("2026-10-06", "許雅琳")})
        by = {v["video_id"]: v for v in vs}
        self.assertEqual(by["a"]["names"], ["莊陞漢", "陳一惇"])
        self.assertEqual(by["a"]["listed_by"], "議事錄")
        # 議事錄沒有的日期：照說明欄名單
        self.assertEqual(by["b"]["names"], ["莊陞漢", "許雅琳", "陳一惇"])
        self.assertEqual(by["b"]["listed_by"], "影片說明欄")

    def test_reviewed_description_typo_is_corrected_for_display_only(self):
        items = [{"video_id": "0TRyR1fsW-w", "nth": 2, "title": "x"}]
        d = DESC.replace("115年10月06日", "112年11月08日").replace("許雅琳", "詹婉惠")
        v = cha_videos.videos(items, {"0TRyR1fsW-w": d})[0]
        self.assertEqual(v["shown"], ["莊陞漢", "詹琬惠", "陳一惇"])
        self.assertIn("詹婉惠", v["names"])  # 掛影片仍照說明欄原文比對，不因顯示更正而改歸屬

    def test_video_is_attached_to_each_listed_candidate_only_with_unique_names(self):
        items = [{"video_id": "GcPO3AQC6NU", "nth": 8, "title": "x"}]
        people = PEOPLE + [("p9", "莊陞漢", True), ("p10", "許雅琳", False)]
        with tempfile.TemporaryDirectory() as tmp:
            logs = []
            conn = new_conn(tmp, people)
            ts, vs, by_pid = cha_videos.build(conn, items, {"GcPO3AQC6NU": DESC}, logs.append, book=(set(), set()))
            n, stale = cha_videos.write_videos(conn, by_pid, "t")
            row = conn.execute("SELECT data, source_url, date FROM fact WHERE fact_key = 'chavideo:GcPO3AQC6NU:p9'").fetchone()
        self.assertEqual(sorted(by_pid), ["p9"])
        self.assertEqual(n, 1)
        self.assertTrue(any("陳一惇：名錄同名" in s for s in logs))
        self.assertEqual(row["source_url"], "https://www.youtube.com/watch?v=GcPO3AQC6NU")
        self.assertEqual(row["date"], "2026-10-06")
        self.assertIn('"day": true', row["data"])


if __name__ == "__main__":
    unittest.main()


WRITTEN_PAGES = PAGES[:5] + [
    day("114 年 10 月 29 日", "質詢議員有王小明議員個人質詢。",
        TURN.format("王議員小明") * 3 + "主席(劉議員淑芳)：好，王小明議員質詢結束。接下來是周君綾議員他採書面質詢。"
        "賴清美議員跟王小明議員書面質詢，現在是11點。李議員成濟：其他的我用書面質詢。"
        "主席(許副議長原龍)：好，接下來是李成濟議員個人質詢，他改成書面質詢。主席(許副議長原龍)：其他的可以書面質詢。"),
]


class TestChaWrittenSwitch(unittest.TestCase):
    def test_chair_named_members_get_one_record_per_day_on_that_page(self):
        wr, logs = build(WRITTEN_PAGES, written=True)
        [(k, d, url, date)] = wr["p2"]
        self.assertEqual((k, date), ("chawr:no20_r06_t1418:2025-10-29:p2", "2025-10-29"))
        self.assertEqual(url, cha_book.book_url("no20_r06_t1418", 6))
        self.assertEqual((d["doc_type"], d["link_label"]), (cha_book.WRITTEN_DOC, "議事錄電子書第 6 頁"))
        self.assertEqual([x[3] for x in wr["p4"]], ["2025-10-29"])  # 「…個人質詢，他改成書面質詢」

    def test_sentence_naming_someone_who_spoke_orally_is_dropped_whole(self):
        wr, logs = build(WRITTEN_PAGES, written=True)
        self.assertNotIn("p5", wr)
        self.assertNotIn("p1", wr)  # 同一句的王小明當天有口頭質詢：賴清美也不收
        self.assertTrue(any("賴清美 主席宣布書面質詢的同一句有人當天其實口頭質詢" in x for x in logs))

    def test_only_the_chair_counts_and_unnamed_mentions_are_ignored(self):
        day_ = cha_book.parse_days(WRITTEN_PAGES)[-1]
        self.assertEqual([n for _, n, _ in cha_book.chair_written(day_)], ["周君綾", "賴清美", "王小明", "李成濟"])

    def test_group_forms_split_into_full_names(self):
        d = {"chunks": [(9, "主席(曹議員嘉豪)：第二輪的是曹嘉豪議員、施嘉華議員及黃俊源議員書面質詢，接著。"
                            "主席(曹議員嘉豪)：張國棟議員質詢改書面質詢，現在時間是下午1時43分。")], "date": "2023-05-08"}
        self.assertEqual([n for _, n, _ in cha_book.chair_written(d)], ["曹嘉豪", "施嘉華", "黃俊源", "張國棟"])
