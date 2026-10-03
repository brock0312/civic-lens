import json
import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources.khh_attendance import (fact_data, match_people, parse_bbox, parse_page, parse_table, roster_index,
                                        write_table)

FIXTURE = Path(__file__).parent / "fixtures" / "khh_attendance_242906_bbox.html"
NAMES = ["康裕成", "曾俊傑", "林富寶", "林義迪", "朱信強", "李亞築", "黃明太", "陳明澤", "宋立彬", "黃秋媖"]
LEGEND = "註：○出席△請假◇病假☆公差□公假▽喪假§事假☉缺席"


def page(names, rows, totals, legend=LEGEND, x0=100.0, pitch=12.0):
    """合成一頁新版統計表的字框：姓名直排、每格一個符號字、合計列每欄一個數字（totals[欄] 由上而下）。"""
    w = [(60, 40, 200, 50, "（議員出席情形統計表）"), (60, 70, 300, 80, legend)]
    for j, name in enumerate(names):
        x = x0 + j * pitch
        w += [(x, 100 + 12 * k, x + 10, 110 + 12 * k, c) for k, c in enumerate(name)]
    for r, row in enumerate(rows):
        y = 150 + 12 * r
        w += [(x0 + j * pitch, y, x0 + j * pitch + 10, y + 10, c) for j, c in enumerate(row) if c != " "]
    for j, col in enumerate(totals):
        x = x0 + j * pitch + 5
        for k, n in enumerate(col):
            y = 160 + 12 * len(rows) + 12 * k
            w.append((x - 2.5 * len(str(n)), y, x + 2.5 * len(str(n)), y + 10, str(n)))
    return w


def counts(present, leave=0, sick=0, trip=0, official=0, mourn=0, personal=0, absent=0):
    return [present, leave, sick, trip, official, mourn, personal, absent]


class TestRealTable(unittest.TestCase):
    """第 4 屆第 4 次臨時會（舊版：字框偏移半個字、0 不印、兩位辭職議員的格子劃掉、表下備註有日期數字）。"""

    @classmethod
    def setUpClass(cls):
        cls.t = parse_table(parse_bbox(FIXTURE.read_text(encoding="utf-8")))

    def test_reads_vertical_names_on_both_halves(self):
        self.assertEqual(self.t["meetings"], 7)
        self.assertFalse(self.t["absent_column"])
        self.assertEqual(len(self.t["people"]) + len(self.t["rejected"]), 64)
        for name in ("康裕成", "黃香菽", "張博洋", "范織欽", "高忠德"):
            self.assertIn(name, self.t["people"])

    def test_counts_match_the_printed_table(self):
        p = self.t["people"]
        self.assertEqual((p["白喬茵"]["出席"], p["白喬茵"]["請假"]), (2, 5))
        self.assertEqual((p["黃飛鳳"]["出席"], p["黃飛鳳"]["請假"]), (1, 6))
        self.assertEqual((p["邱俊憲"]["出席"], p["邱俊憲"]["請假"]), (7, 0))
        self.assertNotIn("缺席", p["邱俊憲"])

    def test_struck_out_columns_are_not_taken(self):
        self.assertEqual(sorted(n for n, _, _ in self.t["rejected"]), ["李柏毅", "黃捷"])
        self.assertTrue(all(code == "blank" for _, code, _ in self.t["rejected"]))


class TestParseTable(unittest.TestCase):
    def test_counts_every_category_including_absence(self):
        rows = ["○" * 10, "△☉□○○○○○○○", "○" * 10]
        totals = [counts(2, leave=1)] + [counts(2, absent=1)] + [counts(2, official=1)] + [counts(3)] * 7
        t = parse_table([page(NAMES, rows, totals)])
        self.assertEqual((t["meetings"], t["absent_column"], t["rejected"]), (3, True, []))
        self.assertEqual(t["people"]["曾俊傑"]["缺席"], 1)
        self.assertEqual(t["people"]["林富寶"]["公假"], 1)
        self.assertEqual(t["people"]["黃秋媖"]["出席"], 3)

    def test_column_disagreeing_with_official_totals_is_rejected(self):
        rows = ["△" + "○" * 9, "○" * 10]
        totals = [counts(2)] + [counts(2)] * 9  # 官方合計說康裕成全勤，符號卻有一次請假
        t = parse_table([page(NAMES, rows, totals)])
        self.assertNotIn("康裕成", t["people"])
        self.assertEqual([(n, c) for n, c, _ in t["rejected"]], [("康裕成", "mismatch")])
        self.assertEqual(len(t["people"]), 9)

    def test_duplicate_name_in_one_table_is_rejected(self):
        names = NAMES[:9] + ["康裕成"]
        t = parse_table([page(names, ["○" * 10], [counts(1)] * 10)])
        self.assertNotIn("康裕成", t["people"])
        self.assertIn(("康裕成", "duplicate", "同一份表出現 2 次"), t["rejected"])

    def test_absence_mark_without_absence_column_is_rejected(self):
        legend = "註：○出席△請假◇病假☆公差□公假▽喪假§事假"
        t = parse_table([page(NAMES, ["☉" + "○" * 9], [[1]] * 10, legend=legend)])
        self.assertFalse(t["absent_column"])
        self.assertEqual([(n, c) for n, c, _ in t["rejected"]], [("康裕成", "absent_without_column")])

    def test_pages_of_the_same_half_are_joined(self):
        p1 = page(NAMES, ["○" * 10, "○" * 10], [])
        p2 = page(NAMES, ["△" + "○" * 9], [counts(2, leave=1)] + [counts(3)] * 9)
        t = parse_table([p1, p2])
        self.assertEqual(t["meetings"], 3)
        self.assertEqual(t["people"]["康裕成"]["請假"], 1)


class TestParsePage(unittest.TestCase):
    def test_two_numbers_printed_as_one_word_are_split(self):
        w = page(NAMES, ["○" * 10], [])
        # 舊版：相鄰兩欄的「42」「47」黏成一個字詞，寬度兩欄
        w.append((100.0, 170, 124.0, 180, "4247"))
        w.append((300.0, 400, 340.0, 410, "16295"))  # 頁碼
        got = parse_page(w)["totals"]
        self.assertEqual((got[0], got[1]), ([42], [47]))
        self.assertEqual(len(got), 2)

    def test_number_glued_to_row_label_goes_to_the_first_column(self):
        w = page(NAMES, ["○" * 10], [])
        w.append((88.0, 170, 107.5, 180, "席7"))  # 「席」在欄外、「7」在第一欄
        self.assertEqual(parse_page(w)["totals"], {0: [7]})


def new_conn(tmp):
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    people = [("p1", "邱俊憲", True), ("p2", "康裕成", False), ("p3", "高忠德 Takiludun．Anu", True),
              ("p4", "黃秋媖", True), ("p5", "陳明澤", True), ("p6", "陳明澤", True)]
    for pid, name, cand in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "khh_councilor", "district_id": "khh-council-05"},
                    "https://u", "t", date="2022-12-25")
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "khh-council-05"}, "https://u", "t")
    return conn


class TestMatch(unittest.TestCase):
    def test_only_unique_roster_names_are_matched(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster = roster_index(new_conn(tmp))
        got, skipped = match_people(["邱俊憲", "康裕成", "高忠德", "黄秋媖", "陳明澤", "黃紹庭"], roster,
                                    {"p1", "p3", "p4", "p5", "p6"})
        self.assertEqual(got, {"邱俊憲": "p1", "高忠德": "p3", "黄秋媖": "p4"})  # 康裕成在名錄但沒參選
        self.assertEqual(skipped, [("陳明澤", "名錄同名"), ("黃紹庭", "名錄沒有此人")])

    def test_writes_facts_only_for_candidates(self):
        parsed = {"meetings": 3, "absent_column": True,
                  "people": {n: dict(zip(["出席", "請假", "病假", "公差", "公假", "喪假", "事假", "缺席"], counts(2, sick=1)))
                             for n in ("邱俊憲", "康裕成")},
                  "rejected": [("高忠德", "mismatch", "符號數和合計列不符"), ("黃紹庭", "blank", "有 2 格空白")]}
        item = {"sn": "243650", "session": "第4屆第9次臨時會", "pdf_url": "https://cissearch.kcc.gov.tw/x.pdf"}
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp)
            n, _ = write_table(conn, item, parsed, roster_index(conn), {"p1", "p3"}, "T")
            rows = conn.execute("SELECT * FROM fact WHERE kind = 'attendance'").fetchall()
            gaps = conn.execute("SELECT * FROM fact WHERE kind = 'attendance_excluded'").fetchall()
        self.assertEqual(n, 1)
        self.assertEqual([(r["fact_key"], r["person_id"], r["source_url"]) for r in rows],
                         [("kattend:243650:p1", "p1", "https://cissearch.kcc.gov.tw/x.pdf")])
        d = json.loads(rows[0]["data"])
        self.assertEqual((d["meetings"], d["present"], d["leave"], d["absent"], d["leave_types"]["病假"]), (3, 2, 1, 0, 1))
        self.assertEqual(d["title"], "第4屆第9次臨時會議員出席情形統計表")
        # 被整欄不收的候選人（高忠德）留一筆說明；不在名錄的黃紹庭不寫
        self.assertEqual([(r["fact_key"], r["person_id"], r["source_url"]) for r in gaps],
                         [("kattendx:243650:p3", "p3", "https://cissearch.kcc.gov.tw/x.pdf")])
        self.assertEqual(json.loads(gaps[0]["data"])["reason"], "mismatch")


class TestFactData(unittest.TestCase):
    def test_official_duty_is_separate_from_leave_and_absence_is_none_without_column(self):
        c = {"出席": 40, "請假": 1, "病假": 2, "公差": 1, "公假": 3, "喪假": 0, "事假": 1}
        d = fact_data("第4屆第2次定期大會", 48, c, False)
        self.assertEqual((d["present"], d["leave"], d["duty"], d["absent"]), (40, 4, 4, None))
        self.assertEqual(d["leave_types"]["公假"], 3)


if __name__ == "__main__":
    unittest.main()
