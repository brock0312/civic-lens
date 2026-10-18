import json
import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import cyq_book

URL = "https://ws.cyscc.gov.tw/001/Upload/1/relfile/62/17608/734438ab-e545-44f4-a8da-07088b0351c3.pdf"


def page(printed, body, even=False):
    head = f"{printed}   質詢與答覆" if even else f"                      質詢與答覆   {printed}"
    return f"{head}\n\n\n{body}\n"


def turn(label, text):
    return f"{label}：\n  {text}\n"


def day(roc, recorder=None):
    return f"  嘉義縣議會第 20 屆第 7 次定期大會質詢與答覆\n         縣政總質詢與業務質詢紀錄\n" \
           f"                     {recorder or roc}   記錄人：洪政利\n\n"


PAGES = [
    "         前 言\n\n二、本刊質詢及答覆，係依據錄音摘要彙整\n",
    "質詢與答覆\n     115.5.25   口頭質詢與答覆 .................... 1617\n     115.5.26   口頭質詢與答覆 .................... 1721\n",
    "115.5.26 口頭質詢與答覆\n",  # PDF 3：分隔頁
    "",
    page(1721, day("115.05.26") + turn("主席陳副議長怡岳", "現在請蔡奇璋議員。") + turn("蔡奇璋議員", "縣長好。")
         + turn("翁縣長章梁", "議員好。") + turn("蔡奇璋議員", "第二題。")),
    page(1722, turn("黃嫈珺議員", "我插一句。") + turn("蔡奇璋議員", "第三題。") + turn("主席陳副議長怡岳", "好，請我們岱杰議員。")
         + turn("林岱杰議員", "謝謝副議長。"), even=True),
    page(1723, turn("警察局長古瑞麟", "是。") + turn("林岱杰議員", "對。") + turn("林岱杰議員", "好，謝謝。")
         + turn("王小明議員", "a") + turn("王小明議員", "b") + turn("王小明議員", "c")),
    page(9999, turn("林岱杰議員", "頁首印錯的頁。"), even=True),
    "嘉義縣議會第 20 屆第 21 次臨時會\n" + turn("林岱杰議員", "臨時會的發言不算。") * 5,
]

PEOPLE = [("p1", "林岱杰", True), ("p2", "蔡奇璋", True), ("p3", "黃嫈珺", True), ("p4", "詹琬蓁", False)]


def new_conn(tmp):
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand in PEOPLE:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "cyq_councilor", "district_id": "cyq-council-02"},
                    "https://u", "t", date="2022-12-25")
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "cyq-council-02"}, "https://u", "t")
    return conn


VOLUMES = [{"sn": 17608, "session": "第20屆第7次定期會", "nth": 7, "files": [("下冊.pdf", URL)]}]


def build(pages=PAGES, written=False):
    with tempfile.TemporaryDirectory() as tmp:
        logs = []
        out = cyq_book.build(new_conn(tmp), VOLUMES, {URL: pages}, logs.append)
    return (out[-1] if written else out[:-1]), logs  # written：只回「改採書面質詢」facts


class TestCyqDays(unittest.TestCase):
    def test_day_runs_from_divider_to_chapter_end(self):
        logs = []
        days = cyq_book.parse_days(PAGES, "x", logs.append)
        self.assertEqual([(d["date"], [p for p, _, _ in d["pages"]]) for d in days], [("2026-05-26", [5, 6, 7, 8])])
        self.assertEqual([pr for _, pr, _ in days[0]["pages"]], [1721, 1722, 1723, 9999])
        self.assertTrue(any("PDF 第 9 頁頁首不是「質詢與答覆」" in x for x in logs))

    def test_day_whose_recorder_date_differs_is_dropped(self):
        pages = PAGES[:4] + [PAGES[4].replace("115.05.26", "115.05.25")] + PAGES[5:]
        logs = []
        self.assertEqual(cyq_book.parse_days(pages, "x", logs.append), [])
        self.assertTrue(any("記錄日期 115.05.25 與分隔頁不同" in x for x in logs))

    def test_toc_days(self):
        self.assertEqual(cyq_book.toc_days(PAGES), {"2026-05-25", "2026-05-26"})


class TestCyqEntries(unittest.TestCase):
    def test_attaches_by_own_label_and_links_first_label_page_with_printed_page(self):
        (ts, entries, status, by_pid), logs = build()
        k, d, url, date = by_pid["p1"][0]
        self.assertEqual((k, date, url), ("cyqbook:2026-05-26:p1", "2026-05-26", URL + "#page=6"))
        self.assertEqual((d["page"], d["printed_page"], d["councillors"], d["doc_type"]), (6, 1722, ["林岱杰"], "縣政總質詢紀錄"))
        self.assertEqual(d["title"], "質詢與答覆紀錄（議事錄第 1722 頁起；依錄音摘要整理）")
        self.assertNotIn("逐字", d["title"])
        self.assertEqual(by_pid["p2"][0][1]["page"], 5)

    def test_interjection_below_min_turns_is_not_collected(self):
        (ts, entries, status, by_pid), logs = build()
        self.assertNotIn("p3", by_pid)
        self.assertTrue(any("黃嫈珺 發言標籤只有 1 段" in x for x in logs))

    def test_unknown_name_and_non_candidate_are_not_collected(self):
        (ts, entries, status, by_pid), logs = build()
        self.assertTrue(any("王小明：名錄沒有此人" in x for x in logs))
        self.assertEqual(set(by_pid), {"p1", "p2"})

    def test_printed_page_disagreeing_with_day_offset_falls_back_to_pdf_page(self):
        pages = PAGES[:4] + [PAGES[4].replace(turn("蔡奇璋議員", "第二題。"), "")] + PAGES[5:]
        pages[5] = pages[5].replace(turn("蔡奇璋議員", "第三題。"), "")
        pages[7] = page(9999, turn("蔡奇璋議員", "第二題。") * 3, even=True)
        (ts, entries, status, by_pid), logs = build(pages)
        d = by_pid["p2"][0][1]
        self.assertEqual((d["page"], d["printed_page"]), (5, 1721))
        logs = []
        days = cyq_book.parse_days(pages, "x", logs.append)
        self.assertIsNone(cyq_book.printed_page(days[0], 8, "x", logs.append))
        self.assertIn("議事錄 PDF 第 8 頁起", cyq_book.facts(
            [{"name": "林岱杰", "session": "s", "roc": "r", "date": "d", "url": URL, "page": 8, "printed": None}],
            {"林岱杰": ["p1"]}, {"p1"}, logs.append)["p1"][0][1]["title"])

    def test_garbled_volume_without_chapter_is_reported(self):
        garbled = ["ಃ 31 ۛ ಃ ۛ ಃ ۛ ಃ ۛ ಃ ۛ ಃ ۛ ಃ ۛ ಃ ۛ 第" * 3] * 4
        (ts, entries, status, by_pid), logs = build(garbled)
        self.assertEqual(status[URL], "文字層亂碼")
        self.assertTrue(any("每一冊都沒有可讀的質詢與答覆章" in x for x in logs))
        self.assertEqual(cyq_book.text_status(["", " ", "x"]), "掃描影像（幾乎沒有文字層）")

    def test_toc_day_not_parsed_is_logged(self):
        (ts, entries, status, by_pid), logs = build()
        self.assertTrue(any("目錄列有 2026-05-25" in x for x in logs))


class TestCyqList(unittest.TestCase):
    def test_parse_list_keeps_term_20_regular_sessions_and_all_files(self):
        def row(topic, sn, files):
            fs = [{"FileName": u, "SrcFileName": n} for n, u in files]
            return {"主題": topic, "S_N": sn, "Path": "javascript:OpenRelFile(" + json.dumps({"files": fs}, ensure_ascii=False) + ");"}
        data = {"Data": [row("第20屆第7次定期會、第19、20、21次臨時會", 17608, [("上冊.pdf", URL.replace("734438ab", "6f7a5046")), ("下冊.pdf", URL)]),
                         row("第19屆第8次定期會", 9000, [("x.pdf", URL)])]}
        vols = cyq_book.parse_list(data)
        self.assertEqual([(v["session"], [n for n, _ in v["files"]]) for v in vols], [("第20屆第7次定期會", ["上冊.pdf", "下冊.pdf"])])
        bad = {"Data": [row("第20屆第1次定期會", 1, [("x.pdf", "https://evil.example/x.pdf")])]}
        with self.assertRaises(ValueError):
            cyq_book.parse_list(bad)

    def test_timetable_groups_names_by_date_and_ignores_notes(self):
        text = ("                  蔡奇璋   林岱杰   簡嘉億\n115.05.26   (二)   翁聰賢         羅士洋\n"
                "                  張議長明達    陳副議長怡岳\n※ 每人質詢時間 50 分鐘，各議員屆時請準時出席。\n  並同意借用後始得為之。\n")
        self.assertEqual(cyq_book.timetable(text)["2026-05-26"], {"蔡奇璋", "林岱杰", "簡嘉億", "翁聰賢", "羅士洋", "張明達", "陳怡岳"})


if __name__ == "__main__":
    unittest.main()


MINUTES_PAGE = ("嘉義縣議會第 20 屆第 7 次定期會第 9 次會議紀錄\n時間：中華民國115年5月26日上午9時13分\n地點：本會議事廳\n"
                "出席：陳副議長怡岳等28人\n貳、縣政總質詢與業務質詢：蔡奇璋、黃嫈珺（書面質詢）、詹琬蓁（書面質詢）等議員。\n參、散會：上午11時\n")
WRITTEN_PAGES = PAGES[:5] + [
    page(1722, turn("黃嫈珺議員", "我插一句。") + turn("蔡奇璋議員", "第三題。")
         + turn("主席陳副議長怡岳", "好，我們黃嫈珺議員，他要書面質詢。再來蔡奇璋和林岱杰議員，他們兩位書面質詢。")
         + turn("林岱杰議員", "謝謝副議長。") + turn("林岱杰議員", "我的部分就用書面質詢。"), even=True),
] + PAGES[6:] + [MINUTES_PAGE]


class TestCyqWrittenSwitch(unittest.TestCase):
    def test_minutes_annotation_and_chair_naming_make_one_record_per_person_per_day(self):
        wr, logs = build(WRITTEN_PAGES, written=True)
        self.assertEqual(list(wr), ["p3"])  # 詹琬蓁不是候選人
        [(k, d, url, date)] = wr["p3"]
        self.assertEqual((k, date), ("cyqwr:2026-05-26:p3", "2026-05-26"))
        self.assertEqual(d["doc_type"], cyq_book.WRITTEN_DOC)
        self.assertEqual(url, URL + "#page=10")  # 會議紀錄優先於主席發言
        self.assertEqual((d["link_label"], d["title"]), ("議事錄 PDF 第 10 頁", "縣政總質詢：會議紀錄記載書面質詢（書面內容議會未公開）"))

    def test_member_who_also_spoke_that_day_is_not_written(self):
        wr, logs = build(WRITTEN_PAGES, written=True)
        self.assertNotIn("p1", wr)
        self.assertNotIn("p2", wr)
        self.assertTrue(any("蔡奇璋 記載書面質詢，但當天也有口頭質詢" in x for x in logs))

    def test_chair_naming_forms(self):
        d = {"date": "2026-05-26", "roc": "115.5.26", "pages": [(5, 1722, turn("主席張議長明達", "好，陳信文議員他書面質詢，換雅文。")
                                                                    + turn("陳副議長怡岳", "我們陳福成議員，也是書面質詢。蔡政宜和武清山議員，他們三位書面質詢。")
                                                                    + turn("江季珍議員", "我書面質詢，謝謝。"))]}
        logs = []
        self.assertEqual([w["name"] for w in cyq_book.chair_written(d, log=logs.append)], ["陳信文", "陳福成"])
        self.assertTrue(any("沒有逐一點名" in x for x in logs))  # 位數與點名人數不同

    def test_minutes_wrapped_in_parentheses(self):
        p = ("時間：中華民國112年6月5日上午10時4分\n貳、縣政總質詢與業務質詢（蔡信典、黃惠汝等議員，蔡政宜議員書面質詢。）\n參、散會\n"
             "時間：中華民國113年6月7日上午9時\n貳、縣政總質詢與業務質詢:李國勝、黃嫈珺(書面質詢)。\n參、主席裁示\n")
        self.assertEqual([(w["date"], w["name"]) for w in cyq_book.minutes_written([p])],
                         [("2023-06-05", "蔡政宜"), ("2024-06-07", "黃嫈珺")])
