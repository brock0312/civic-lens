import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import nan_book

LIST = """
<tr><div id="x"><td>第20屆</td>
<td>第7次</td>
<td>定期會</td></div>
<td><a class="subject"></a> 20屆第7次定期會 議事錄 </td>
<td><a class="btn download" href="../../upload/news/202609011615240.pdf" target="_blank"></a></td></tr>
<tr><td>第20屆</td><td>第15、16、17次</td><td>臨時會</td><td>x</td><td><a href="../../upload/news/202603031030050.pdf"></a></td></tr>
<tr><td>第19屆</td><td>第8次</td><td>定期會</td><td>x</td><td><a href="../../upload/news/202305291517200.pdf"></a></td></tr>
"""

S = nan_book.S


def w(x0, y0, x1, y1, text):
    return (x0, y0, x1, y1, text)


def mask(width, height, lines):
    """lines：[(x0, y0, x1, y1)]（像素，含端點）塗黑 → grid() 吃的 (w, h, 0/1 bytes)。"""
    px = bytearray(width * height)
    for x0, y0, x1, y1 in lines:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                px[y * width + x] = 1
    return width, height, bytes(px)


def table(extra=()):
    """三欄表格：垂直線 x=10、60、110、390，全寬水平線 y=20、100、280；extra 加其他線。"""
    lines = [(x, 20, x, 280) for x in (10, 60, 110, 390)] + [(10, y, 390, y) for y in (20, 100, 280)]
    return mask(400, 300, lines + list(extra))


class ListTest(unittest.TestCase):
    def test_parse_list_keeps_term_20_books_with_kind(self):
        books = nan_book.parse_list(LIST)
        self.assertEqual([b["id"] for b in books], ["202609011615240", "202603031030050"])
        self.assertEqual(books[0]["title"], "第20屆第7次定期會議事錄")
        self.assertEqual(books[1]["kind"], "臨時會")


class HeadingTest(unittest.TestCase):
    def test_heading_reads_session_meeting_and_date(self):
        words = [w(60, 75, 500, 93, "南投縣議會第 20 屆第 7 次定期會議員建議事項（第 2 會次）"), w(400, 100, 500, 110, "115 年 4 月 29 日"),
                 w(60, 150, 90, 160, "類別"), w(300, 150, 360, 162, "建議事項")]
        self.assertEqual(nan_book.heading(words), ("第20屆第7次定期會", "第2會次", "2026-04-29", 162))

    def test_heading_accepts_missing_term_char_and_compat_ideographs(self):
        # 第 5 次定期會：表頭漏印「屆」、「年」「類」是相容表意字（U+F98E、U+F9D0）
        text = nan_book.compat("南投縣議會第20第5次定期會議員建議事項（第2會次）114年5月23日")
        words = [w(60, 75, 500, 93, text), w(60, 150, 90, 160, nan_book.compat("類別"))]
        self.assertEqual(nan_book.heading(words)[:3], ("第20屆第5次定期會", "第2會次", "2025-05-23"))
        self.assertEqual(nan_book.compat("（第3會次）？，"), "（第3會次）？，")  # 全形標點不動

    def test_meeting_record_page_is_not_a_heading(self):
        self.assertIsNone(nan_book.heading([w(60, 75, 500, 93, "三、議員建議事項：如附件。")]))


class GridTest(unittest.TestCase):
    def test_grid_finds_columns_and_per_column_rules_for_merged_name_cell(self):
        # y=180 只切過題目欄：姓名、類別格跨兩列（合併儲存格）
        g, why = nan_book.grid(table([(110, 180, 390, 180)]))
        self.assertIsNone(why)
        self.assertEqual([round(x / S) for x in g["cols"]], [10, 60, 110, 390])
        self.assertEqual([[round(y / S) for y in b] for b in g["bounds"]], [[20, 100, 280], [20, 100, 280], [20, 100, 180, 280]])

    def test_grid_rejects_page_without_four_vertical_lines(self):
        lines = [(x, 20, x, 280) for x in (10, 110, 390)] + [(10, y, 390, y) for y in (20, 280)]
        g, why = nan_book.grid(mask(400, 300, lines))
        self.assertIsNone(g)
        self.assertIn("垂直線 3 條", why)


class RowsTest(unittest.TestCase):
    def grid(self, extra=()):
        return nan_book.grid(table(extra))[0]

    def test_merged_name_cell_names_every_text_cell_it_spans(self):
        g = self.grid([(110, 180, 390, 180)])
        words = [w(15 * S, 50 * S, 50 * S, 60 * S, "社政"), w(65 * S, 50 * S, 100 * S, 60 * S, "陳宜君"),
                 w(120 * S, 30 * S, 380 * S, 40 * S, "1.建請擴充使用範"), w(120 * S, 42 * S, 200 * S, 52 * S, "圍。"),
                 w(15 * S, 185 * S, 50 * S, 195 * S, "民政"), w(65 * S, 185 * S, 100 * S, 195 * S, "吳棋楠"),
                 w(120 * S, 120 * S, 380 * S, 130 * S, "第一題"), w(120 * S, 200 * S, 380 * S, 210 * S, "第二題"),
                 w(200 * S, 290 * S, 220 * S, 298 * S, "127")]
        got, why = nan_book.rows(words, g)
        self.assertIsNone(why)
        self.assertEqual(got, [{"text": "1.建請擴充使用範圍。", "cat": "社政", "name": "陳宜君"},
                               {"text": "第一題", "cat": "民政", "name": "吳棋楠"},
                               {"text": "第二題", "cat": "民政", "name": "吳棋楠"}])

    def test_justified_letter_spacing_is_removed_only_between_cjk_characters(self):
        words = [w(120, 30, 380, 40, "2.導 護 老 師 、 志 工 是 否"), w(120, 42, 380, 52, "有 MOU 10 億訂單？"), w(120, 54, 380, 64, "(1) 積 極")]
        self.assertEqual(nan_book.cell_text(words), "2.導護老師、志工是否有 MOU 10 億訂單？(1) 積極")

    def test_name_rule_not_crossing_text_column_rejects_page(self):
        # 姓名欄在 y=180 有格線、題目欄沒有：一格題目跨兩位議員，不能猜
        g = self.grid([(10, 180, 110, 180)])
        got, why = nan_book.rows([], g)
        self.assertIsNone(got)
        self.assertIn("沒有切過題目欄", why)

    def test_word_on_a_rule_rejects_page(self):
        g = self.grid()
        got, why = nan_book.rows([w(120 * S, 95 * S, 380 * S, 105 * S, "壓線")], g)
        self.assertIsNone(got)
        self.assertIn("歸不了格", why)


class AddRowsTest(unittest.TestCase):
    CUR = {"session": "第20屆第7次定期會", "meeting": "第2會次", "date": "2026-04-29"}

    def test_continuation_cell_joins_previous_page_last_row(self):
        out = nan_book.add_rows([], self.CUR, 131, [{"cat": "社政", "name": "蘇昱誠", "text": "2.民眾反映敬老愛心卡叫不到愛心計程車，要"}], False)
        out = nan_book.add_rows(out, self.CUR, 132, [{"cat": "", "name": "", "text": "如何解決？"},
                                                     {"cat": "社政", "name": "林友友", "text": "針對社工"}], True)
        self.assertEqual([(r["page"], r["n"], r["name"], r["text"]) for r in out],
                         [(131, 0, "蘇昱誠", "2.民眾反映敬老愛心卡叫不到愛心計程車，要如何解決？"), (132, 0, "林友友", "針對社工")])

    def test_sentence_split_across_pages_with_reprinted_name_is_joined(self):
        # 第 5 次定期會第 16 會次：跨頁時重印姓名，類別印成另一個；上一列停在句子中間
        out = nan_book.add_rows([], self.CUR, 164, [{"cat": "警政", "name": "張婉慈", "text": "除了加強駕駛觀念外，道"}], False)
        out = nan_book.add_rows(out, self.CUR, 165, [{"cat": "工務", "name": "張婉慈", "text": "路設計更重要。"},
                                                     {"cat": "教育", "name": "張婉慈", "text": "學區"}], True)
        self.assertEqual([(r["cat"], r["text"]) for r in out], [("警政工務", "除了加強駕駛觀念外，道路設計更重要。"), ("教育", "學區")])

    def test_same_name_after_a_finished_sentence_starts_a_new_row(self):
        out = nan_book.add_rows([], self.CUR, 164, [{"cat": "警政", "name": "甲", "text": "完整。"}], False)
        out = nan_book.add_rows(out, self.CUR, 165, [{"cat": "工務", "name": "甲", "text": "另一題"}], True)
        self.assertEqual(len(out), 2)

    def test_blank_first_cell_of_a_new_table_is_not_joined_to_another_meeting(self):
        out = nan_book.add_rows([], self.CUR, 131, [{"cat": "社政", "name": "甲", "text": "a"}], False)
        other = {**self.CUR, "meeting": "第3會次"}
        out = nan_book.add_rows(out, other, 133, [{"cat": "", "name": "", "text": "b"}], True)
        self.assertEqual([(r["meeting"], r["text"]) for r in out], [("第2會次", "a"), ("第3會次", "b")])


def new_conn(tmp, people):
    """people：[(person_id, name, 有 2026 candidacy)]，都是南投縣議員。"""
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "nan_councilor", "district_id": "nan-council-01"},
                    "https://u", "t", date="2022-12-25")
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "nan-council-01"}, "https://u", "t")
    return conn


def row(page, n, cat, name, text, meeting="第2會次"):
    return {"session": "第20屆第7次定期會", "meeting": meeting, "date": "2026-04-29", "page": page, "n": n,
            "cat": cat, "name": name, "text": text}


class FactsTest(unittest.TestCase):
    BOOK = {"id": "202609011615240", "title": "第20屆第7次定期會議事錄", "kind": "定期會"}

    def build(self, rows, withheld=None, people=None):
        people = people or [("p1", "陳宜君", True), ("p2", "林庭秝 Ali Walis", True), ("p3", "簡千翔", True), ("p4", "林儒暘", True),
                            ("p5", "何勝豐", True), ("p6", "李洲忠", True), ("p7", "潘一全", False)]
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, people)
            ts, qs, held, n = nan_book.build(conn, [self.BOOK], {self.BOOK["id"]: rows}, withheld or {}, logs.append)
        return qs, held, n, logs

    def test_each_row_is_one_fact_with_full_official_text_date_and_page_link(self):
        text = "1.有關補助本縣 65 歲以上長者健保費政策，建請透過關懷據點、巷弄長照站多加宣傳、說明。" * 3
        qs, held, n, logs = self.build([row(129, 0, "社政", "陳宜君", text)])
        [(key, data, url, date)] = qs["p1"]
        self.assertEqual(key, "ntccq:202609011615240:129:0:p1")
        self.assertEqual(data["title"], text)
        self.assertEqual((data["doc_type"], data["dept"], data["meeting"]), ("議員建議事項", "社政", "第2會次"))
        self.assertEqual(url, "https://www.ntcc.gov.tw/upload/news/202609011615240.pdf#page=129")
        self.assertEqual(date, "2026-04-29")

    def test_joint_row_glued_names_and_speaker_title_resolve_to_each_councillor(self):
        qs, _, _, logs = self.build([row(187, 1, "警政", "簡千翔林儒暘", "動保"), row(140, 7, "工務", "議長何勝豐", "工務處")])
        self.assertEqual(len(qs["p3"]), 1)
        self.assertEqual(len(qs["p4"]), 1)
        self.assertEqual(qs["p3"][0][1]["councillors"], ["簡千翔", "林儒暘"])
        self.assertEqual(qs["p5"][0][1]["title"], "工務處")
        self.assertEqual(logs, [])

    def test_unknown_or_misspelled_name_is_not_attached(self):
        qs, _, n, logs = self.build([row(151, 0, "工務", "李州忠", "道路")])  # 官方誤植，不模糊比對
        self.assertEqual(qs, {})
        self.assertTrue(any("李州忠：名錄沒有此人" in x for x in logs))

    def test_name_fix_applies_only_to_its_book_page_and_printed_name(self):
        book = {"id": "202512051057560", "title": "第20屆第5次定期會議事錄", "kind": "定期會"}
        rows = [row(151, 6, "環保", "李州忠", "焚化廠"), row(151, 7, "教育", "李州忠", "校長"), row(152, 0, "工務", "李州忠", "道路")]
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, [("p6", "李洲忠", True)])
            _, qs, held, _ = nan_book.build(conn, [book], {book["id"]: rows}, {"202512051057560:151:7": "第三人"}, logs.append)
        [(key, data, _, _)] = qs["p6"]
        self.assertEqual((key, data["councillors"]), ("ntccq:202512051057560:151:6:p6", ["李洲忠"]))
        self.assertEqual([h[0] for h in held], ["202512051057560:151:7"])  # withheld 照舊不收
        self.assertTrue(any("李州忠：名錄沒有此人" in x and "第 152 頁" in x for x in logs))  # 別頁不更正

    def test_blank_name_continues_previous_councillor_of_same_table_only(self):
        qs, _, _, logs = self.build([row(129, 0, "社政", "陳宜君", "a"), row(129, 1, "工務", "", "b"),
                                     row(133, 0, "工務", "", "c", meeting="第3會次")])
        self.assertEqual([d["title"] for _, d, _, _ in qs["p1"]], ["a", "b"])
        self.assertTrue(any("第3會次 PDF 第 133 頁第 1 列沒有議員姓名" in x for x in logs))

    def test_later_verbatim_copy_of_an_earlier_row_is_not_attached(self):
        # 第 6 次定期會第 12 會次照抄第 5 次定期會吳國昌的建議、掛在別人名下：只收最早那一列
        text = "在埔里有業者申請建築廢棄物掩埋場設置，請縣府要嚴格把關。"
        early = {**row(168, 5, "環保", "陳宜君", text), "date": "2025-06-13", "session": "第20屆第5次定期會"}
        late = {**row(197, 4, "環保", "簡千翔", text), "date": "2025-10-29", "session": "第20屆第6次定期會"}
        qs, _, _, logs = self.build([late, early])
        self.assertEqual(len(qs["p1"]), 1)
        self.assertNotIn("p3", qs)
        self.assertTrue(any("完全相同，疑為官方複製，不收" in x for x in logs))

    def test_withheld_rows_and_non_candidates_are_not_written(self):
        qs, held, n, _ = self.build([row(129, 0, "社政", "陳宜君", "a"), row(129, 1, "民政", "潘一全", "b")],
                                    withheld={"202609011615240:129:0": "原因"})
        self.assertEqual(qs, {})
        self.assertEqual([h[0] for h in held], ["202609011615240:129:0"])

    def test_withheld_csv_reads_item_and_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "w.csv"
            p.write_text("item,reason\n202609011615240:129:0,點名非公職第三人＋違法指控\n", encoding="utf-8")
            self.assertEqual(nan_book.load_withheld(p), {"202609011615240:129:0": "點名非公職第三人＋違法指控"})


if __name__ == "__main__":
    unittest.main()
