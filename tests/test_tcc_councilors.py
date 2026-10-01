import contextlib
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from etl.db import open_db
from etl.sources import tcc_councilors
from etl.sources.tcc_councilors import ROSTER_URL, load_identity, parse_birth_date, parse_roster, write_roster

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = (FIXTURES / "tcc_roster_sample.html").read_text(encoding="utf-8")

IDENTITY_CSV = """source,source_key,person_id,verified_by
tcc14,黃瀞瑩,pA,議會第14屆名錄 vs 2026 登記冊：姓名、選區 tpe-council-01、黨籍 台灣民眾黨一致
tpe_other,林延鳳,pX,別的來源
tcc14,李傅中武,pB,2026 登記冊無同名者（未參選 2026）
"""


class TestTccCouncilors(unittest.TestCase):
    def test_parse_roster_reads_district_from_section_title_and_party_from_logo(self):
        rows = parse_roster(SAMPLE)
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0], {"name": "黃瀞瑩", "district_id": "tpe-council-01", "party": "台灣民眾黨", "sid": "2547"})
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(by_name["苗博雅"], {"name": "苗博雅", "district_id": "tpe-council-06", "party": "社會民主黨", "sid": "2602"})
        self.assertEqual(by_name["李芳儒"]["district_id"], "tpe-council-07")
        self.assertEqual(by_name["李傅中武"]["district_id"], "tpe-council-08")

    def test_parse_roster_rejects_unknown_section(self):
        with self.assertRaises(ValueError):
            parse_roster(SAMPLE.replace('title="第八選區', 'title="第九選區'))

    def test_parse_roster_rejects_member_without_party_logo(self):
        with self.assertRaises(ValueError):
            parse_roster(SAMPLE.replace('alt="社會民主黨">', '>', 1))

    def test_load_identity_keeps_only_requested_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.csv"
            path.write_text(IDENTITY_CSV, encoding="utf-8")
            identity = load_identity(path)
        self.assertEqual(set(identity), {"黃瀞瑩", "李傅中武"})
        self.assertEqual(identity["李傅中武"], ("pB", "2026 登記冊無同名者（未參選 2026）"))

    def test_load_identity_rejects_duplicate_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.csv"
            path.write_text(IDENTITY_CSV + "tcc14,黃瀞瑩,pC,x\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_identity(path)

    def test_write_roster_skips_unmapped_councilors_and_writes_office_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            roster = parse_roster(SAMPLE)
            identity = {"黃瀞瑩": ("pA", "證據A"), "李傅中武": ("pB", "證據B")}
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                mapped = write_roster(conn, roster, identity, "2026-09-28T00:00:00Z")

            self.assertEqual(mapped, {"黃瀞瑩": "pA", "李傅中武": "pB"})
            self.assertIn("苗博雅", out.getvalue())
            self.assertEqual(
                sorted(tuple(r) for r in conn.execute("SELECT person_id, name FROM person")),
                [("pA", "黃瀞瑩"), ("pB", "李傅中武")],
            )
            self.assertEqual(
                sorted(tuple(r) for r in conn.execute("SELECT source, source_key, person_id FROM person_source_id")),
                [("tcc14", "李傅中武", "pB"), ("tcc14", "黃瀞瑩", "pA")],
            )
            facts = conn.execute("SELECT * FROM fact").fetchall()
            self.assertEqual(len(facts), 2)
            fact = conn.execute("SELECT * FROM fact WHERE fact_key = 'office:tcc14:pB'").fetchone()
            self.assertEqual(fact["kind"], "office")
            self.assertEqual(fact["date"], "2022-12-25")
            self.assertEqual(fact["source_url"], ROSTER_URL)
            self.assertEqual(json.loads(fact["data"]), {
                "office": "tpe_councilor", "term": 14, "district_id": "tpe-council-08",
                "party": "中國國民黨", "title": "臺北市議員（第14屆）",
            })

    def test_write_birth_dates_updates_only_birth_date_of_mapped_councilors(self):
        page = (
            '<span id="ContentPlaceHolder1_FormView1_CouncilorNameLabel">黃瀞瑩</span>'
            '<span id="ContentPlaceHolder1_FormView1_BirthdayLabel">民國81年1月1日</span>'
        )
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            conn.execute("INSERT INTO person (person_id, name, birth_year) VALUES ('pA', '黃瀞瑩', 1992)")
            roster = [{"name": "黃瀞瑩", "sid": "2547"}, {"name": "苗博雅", "sid": "2602"}]
            with mock.patch.object(tcc_councilors, "get", return_value=page.encode()) as get, \
                    mock.patch.object(tcc_councilors.time, "sleep"):
                tcc_councilors.write_birth_dates(conn, roster, {"黃瀞瑩": "pA"})
            get.assert_called_once_with("https://www.tcc.gov.tw/Councilor_Content.aspx?n=13898&s=2547")
            self.assertEqual(tuple(conn.execute("SELECT name, birth_date, birth_year FROM person").fetchone()),
                             ("黃瀞瑩", "1992-01-01", 1992))

    def test_parse_birth_date_converts_roc_year_and_checks_name(self):
        page = (
            '<span id="ContentPlaceHolder1_FormView1_CouncilorNameLabel">黃瀞瑩</span>議員<br />'
            '<span id="ContentPlaceHolder1_FormView1_BirthdayLabel">民國81年1月1日</span>'
        )
        self.assertEqual(parse_birth_date(page, "黃瀞瑩"), "1992-01-01")
        with self.assertRaises(ValueError):
            parse_birth_date(page, "林延鳳")
        with self.assertRaises(ValueError):
            parse_birth_date(page.replace("民國81年1月1日", "81/01/01"), "黃瀞瑩")


if __name__ == "__main__":
    unittest.main()
