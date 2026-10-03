import unittest
from unittest import mock

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


class FitsTest(unittest.TestCase):
    GROUP = [(10, 50, "no"), (50, 100, "name"), (100, 200, "platform")]

    def test_row_with_slightly_shifted_divider_still_fits(self):
        self.assertTrue(bg._fits(self.GROUP, [(10, 50), (50, 105), (105, 200)]))

    def test_other_table_does_not_fit(self):
        self.assertFalse(bg._fits(self.GROUP, [(10, 30), (30, 120), (120, 200)]))


class BlankGlyphTest(unittest.TestCase):
    SVG = """<defs><g><g id="glyph-0-0"><path d="M 0 0 L 1 1"/></g><g id="glyph-1-0">
</g></g></defs><g fill="rgb(0%,0%,0%)"><use xlink:href="#glyph-0-0" x="332.1" y="1931.7"/>
<use xlink:href="#glyph-1-0" x="298.983576" y="1959.088016"/></g>"""

    def test_finds_origins_of_glyphs_without_outline(self):
        self.assertEqual(bg.blank_glyphs(self.SVG), [(298.983576, 1959.088016)])

    def test_drops_single_char_word_drawn_with_blank_glyph(self):
        # 高雄：空字形「媖」疊在「湯詠瑜」的姓名格裡
        ghost, real = word(299.0068, 1929.4563, 332.0068, 1964.1063, "媖"), word(332.1, 1896.7, 367.1, 1931.7, "瑜")
        self.assertEqual(bg.drop_blank([ghost, real], bg.blank_glyphs(self.SVG)), [real])

    def test_keeps_word_under_a_line_of_blank_spaces(self):
        # 南投：上一行空白字元（空字形）的基線剛好落在「洪」字框上緣
        hung = word(298.6, 1958.0, 341.6, 2001.0, "洪")
        self.assertEqual(bg.drop_blank([hung], bg.blank_glyphs(self.SVG)), [hung])

    def test_blank_glyph_sharing_origin_with_a_drawn_glyph_is_ignored(self):
        # 嘉義市：字前面有不佔寬度的空白（空字形），原點與「嘉」相同
        svg = self.SVG + '<use xlink:href="#glyph-0-0" x="299.2" y="1959.3"/>'
        self.assertEqual(bg.blank_glyphs(svg), [])

    def test_keeps_blank_bullet(self):
        # 臺南：文字層的「•」是空字形，看得見的圓點是另一個字形；「•」要留著，-raw 才對得上
        bullet = word(298.5, 1950, 309.5, 1961.5, "•")
        self.assertEqual(bg.drop_blank([bullet], bg.blank_glyphs(self.SVG)), [bullet])


class VerticalFontTest(unittest.TestCase):
    # 新竹市第 1 區第 1 頁實測：直排字型（Identity-V）的「臺灣省新竹市」字框 902.4–917.4，字形原點在 895.5、
    # 基線 420.3 起每 15pt 一字；橫排字型的「49」字框左緣就是字形原點
    BIRTHPLACE = word(902.4239, 392.2741, 917.4239, 482.2741, "臺灣省新竹市")
    YEAR = word(864.4889, 407.2891, 877.9889, 422.2891, "49")
    GLYPHS = [(895.522989, 420.294131 + 15 * i) for i in range(6)] + [(864.351337, 420.294131), (871.098448, 420.294131)]

    def test_vertical_font_box_moves_onto_its_glyphs(self):
        (fixed,) = bg.fix_vertical([self.BIRTHPLACE], self.GLYPHS)
        self.assertAlmostEqual(fixed[0], 895.522989)
        self.assertAlmostEqual(fixed[1], 420.294131 - 0.87 * 15)
        self.assertAlmostEqual(fixed[3] - fixed[1], 90)
        self.assertEqual(fixed[4], "臺灣省新竹市")

    def test_word_with_a_glyph_on_its_left_edge_is_not_moved(self):
        self.assertEqual(bg.fix_vertical([self.YEAR], self.GLYPHS), [self.YEAR])

    def test_glyph_slightly_left_of_the_box_edge_counts_as_on_the_edge(self):
        # 金門縣長表頭「見」：字形原點比字框左緣偏左 1.2pt，左下方另有一行橫排字；不能搬
        see = word(1305.253, 123.2111, 1331.253, 197.4151, "見")
        self.assertEqual(bg.fix_vertical([see], [(1304.05268, 169.853414), (1288.954275, 219.259009)]), [see])

    def test_too_few_glyphs_in_the_column_is_not_moved(self):
        self.assertEqual(bg.fix_vertical([self.BIRTHPLACE], self.GLYPHS[:3]), [self.BIRTHPLACE])

    def test_ink_check_uses_the_moved_box(self):
        # 墨跡只畫在字形實際位置（895–910pt）：原字框右半在空白處，中段沒有墨跡會被當成看不見的文字
        g = bytearray([255]) * (1300 * 700)
        for y in range(int(405 * 100 / 72), int(495 * 100 / 72)):
            g[y * 1300 + int(896 * 100 / 72):y * 1300 + int(901 * 100 / 72)] = bytes(int(5 * 100 / 72))
        page = (1300, 700, bytes(g))
        (fixed,) = bg.fix_vertical([self.BIRTHPLACE], self.GLYPHS)
        self.assertEqual(bg.suspect_words([self.BIRTHPLACE], page), {self.BIRTHPLACE})
        self.assertEqual(bg.suspect_words([fixed], page), set())


    def test_blank_ghost_does_not_make_the_moved_name_look_stacked(self):
        # 高雄：姓名「柔」是直排字型，搬到字形位置後和左邊空字形的「媖」重疊；「媖」會被丟掉，「柔」不算疊字
        svg = ('<g id="glyph-0-0"><path d="M 0 0 L 1 1"/></g><g id="glyph-1-0">\n</g>'
               '<use xlink:href="#glyph-0-0" x="314.481872" y="573.8"/><use xlink:href="#glyph-1-0" x="298.98" y="572.0"/>')
        rou, ghost = word(332.0, 508.7, 367.0, 543.7, "柔"), word(299.0, 542.5, 332.0, 577.1, "媖")
        ink = bytearray([255]) * (600 * 900)
        for y in range(int(550 * 100 / 72), int(572 * 100 / 72)):
            ink[y * 600 + int(318 * 100 / 72):y * 600 + int(345 * 100 / 72)] = bytes(int(27 * 100 / 72))
        pg = bg.clean_page({"words": [rou, ghost], "suspect": set()}, svg, (600, 900, bytes(ink)))
        (moved,) = pg["words"]
        self.assertEqual((round(moved[0], 1), moved[4], pg["suspect"], pg["vertical_fixed"]), (314.5, "柔", set(), 1))


class MidTableTitleTest(unittest.TestCase):
    # C 家族一頁：表頭上方「第12選舉區」，第 1 列之後隔一條沒有直線的橫帶印「第13選舉區」，再接第 2 列（高雄合併檔）
    def page(self):
        w, h = 300, 120
        px = bytearray([255]) * (w * h)
        for y in (10, 30, 55, 70, 95):
            px[y * w:(y + 1) * w] = bytes(w)
        for x in (5, 50, 100, 150, 200, 250, 295):
            for y in range(10, 96):
                if x in (5, 295) or not 55 < y < 70:
                    px[y * w + x] = 0
        words = [px_word(10, 2, 80, 8, "第12選舉區")]
        words += [px_word(x + 5, 15, x + 40, 25, t)
                  for x, t in zip((5, 50, 100, 150, 200, 250), ("號次", "姓名", "出生年月日", "推薦之政黨", "學歷", "政見"))]
        words += [px_word(10, 58, 80, 67, "第13選舉區：甲仙區")]
        for y, no, name in ((35, "1", "王小明"), (75, "1", "李大華")):
            words += [px_word(10, y, 40, y + 10, no), px_word(55, y, 95, y + 10, name)]
        return [{"words": words}], [(w, h, bytes(px))]

    def test_title_between_rows_switches_district(self):
        rows = bg.cut_pages(*self.page())
        self.assertEqual([(r["title"], bg._text(r["fields"]["name"])) for r in rows],
                         [(("councilor", 12), "王小明"), (("councilor", 13), "李大華")])


class NameOnlyRejectTest(unittest.TestCase):
    CEC = {("khh", "councilor", 3): {n: {"name": name, "birth_year": 1980, "party": "無黨籍及未經政黨推薦"}
                                     for n, name in ((1, "王小明"), (2, "李大華"), (3, "陳一"), (4, "林二"))}}

    def row(self, no, name, birth="69年1月1日"):
        cell = lambda t: [((0, 0, 10, 10), [word(1, 1, 9, 9, t)] if t else [])]
        return {"page": 1, "box": (0, 0, 10, 10), "district_text": None, "title": None,
                "fields": {"no": cell(no), "name": cell(name), "birth": cell(birth), "party": cell("無")}}

    def run_rows(self, rows):
        page = {"words": [], "images": [], "suspect": set()}
        with mock.patch.object(bg, "pdf_layers", return_value=("", "", "", [None])), \
                mock.patch.object(bg, "parse_pages", return_value=[page]), mock.patch.object(bg, "_svg", return_value=""):
            return bg.process(mock.Mock(**{"read_bytes.return_value": b""}), "khh", [["councilor", 3]], self.CEC, cutter=lambda p, g: rows)

    def test_name_check_comes_after_birth_and_party(self):
        _, _, _, why = bg.identify({**self.row("1", "王大明", "70年1月1日"), "suspect": set()}, "khh", [["councilor", 3]], self.CEC)
        self.assertEqual(why, "出生年不符")

    def test_name_only_rejects_do_not_make_the_file_unreliable(self):
        # 罕用字缺字（「李大」）、姓名格整格是圖：號次、出生年、黨籍都對，只擋該列
        rep = self.run_rows([self.row("1", "王小明"), self.row("2", "李大"), self.row("3", ""), self.row("4", "林二")])
        self.assertFalse(rep["unreliable"])
        self.assertEqual([r["cand_no"] for r in rep["rows"]], [1, 4])

    def test_mostly_empty_name_cells_make_the_file_unreliable(self):
        # 新竹市：直排字框偏移，大多數姓名格切不到字
        rep = self.run_rows([self.row("1", "王小明"), self.row("2", ""), self.row("3", ""), self.row("4", "林二")])
        self.assertFalse(rep["unreliable"])
        rep = self.run_rows([self.row("1", "王小明"), self.row("2", ""), self.row("3", ""), self.row("4", "")])
        self.assertTrue(rep["unreliable"])

    def test_birth_mismatches_still_make_the_file_unreliable(self):
        rep = self.run_rows([self.row("1", "王小明"), self.row("2", "李大華", "70年1月1日"),
                             self.row("3", "陳一", "70年1月1日"), self.row("4", "林二")])
        self.assertTrue(rep["unreliable"])
        self.assertEqual(rep["rows"], [])


class GateFieldTest(unittest.TestCase):
    def test_image_only_cell_is_image_not_blank(self):
        self.assertEqual(bg.gate_field([((0, 0, 100, 100), [])], [(10, 10, 50, 50)], set(), ""), (None, "圖片"))
        self.assertEqual(bg.gate_field([((0, 0, 100, 100), [])], [], set(), ""), (None, "空白"))


class SideLabelTest(unittest.TestCase):
    # 花蓮第 8–10 區：三區各一人，選區名直排印在表格左側框外，三個側標幾乎相連
    def page(self):
        w, h = 300, 130
        px = bytearray([255]) * (w * h)
        for y in (10, 30, 60, 90, 120):
            px[y * w:(y + 1) * w] = bytes(w)
        for x in (50, 100, 150, 200, 250, 295):
            for y in range(10, 121):
                px[y * w + x] = 0
        words = [px_word(x + 5, 15, x + 40, 25, t)
                 for x, t in zip((50, 100, 150, 200, 250), ("號次", "姓名", "出生年月日", "推薦之政黨", "學歷"))]
        for y, label, name in ((30, "縣議員第八選區", "連一龍"), (60, "縣議員第九選區", "吳香蘭"), (90, "縣議員第十選區", "高小成")):
            words += [px_word(40, y + 2, 48, y + 28, label), px_word(55, y + 5, 70, y + 25, "1"),
                      px_word(105, y + 5, 145, y + 25, name)]
        return [{"words": words}], [(w, h, bytes(px))]

    def test_adjacent_side_labels_of_different_districts_are_split(self):
        rows = bg.cut_pages(*self.page())
        self.assertEqual([(bg.section_of(r["district_text"]), bg._text(r["fields"]["name"])) for r in rows],
                         [(("councilor", 8), "連一龍"), (("councilor", 9), "吳香蘭"), (("councilor", 10), "高小成")])


class MixedScriptNameTest(unittest.TestCase):
    CEC = {("hua", "councilor", 6): {1: {"name": "何進雄 Kin Cian．Ri Pun", "birth_year": 1969, "party": "中國國民黨"},
                                     2: {"name": "林正福", "birth_year": 1965, "party": "中國國民黨"},
                                     3: {"name": "黃月娥 Yuma’Baysu’", "birth_year": 1969, "party": "中國國民黨"}}}

    def row(self, no, name):
        cell = lambda t: [((0, 0, 10, 10), [word(1, 1, 9, 9, t)])]
        return {"fields": {"no": cell(no), "name": cell(name), "birth": cell("58年11月4日"), "party": cell("中國國民黨")},
                "district_text": "第六選區", "title": None, "suspect": set()}

    def test_cjk_first_keeps_order_within_each_script(self):
        self.assertEqual(bg.cjk_first("Kin何進雄Cian•RiPun"), "何進雄KinCian•RiPun")

    def test_interleaved_aboriginal_name_matches(self):
        self.assertIsNone(bg.identify(self.row("1", "Kin何進雄Cian•RiPun"), "hua", [["councilor", 6]], self.CEC)[3])

    def test_reordering_does_not_excuse_a_different_name(self):
        self.assertEqual(bg.identify(self.row("1", "Kin何進雄Cian•Ri"), "hua", [["councilor", 6]], self.CEC)[3], "姓名不符")

    def test_apostrophe_variants_are_the_same_character(self):
        for a in ("'", "’", "‘", "＇"):
            self.assertIsNone(bg.identify(self.row("3", f"黃月娥Yuma{a}Baysu{a}"), "hua", [["councilor", 6]], self.CEC)[3], a)

    def test_apostrophe_read_as_comma_is_still_rejected(self):
        self.assertEqual(bg.identify(self.row("3", "黃月娥Yuma，Baysu，"), "hua", [["councilor", 6]], self.CEC)[3], "姓名不符")

if __name__ == "__main__":
    unittest.main()
