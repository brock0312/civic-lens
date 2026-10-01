import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert, upsert_fact
from etl.sources import tpe_bulletin_2022 as b

FIXTURES = Path(__file__).parent / "fixtures"
# 2022 臺北市議員第 02 區公報：第 1 頁前兩列 4 格、第 2 頁第一列 2 格（第 2 頁拿掉標題，測跨頁沿用選區）
BBOX = (FIXTURES / "bulletin2022_tp02_bbox.html").read_text(encoding="utf-8")
IMAGES = (FIXTURES / "bulletin2022_tp02_images.xml").read_text(encoding="utf-8")
RAW = (FIXTURES / "bulletin2022_tp02_raw.txt").read_text(encoding="utf-8")
INKED = (2200, 3000, bytes(2200 * 3000))  # 全黑：每個字都「看得見」
BLANK = (2200, 3000, b"\xff" * (2200 * 3000))  # 全白：每個字都「看不見」


def pages(gray=INKED):
    return b.parse_pages(BBOX, IMAGES, [gray, gray])


def cands(gray=INKED):
    return {c["no"]: c for c in b.parse_bulletin(pages(gray))}


def cec_row(no, name, year, party):
    return {"cand_no": no, "cand_name": name, "cand_birthyear": year, "party_name": party}


CEC = [
    cec_row(1, "陳志明", "1976", "時代力量"), cec_row(2, "劉榮之", "1977", "新黨"),
    cec_row(3, "江志銘", "1962", "民主進步黨"), cec_row(4, "李明賢", "1973", "中國國民黨"),
    cec_row(9, "吳欣岱", "1987", "台灣基進"), cec_row(10, "李建昌", "1962", "民主進步黨"),
]


class TestParseBulletin(unittest.TestCase):
    def test_splits_cells_across_columns_and_pages(self):
        cs = cands()
        self.assertEqual(sorted(cs), [1, 2, 3, 4, 9, 10])
        self.assertEqual({c["section"] for c in cs.values()}, {"council-2"})  # 第 2 頁沒有標題，沿用第 1 頁
        self.assertEqual(cs[10]["page"], 2)
        self.assertEqual(cs[3]["name"], "江志銘")
        self.assertEqual(cs[3]["birth_date"], "1962-01-01")
        self.assertEqual(cs[3]["party"], "民主進步黨")
        self.assertEqual(cs[4]["birth_date"], "1973-01-01")

    def test_left_platform_keeps_wrapped_lines_in_order_without_right_column(self):
        # -layout 會把江志銘的第 4 點折行「究及後續的工程規劃。」和個人資料、右欄李明賢的政見交錯在一起
        text = cands()[3]["platform"]
        lines = text.split("\n")
        self.assertTrue(lines[0].startswith("1. 放寬南港「產專區」都市更新獎勵的門檻"))
        i = next(k for k, l in enumerate(lines) if l.startswith("4. 立即啟動"))
        self.assertEqual(lines[i + 1], "究及後續的工程規劃。")
        self.assertTrue(lines[-1].endswith("解爭議。"))
        for foreign in ("交通平權", "出生年月日", "民主進步黨", "個人資料"):
            self.assertNotIn(foreign, text)

    def test_platform_text_is_verbatim_substring_of_raw_extraction(self):
        for no in (3, 4, 10):
            self.assertIn(b.squeeze(cands()[no]["platform"]), b.squeeze(RAW))
        self.assertIn("【老得安心】恢復重陽敬老金、擴大敬老卡使用範圍", cands()[4]["platform"])

    def test_image_platform_is_not_collected(self):
        c = cands()[1]
        self.assertIsNone(c["platform"])
        self.assertIn("政見框有圖片（圖片政見不收）", c["notes"])
        self.assertEqual(c["experience"][0], "• 臺灣大學環境工程研究所")

    def test_bulleted_items_join_wrapped_lines_and_unbulleted_column_is_one_item(self):
        cs = cands()
        self.assertEqual(cs[2]["experience"][2], "3. 台北市體育總會 C 級棒球教練 C 級游泳教練 C 級游泳裁判，中國科技大學建築系研究所碩士生，展華影業負責人")
        self.assertEqual(cs[2]["education"], ["德明技術學院企業管理科畢業\n（二年制）"])

    def test_invisible_text_in_identity_area_makes_bulletin_unreliable(self):
        with self.assertRaises(b.UnreliableBulletin):
            b.parse_bulletin(pages(BLANK))

    def test_stacked_text_in_platform_drops_only_that_platform(self):
        ps = pages()
        w = next(w for w in ps[0]["words"] if w[4].startswith("放寬南港"))
        ghost = (w[0], w[1] + 1, w[2], w[3] + 1, "下一格被遮住的政見")
        ps[0]["words"] = ps[0]["words"] + [ghost]
        ps[0]["suspect"] = b.stacked(ps[0]["words"])
        cs = {c["no"]: c for c in b.parse_bulletin(ps)}
        self.assertIsNone(cs[3]["platform"])
        self.assertIn("政見框有看不見或重疊的文字", cs[3]["notes"])
        self.assertIsNotNone(cs[3]["education"])
        self.assertIsNotNone(cs[4]["platform"])

    def test_check_raw_rejects_text_not_found_in_raw_extraction(self):
        cs = list(cands().values())
        kept = {c["no"]: c for c in b.check_raw(cs, RAW)}
        self.assertEqual(kept[3]["platform"], cands()[3]["platform"])
        dropped = {c["no"]: c for c in b.check_raw(cs, RAW.replace("放寬南港", "放寬北投"))}
        self.assertIsNone(dropped[3]["platform"])
        self.assertIn("政見與 pdftotext -raw 對不上", dropped[3]["notes"])


class TestCheckAgainstCec(unittest.TestCase):
    def test_accepts_exact_match_and_normalizes_no_party(self):
        cs = list(cands().values())
        b.check_against_cec(cs, CEC, "第 02 選舉區")
        c = dict(cs[0], party="無")
        b.check_against_cec([c], [cec_row(c["no"], c["name"], c["birth_date"][:4], "無黨籍及未經政黨推薦")], "x")

    def test_raises_when_candidate_list_differs(self):
        cs = list(cands().values())
        with self.assertRaises(ValueError):
            b.check_against_cec(cs, CEC[:-1], "第 02 選舉區")
        with self.assertRaises(ValueError):
            b.check_against_cec(cs, CEC[:-1] + [cec_row(10, "李建章", "1962", "民主進步黨")], "第 02 選舉區")

    def test_raises_when_birth_year_differs(self):
        cs = list(cands().values())
        with self.assertRaises(ValueError):
            b.check_against_cec(cs, CEC[:2] + [cec_row(3, "江志銘", "1963", "民主進步黨")] + CEC[3:], "第 02 選舉區")

    def test_indigenous_name_spacing_is_ignored(self):
        c = dict(next(iter(cands().values())), name="高為人 Sayun Watan")
        b.check_against_cec([c], [cec_row(c["no"], "高為人Sayun Watan", c["birth_date"][:4], c["party"])], "x")


class TestAttachCouncilors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = open_db(Path(self.tmp.name) / "civic.db", Path(self.tmp.name) / "civic.sql")
        for pid, name, birth, district in [
            ("pA", "江志銘", "1962-01-01", "tpe-council-02"),   # 三點都對
            ("pB", "李明賢", "1973-01-02", "tpe-council-02"),   # 生日不同
            ("pC", "李建昌", "1962-01-01", "tpe-council-03"),   # 別區，不處理
        ]:
            upsert(self.conn, "person", {"person_id": pid, "name": name, "birth_date": birth}, ("person_id",))
            upsert(self.conn, "person_source_id",
                   {"source": "tcc14", "source_key": name, "person_id": pid, "verified_by": "x"}, ("source", "source_key"))
            upsert_fact(self.conn, f"office:tcc14:{pid}", pid, "office", {"district_id": district},
                        "https://example.org", "t", date="2022-12-25")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def facts(self):
        return {r[0]: json.loads(r[1]) for r in self.conn.execute("SELECT fact_key, data FROM fact WHERE kind != 'office'")}

    def test_writes_only_when_name_district_and_birth_date_all_match(self):
        incs = b.load_incumbents(self.conn)
        report = b.attach_councilors(self.conn, 2, list(cands().values()), incs, "https://bulletin.example/02.pdf", "t")
        by_name = {r[0]: r for r in report}
        self.assertEqual(set(by_name), {"江志銘", "李明賢"})
        self.assertEqual(by_name["江志銘"][1], ["platform", "profile"])
        self.assertEqual(by_name["李明賢"][1], [])
        self.assertIn("生日不符", by_name["李明賢"][2])
        facts = self.facts()
        self.assertEqual(set(facts), {"platform:2022-local:pA", "profile:2022-local:pA"})
        p = facts["platform:2022-local:pA"]
        self.assertEqual(p["text"], cands()[3]["platform"])
        self.assertEqual((p["election"], p["office"], p["district_id"]), ("2022-local", "tpe_councilor", "tpe-council-02"))
        self.assertEqual(facts["profile:2022-local:pA"]["education"][0], "• 淡江大學日本語文學系碩士")
        row = self.conn.execute("SELECT date, source_url FROM fact WHERE fact_key = 'platform:2022-local:pA'").fetchone()
        self.assertEqual(tuple(row), ("2022-11-26", "https://bulletin.example/02.pdf"))

    def test_skips_incumbent_without_official_birth_date(self):
        self.conn.execute("UPDATE person SET birth_date = NULL WHERE person_id = 'pA'")
        report = b.attach_councilors(self.conn, 2, list(cands().values()), b.load_incumbents(self.conn), "https://x", "t")
        self.assertEqual({r[0]: r[2] for r in report}["江志銘"], "議會個人頁沒有生日")
        self.assertEqual(self.facts(), {})


class TestBulletinUrl(unittest.TestCase):
    def test_percent_encodes_path(self):
        self.assertEqual(
            b.bulletin_url(b.COUNCIL_PDF.format(2)),
            "https://bulletin.cec.gov.tw/01%E9%81%B8%E8%88%89%E5%85%AC%E5%A0%B1/05%E7%9B%B4%E8%BD%84%E5%B8%82%E8%AD%B0%E5%93%A1"
            "/111%E5%B9%B4/01%E8%87%BA%E5%8C%97%E5%B8%82/%E8%87%BA%E5%8C%97%E5%B8%82%E7%AC%AC02%E9%81%B8%E8%88%89%E5%8D%80.pdf",
        )


if __name__ == "__main__":
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main()
