import unittest

from etl import bulletin_grid as bg


def gray(w, h, hs=(), vs=()):
    """白底灰階頁，hs 是整列深色的 y，vs 是整欄深色的 x。"""
    px = bytearray([255]) * (w * h)
    for y in hs:
        px[y * w:(y + 1) * w] = bytes(w)
    for x in vs:
        for y in range(h):
            px[y * w + x] = 0
    return w, h, bytes(px)


def word(x0, y0, x1, y1, t):
    return (x0, y0, x1, y1, t)


class LinesTest(unittest.TestCase):
    def test_finds_rules_and_per_band_columns(self):
        w, h, px = gray(100, 80, hs=(10, 40, 70), vs=(5, 30, 95))
        mask = px.translate(bg.DARK)
        self.assertEqual(bg.h_lines(mask, w, h), [(10, 10), (40, 40), (70, 70)])
        self.assertEqual(bg.v_lines(mask, w, 13, 38), [(5, 5), (30, 30), (95, 95)])

    def test_short_dark_runs_are_not_rules(self):
        w, h, px = gray(100, 80)
        px = bytearray(px)
        px[20 * w:20 * w + 20] = bytes(20)  # 20% 頁寬的字筆畫
        mask = bytes(px).translate(bg.DARK)
        self.assertEqual(bg.h_lines(mask, w, h), [])

    def test_vertical_line_only_inside_one_band_splits_only_that_band(self):
        w, h, px = gray(100, 80, hs=(10, 40, 70), vs=(5, 95))
        px = bytearray(px)
        for y in range(41, 70):
            px[y * w + 50] = 0
        page = bg.Page((w, h, bytes(px)))
        bands = page.bands(page.rules)
        self.assertEqual(len(bands), 2)
        self.assertEqual(len(bands[0][2]), 1)
        self.assertEqual(len(bands[1][2]), 2)


class CellTextTest(unittest.TestCase):
    def test_vertical_cell_reads_right_to_left_then_top_down(self):
        ws = [word(20, 0, 30, 10, "臺"), word(20, 10, 30, 20, "灣"), word(5, 0, 15, 10, "省"), word(5, 10, 15, 20, "府")]
        self.assertEqual(bg.cell_text(ws, 0, 0, 35, 200), "臺灣\n省府")

    def test_vertical_cell_keeps_slightly_offset_digits_in_the_same_column(self):
        # 苗栗：直排生日裡的橫寫數字比單字偏左
        ws = [word(360, 380, 383, 403, "年"), word(349, 380, 372, 403, "47"), word(360, 426, 383, 449, "月"),
              word(349, 426, 372, 449, "12"), word(360, 472, 383, 495, "日"), word(355, 472, 366, 495, "5")]
        self.assertEqual(bg.cell_text(ws, 340, 300, 390, 580), "47年12月5日")

    def test_wide_cell_reads_lines_left_to_right(self):
        ws = [word(50, 0, 90, 10, "國小"), word(0, 0, 40, 10, "啟文"), word(0, 20, 40, 30, "國中")]
        self.assertEqual(bg.cell_text(ws, 0, 0, 200, 50), "啟文 國小\n國中")


class HeaderTest(unittest.TestCase):
    LABELS = ["號次", "相片", "姓名", "出生年月日", "性別", "出生地", "推薦之政黨", "學歷", "經歷", "政見"]

    def cells(self, labels, x=0):
        return [(x + i * 10, x + i * 10 + 9, t) for i, t in enumerate(labels)]

    def test_maps_fields_without_district_column(self):
        (g,) = bg.header_groups(self.cells(self.LABELS))
        self.assertEqual([f for _, _, f in g], ["no", "photo", "name", "birth", "sex", "birthplace", "party",
                                                "education", "experience", "platform"])

    def test_maps_district_column_and_split_labels(self):
        labels = ["選舉\n區別", "號次", "相 片", "姓名", "出 生\n年月日", "性\n別", "出生地", "推薦之\n政 黨", "學 歷", "經 歷", "政 見"]
        (g,) = bg.header_groups(self.cells(labels))
        self.assertEqual(g[0][2], "district")
        self.assertEqual(g[4][2], "birth")
        self.assertEqual(g[6][2], "birthplace")

    def test_two_tables_on_one_page_become_two_groups(self):
        g1, g2 = bg.header_groups(self.cells(self.LABELS) + self.cells(self.LABELS, x=200))
        self.assertEqual(g1[0], (0, 9, "no"))
        self.assertEqual(g2[0], (200, 209, "no"))

    def test_data_row_is_not_a_header(self):
        self.assertEqual(bg.header_groups(self.cells(["1", "", "黃榮利", "44年1月4日", "男", "臺灣省嘉義縣", "無"])), [])


class ParseTest(unittest.TestCase):
    def test_roc_birth_year(self):
        self.assertEqual(bg.roc_birth_year("44年1月4日"), 1955)
        self.assertEqual(bg.roc_birth_year("１０１年\n２月\n３日"), 2012)
        self.assertIsNone(bg.roc_birth_year("年月日\n47125"))
        self.assertEqual(bg.roc_birth_year("54年l月6日"), 1965)
        self.assertEqual(bg.roc_birth_year("79年6年29日"), 1990)

    def test_garble_ratio(self):
        self.assertEqual(bg.garble_ratio("1.爭取（市區）道路拓寬，A+計畫！"), 0.0)
        self.assertGreater(bg.garble_ratio("Ǹ࿎ߦѱ۬൧ख़٠٩ൻ政見"), bg.GARBLE_MAX)

    def test_section_of(self):
        self.assertEqual(bg.section_of("第一選舉區（苗栗市、公館鄉）"), ("councilor", 1))
        self.assertEqual(bg.section_of("第十五選舉區平地原住民議員候選人"), ("councilor", 15))
        self.assertEqual(bg.section_of("市長候選人"), ("mayor", None))
        self.assertIsNone(bg.section_of("第一、九選舉區"))


def px_word(x0, y0, x1, y1, t):
    """以 100 dpi 像素給字框，轉成 pt。"""
    return tuple(v * bg.S for v in (x0, y0, x1, y1)) + (t,)


class BFamilyTest(unittest.TestCase):
    # 合成一頁 B 家族：兩位候選人、各有選區標題；每人上帶（號次｜標籤｜值｜標籤｜值，標籤與值欄在 y=60 有短橫線）
    # 與下帶（經歷｜內容｜政見｜內容）。
    V = (5, 30, 60, 100, 130, 195)

    def page(self):
        w, h, px = gray(200, 300, hs=(40, 80, 120, 160, 200, 240), vs=self.V)
        px = bytearray(px)
        for y in (60, 180):  # 只橫過標籤與值欄的短橫線，不切過號次欄
            px[y * w + 30:y * w + 195] = bytes(165)
        words = []
        for dy, title, name in ((0, "第十二選舉區候選人", "王小明"), (120, "第十三選舉區候選人", "李大華")):
            words += [px_word(10, 20 + dy, 150, 30 + dy, title),
                      px_word(8, 42 + dy, 27, 50 + dy, "號次"), px_word(12, 60 + dy, 22, 75 + dy, "1"),
                      px_word(33, 45 + dy, 57, 55 + dy, "姓名"), px_word(63, 45 + dy, 97, 55 + dy, name),
                      px_word(33, 65 + dy, 57, 75 + dy, "出生年月日"), px_word(63, 65 + dy, 97, 75 + dy, "48年9月25日"),
                      px_word(103, 45 + dy, 127, 55 + dy, "性別"), px_word(135, 45 + dy, 150, 55 + dy, "男"),
                      px_word(103, 65 + dy, 127, 75 + dy, "推薦之政黨"), px_word(135, 65 + dy, 150, 75 + dy, "無"),
                      px_word(8, 90 + dy, 27, 110 + dy, "經歷"), px_word(33, 95 + dy, 57, 105 + dy, "里長"),
                      px_word(63, 90 + dy, 97, 110 + dy, "政見"), px_word(103, 95 + dy, 127, 105 + dy, "修路")]
        return [{"words": words}], [(w, h, bytes(px))]

    def test_short_rule_splits_label_and_value_cells(self):
        page = bg.Page(self.page()[1][0])
        self.assertEqual(len(page.sub_rows(30 * bg.S, 60 * bg.S, 41 * bg.S, 80 * bg.S)), 2)
        self.assertEqual(len(page.sub_rows(5 * bg.S, 30 * bg.S, 41 * bg.S, 80 * bg.S)), 1)

    def test_upper_part_is_split_by_labels(self):
        row = bg.cut_pages_b(*self.page())[0]
        got = {f: bg._text(parts) for f, parts in row["fields"].items()}
        self.assertEqual(got, {"no": "1", "name": "王小明", "birth": "48年9月25日", "sex": "男", "party": "無",
                               "experience": "里長", "platform": "修路"})

    def test_birth_value_is_not_read_as_a_label(self):
        # 「48年9月25日」含「年月日」：已是值的格不能再當標籤，把右邊的「性別」格吃掉
        cell = lambda x0, x1, y0, y1, t: ((x0, y0, x1, y1), [word(x0 + 1, y0 + 1, x1 - 1, y1 - 1, t)])
        cols = [[cell(0, 10, 0, 10, "姓名"), cell(0, 10, 10, 20, "出生年月日")],
                [cell(10, 40, 0, 10, "王小明"), cell(10, 40, 10, 20, "48年9月25日")],
                [cell(40, 50, 0, 20, "性別")], [cell(50, 60, 0, 20, "男")]]
        f = bg.pair_labels(cols)
        self.assertEqual(bg._text(f["birth"]), "48年9月25日")
        self.assertEqual(bg._text(f["sex"]), "男")

    def test_merged_file_is_segmented_by_district_titles(self):
        rows = bg.cut_pages_b(*self.page())
        self.assertEqual([(r["title"], bg._text(r["fields"]["name"])) for r in rows],
                         [(("councilor", 12), "王小明"), (("councilor", 13), "李大華")])


if __name__ == "__main__":
    unittest.main()
