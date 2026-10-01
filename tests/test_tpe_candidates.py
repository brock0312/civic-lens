import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert, upsert_person
from etl.sources.tpe_candidates import SOURCE, district_id_for, parse_roster, person_id_for, roc_to_iso, write_row

SAMPLE = (Path(__file__).parent / "fixtures" / "tpe_reg_sample.txt").read_text(encoding="utf-8")


class TestTpeCandidates(unittest.TestCase):
    def test_parse_roster_handles_normal_split_party_and_indigenous_rows(self):
        rows = parse_roster(SAMPLE)
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0], {
            "area": "臺北市第1選舉區", "district_id": "tpe-council-01", "date": "2026-08-31",
            "reg_no": 1, "name": "謝閔弘", "party": "時代力量",
        })
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(by_name["李文"]["party"], "無")
        self.assertEqual(by_name["林聖峰"]["party"], "天宙和平統一家庭黨")
        self.assertEqual(by_name["林聖峰"]["reg_no"], 20)
        self.assertEqual(by_name["林筱薇 Icyang Tamana"]["party"], "無")
        self.assertEqual(by_name["林筱薇 Icyang Tamana"]["district_id"], "tpe-council-07")
        self.assertEqual(by_name["孔垂崢 Haisul Islituan"]["district_id"], "tpe-council-08")
        self.assertEqual(by_name["李傅鈺婷"]["party"], "中國國民黨")

    def test_parse_roster_rejects_count_mismatch(self):
        with self.assertRaises(ValueError):
            parse_roster(SAMPLE.replace("列印筆數：10", "列印筆數：11"))

    def test_parse_roster_rejects_duplicate_name_in_same_district(self):
        with self.assertRaises(ValueError):
            parse_roster(SAMPLE.replace("李文", "謝閔弘"))

    def test_parse_roster_rejects_unknown_district(self):
        with self.assertRaises(ValueError):
            parse_roster(SAMPLE.replace("臺北市第2選舉區", "臺北市第9選舉區"))

    def test_roc_date_converts_to_iso(self):
        self.assertEqual(roc_to_iso("115/08/31"), "2026-08-31")
        self.assertEqual(roc_to_iso("99/01/05"), "2010-01-05")

    def test_district_id_for_mayor_and_council(self):
        self.assertEqual(district_id_for("臺北市"), "tpe-mayor")
        self.assertEqual(district_id_for("臺北市第6選舉區"), "tpe-council-06")

    def test_write_row_keeps_existing_birth_date(self):
        row = parse_roster(SAMPLE)[0]
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            _add_district(conn, row["district_id"])
            person_id = person_id_for(conn, f"{row['district_id']}:{row['name']}")
            upsert_person(conn, person_id, row["name"], birth_date="1985-01-02", birth_year=1985)

            write_row(conn, "tpe_councilor", "http://pdf", row, "2026-09-28T00:00:00Z")

            person = conn.execute("SELECT * FROM person WHERE person_id = ?", (person_id,)).fetchone()
            self.assertEqual((person["birth_date"], person["birth_year"]), ("1985-01-02", 1985))
            src = conn.execute("SELECT person_id FROM person_source_id WHERE source = ?", (SOURCE,)).fetchone()
            self.assertEqual(src["person_id"], person_id)


def _add_district(conn, district_id):
    upsert(conn, "district", {
        "district_id": district_id, "office": "tpe_councilor", "name": district_id,
        "seats": 12, "source_url": "http://d", "fetched_at": "2026-09-28T00:00:00Z",
    }, ("district_id",))


if __name__ == "__main__":
    unittest.main()
