import unittest

from etl.db import SCHEMA_PATH, connect, upsert
from etl.sources import national_candidates as nc

# 版面取自 4-1（縣市議員登記彙總表）實際座標：漢字 12pt、拉丁字母 6pt，姓名欄滿格 60pt（277.6–337.6）
NAME_X0, NAME_X1 = 277.6, 337.6
LINE = 15.6  # 儲存格內行距


def word(x0, y0, x1, text):
    return f'<word xMin="{x0}" yMin="{y0}" xMax="{x1}" yMax="{y0 + 12}">{text}</word>'


def centered(text, x_mid, y0):
    width = sum(6 if nc.is_latin(c) or c in "·" or c == " " else 12 for c in text)
    return word(x_mid - width / 2, y0, x_mid + width / 2, text)


def cell(lines, x_mid, center):
    """垂直置中的多行儲存格。"""
    top = center - 6 - (len(lines) - 1) * LINE / 2
    return [centered(t, x_mid, top + i * LINE) for i, t in enumerate(lines)]


def row(center, area, date, names, parties):
    words = cell([area], 136.5, center) + cell([date], 231.1, center)
    words += cell(names, (NAME_X0 + NAME_X1) / 2, center)
    return words + cell(parties, 386.4, center)


def page(rows):
    header = [word(118.8, 82.6, 154.8, "選舉區"), word(207.4, 82.6, 255.4, "登記日期"),
              word(295.6, 82.6, 319.6, "姓名"), word(356.4, 82.6, 416.4, "推薦之政黨"),
              word(463.1, 82.6, 487.1, "備註"), word(120, 41, 470, "115年縣市議員選舉候選人登記彙總表")]
    return '<page width="595.2" height="841.68">' + "".join(header + [w for r in rows for w in r]) + "</page>"


def bbox(*pages):
    return "<doc>" + "".join(pages) + "</doc>"


ROSTER = bbox(
    page([
        row(108.6, "新竹縣第1選舉區", "115/08/31", ["陳凱榮"], ["中國國民黨"]),
        # 姓名 4 行，列中心（登記日期那一行）沒有任何姓名的字
        row(170.0, "新竹縣第12選舉區", "115/09/01", ["林秉君", "kaying．", "kuying．", "kalang"], ["無"]),
        # 長政黨名跨 2 行
        row(230.0, "嘉義市第1選舉區", "115/09/02", ["王小明"], ["小民參政歐巴", "桑聯盟"]),
        # 5 行：拼音被從字中間切開（Adrucangal／j·、Drusaljiya／n 都是滿格）
        row(310.0, "屏東縣第11選舉區", "115/09/03", ["邱登星", "Adrucangal", "j·", "Drusaljiya", "n"], ["中國國民黨"]),
    ]),
    page([
        # 行內原有空白要保留；跨行的漢名與拼音之間補一個半形空白
        row(108.6, "彰化縣第10選舉區", "115/09/02", ["王昌智 Mac", "Lunai"], ["無"]),
        row(160.0, "新竹縣第12選舉區", "115/09/04", ["林筱薇", "Icyang", "Tamana"], ["無"]),
        # 滿格但下一行大寫開頭 → 新的單字
        row(215.0, "屏東縣第1選舉區", "115/09/04", ["許○○", "Zuljezulje", "Qapulu"], ["無"]),
    ]),
)

SUMMARY = """
                              115年縣市議員選舉政黨推薦候選人登記情形彙總表
  選舉區       中國國         民主進      合        選
新竹縣第1選舉區      1     0        0         1        4
新竹縣第12選舉區     0     0        2         2        1
                                                                              經             應
嘉義市第1選舉區      0     0        1         1   額    5
屏東縣第1選舉區      0     0        1         1   推    3
屏東縣第11選舉區     1     0        0         1        1
彰化縣第10選舉區     0     0        1         1        1
"""
SEATS = {"hsq-council-01": 4, "hsq-council-12": 1, "cyi-council-01": 5, "pif-council-01": 3,
         "pif-council-11": 1, "cha-council-10": 1}


class TestParseRoster(unittest.TestCase):
    def setUp(self):
        self.rows = nc.parse_roster(ROSTER)
        self.names = [r["name"] for r in self.rows]

    def test_every_row_is_parsed_in_order(self):
        self.assertEqual([r["area"] for r in self.rows], [
            "新竹縣第1選舉區", "新竹縣第12選舉區", "嘉義市第1選舉區", "屏東縣第11選舉區",
            "彰化縣第10選舉區", "新竹縣第12選舉區", "屏東縣第1選舉區"])

    def test_name_split_over_lines_without_text_on_row_center(self):
        self.assertEqual(self.names[1], "林秉君 kaying．kuying．kalang")

    def test_long_party_name_over_two_lines(self):
        self.assertEqual(self.rows[2]["party"], "小民參政歐巴桑聯盟")
        self.assertEqual(self.names[2], "王小明")

    def test_word_cut_mid_way_is_rejoined_without_space(self):
        self.assertEqual(self.names[3], "邱登星 Adrucangalj·Drusaljiyan")

    def test_space_inside_line_is_kept(self):
        self.assertEqual(self.names[4], "王昌智 Mac Lunai")

    def test_han_and_romanized_name_joined_like_taipei_roster(self):
        self.assertEqual(self.names[5], "林筱薇 Icyang Tamana")

    def test_full_line_followed_by_capital_starts_new_word(self):
        self.assertEqual(self.names[6], "許○○ Zuljezulje Qapulu")

    def test_row_missing_name_raises(self):
        broken = bbox(page([row(108.6, "新竹縣第1選舉區", "115/08/31", [], ["無"])]))
        with self.assertRaises(ValueError):
            nc.parse_roster(broken)


class TestCounts(unittest.TestCase):
    def setUp(self):
        self.rows = nc.parse_roster(ROSTER)

    def test_parse_summary_takes_total_and_seats_despite_interleaved_header_text(self):
        s = nc.parse_summary(SUMMARY)
        self.assertEqual(s["嘉義市第1選舉區"], (1, 5))
        self.assertEqual(s["新竹縣第12選舉區"], (2, 1))

    def test_counts_matching_summary_pass(self):
        nc.check_counts(self.rows, nc.parse_summary(SUMMARY), SEATS)

    def test_count_mismatch_raises(self):
        with self.assertRaises(ValueError):
            nc.check_counts(self.rows[:-1], nc.parse_summary(SUMMARY), SEATS)

    def test_seats_mismatch_with_district_table_raises(self):
        with self.assertRaises(ValueError):
            nc.check_counts(self.rows, nc.parse_summary(SUMMARY), {**SEATS, "hsq-council-01": 5})

    def test_list_order_counts_within_district(self):
        got = [(r["district_id"], r["office"], r["list_order"]) for r in nc.with_order(self.rows, "councilor")]
        self.assertEqual(got[1], ("hsq-council-12", "hsq_councilor", 1))
        self.assertEqual(got[5], ("hsq-council-12", "hsq_councilor", 2))

    def test_district_for_rejects_mayor_area_in_council_table(self):
        self.assertEqual(nc.district_for("嘉義市", "mayor"), ("cyi-mayor", "cyi_mayor"))
        with self.assertRaises(ValueError):
            nc.district_for("嘉義市", "councilor")


class TestTaipeiCrossCheck(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        upsert(self.conn, "person", {"person_id": "p1", "name": "林筱薇 Icyang Tamana"}, ("person_id",))
        upsert(self.conn, "person_source_id", {"source": "tpe_reg_2026", "source_key": "tpe-council-07:林筱薇 Icyang Tamana",
                                               "person_id": "p1", "verified_by": "t"}, ("source", "source_key"))

    def test_same_taipei_list_passes(self):
        rows = [{"district_id": "tpe-council-07", "name": "林筱薇 Icyang Tamana"},
                {"district_id": "hsq-council-01", "name": "陳凱榮"}]
        self.assertEqual(nc.check_taipei(self.conn, rows), 1)

    def test_different_taipei_name_raises(self):
        with self.assertRaises(ValueError):
            nc.check_taipei(self.conn, [{"district_id": "tpe-council-07", "name": "林筱薇IcyangTamana"}])


if __name__ == "__main__":
    unittest.main()
