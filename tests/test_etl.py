import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, dump, upsert, upsert_person, upsert_fact
from etl.export import export


class TestEtl(unittest.TestCase):
    def test_fact_without_source_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            upsert_person(conn, "p1", "Alice")

            with self.assertRaises(sqlite3.IntegrityError):
                upsert_fact(conn, "f1", "p1", "candidacy", {}, None, "2024-01-01T00:00:00Z")

            with self.assertRaises(sqlite3.IntegrityError):
                upsert_fact(conn, "f2", "p1", "candidacy", {}, "ftp://x", "2024-01-01T00:00:00Z")

    def test_upsert_fact_updates_existing_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            upsert_person(conn, "p1", "Alice")

            upsert_fact(conn, "f1", "p1", "candidacy", {"v": 1}, "http://a", "2024-01-01T00:00:00Z")
            upsert_fact(conn, "f1", "p1", "candidacy", {"v": 2}, "http://a", "2024-02-01T00:00:00Z")

            rows = conn.execute("SELECT * FROM fact WHERE fact_key = ?", ("f1",)).fetchall()
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(json.loads(row["data"]), {"v": 2})
            self.assertEqual(row["fetched_at"], "2024-02-01T00:00:00Z")

    def test_upsert_person_without_birth_keeps_existing_birth(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            upsert_person(conn, "p1", "Alice", birth_date="1970-01-01", birth_year=1970)
            upsert_person(conn, "p1", "Alicia")

            row = conn.execute("SELECT * FROM person WHERE person_id = 'p1'").fetchone()
            self.assertEqual(tuple(row), ("p1", "Alicia", "1970-01-01", 1970))

    def test_dump_and_reopen_preserves_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "civic.db"
            dump_path = Path(tmp) / "civic.sql"
            conn = open_db(db_path, dump_path)
            upsert_person(conn, "p1", "Alice")
            upsert_fact(conn, "f1", "p1", "candidacy", {"v": 1}, "http://a", "2024-01-01T00:00:00Z")
            conn.commit()
            dump(conn, dump_path)

            db_path2 = Path(tmp) / "civic2.db"
            conn2 = open_db(db_path2, dump_path)

            people = conn2.execute("SELECT * FROM person").fetchall()
            facts = conn2.execute("SELECT * FROM fact").fetchall()
            self.assertEqual(len(people), 1)
            self.assertEqual(len(facts), 1)
            self.assertEqual(people[0]["name"], "Alice")

    def test_dump_contains_no_birth_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            dump_path = Path(tmp) / "civic.sql"
            conn = open_db(Path(tmp) / "civic.db", dump_path)
            upsert_person(conn, "p1", "Alice", birth_date="1970-03-04", birth_year=1970)
            conn.commit()
            dump(conn, dump_path)

            text = dump_path.read_text(encoding="utf-8")
            self.assertIn("""INSERT INTO "person" VALUES('p1','Alice',NULL,NULL);""", text)
            self.assertNotIn("1970", text)

    def test_open_db_rejects_dump_that_attaches_or_writes_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for stmt in ("ATTACH DATABASE '{}' AS x;", "VACUUM INTO '{}';"):
                target = Path(tmp) / "site" / "evil.html"
                target.parent.mkdir(exist_ok=True)
                dump_path = Path(tmp) / "civic.sql"
                dump_path.write_text(stmt.format(target), encoding="utf-8")
                with self.assertRaises(sqlite3.OperationalError):
                    open_db(Path(tmp) / "civic.db", dump_path)
                self.assertFalse(target.exists())

    def test_export_writes_person_and_district_files_and_removes_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            out_dir = Path(tmp) / "out"
            (out_dir / "people").mkdir(parents=True)
            stale = out_dir / "people" / "stale.json"
            stale.write_text("{}", encoding="utf-8")

            _add_district(conn, "tpe-council-01")
            _add_district(conn, "tpe-council-02")
            upsert_person(conn, "p1", "Alice", birth_date="1980-01-01")
            upsert_fact(
                conn, "cand1", "p1", "candidacy",
                {"district_id": "tpe-council-01"}, "http://a", "2024-01-01T00:00:00Z", date="2024-01-01",
            )
            upsert_fact(
                conn, "int1", "p1", "interpellation",
                {"topic": "old"}, "http://a", "2024-01-01T00:00:00Z", date="2023-01-01",
            )
            upsert_fact(
                conn, "int2", "p1", "interpellation",
                {"topic": "new"}, "http://a", "2024-06-01T00:00:00Z", date="2024-06-01",
            )
            conn.commit()

            export(conn, out_dir)

            self.assertFalse(stale.exists())

            person_out = json.loads((out_dir / "people" / "p1.json").read_text(encoding="utf-8"))
            self.assertEqual(person_out["person_id"], "p1")
            self.assertEqual(person_out["name"], "Alice")
            self.assertNotIn("birth_date", person_out)
            self.assertNotIn("birth_year", person_out)
            interps = person_out["facts"]["interpellation"]
            self.assertEqual([f["data"]["topic"] for f in interps], ["new", "old"])

            district_out = json.loads((out_dir / "districts" / "tpe-council-01.json").read_text(encoding="utf-8"))
            self.assertEqual(district_out["district_id"], "tpe-council-01")
            self.assertEqual(district_out["office"], "tpe_councilor")
            self.assertEqual(district_out["seats"], 12)
            self.assertEqual(len(district_out["people"]), 1)
            self.assertEqual(district_out["people"][0]["person_id"], "p1")

            empty = json.loads((out_dir / "districts" / "tpe-council-02.json").read_text(encoding="utf-8"))
            self.assertEqual(empty["people"], [])

    def test_upsert_keeps_fetched_at_when_content_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            upsert_person(conn, "p1", "Alice")
            upsert_fact(conn, "f1", "p1", "candidacy", {"v": 1}, "http://a", "2024-01-01T00:00:00Z")
            upsert_fact(conn, "f1", "p1", "candidacy", {"v": 1}, "http://a", "2024-02-01T00:00:00Z")
            row = conn.execute("SELECT fetched_at FROM fact WHERE fact_key = 'f1'").fetchone()
            self.assertEqual(row["fetched_at"], "2024-01-01T00:00:00Z")

            # NULL → 值 也要算變動
            upsert(conn, "person", {"person_id": "p1", "name": "Alice", "birth_date": None, "birth_year": 1980}, ("person_id",))
            row = conn.execute("SELECT birth_year FROM person WHERE person_id = 'p1'").fetchone()
            self.assertEqual(row["birth_year"], 1980)

    def test_export_rejects_fact_with_unknown_district(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            upsert_person(conn, "p1", "Alice")
            upsert_fact(conn, "c1", "p1", "candidacy", {"district_id": "nope"}, "http://a", "2024-01-01T00:00:00Z")
            with self.assertRaises(ValueError):
                export(conn, Path(tmp) / "out")

    def test_export_writes_one_villages_file_per_county(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            _add_district(conn, "tpe-council-01")
            upsert(conn, "district", {
                "district_id": "ly-tpe-01", "office": "legislator", "name": "臺北市第01選區",
                "seats": 1, "source_url": "http://ly", "fetched_at": "2024-01-01T00:00:00Z",
            }, ("district_id",))
            _add_district(conn, "kee-council-01")
            for villcode, office, district_id, url in [
                ("63000120002", "tpe_councilor", "tpe-council-01", "http://c"),
                ("63000110027", "tpe_councilor", "tpe-council-01", "http://c"),
                ("63000110027", "legislator", "ly-tpe-01", "http://ly"),
                ("10017010001", "kee_councilor", "kee-council-01", "http://k"),
            ]:
                upsert(conn, "village_district", {
                    "villcode": villcode, "office": office, "town": "士林區", "village": "德行里",
                    "district_id": district_id, "source_url": url, "fetched_at": "2024-01-01T00:00:00Z",
                }, ("villcode", "office"))

            (Path(tmp) / "out").mkdir()
            (Path(tmp) / "out" / "villages.json").write_text("{}")  # 舊版全國單檔要被移除

            export(conn, Path(tmp) / "out")

            self.assertFalse((Path(tmp) / "out" / "villages.json").exists())
            self.assertEqual(sorted(p.name for p in (Path(tmp) / "out" / "villages").iterdir()), ["kee.json", "tpe.json"])
            kee = json.loads((Path(tmp) / "out" / "villages" / "kee.json").read_text(encoding="utf-8"))
            self.assertEqual([v["villcode"] for v in kee["villages"]], ["10017010001"])
            self.assertEqual([s["source_url"] for s in kee["sources"]], ["http://k"])
            out = json.loads((Path(tmp) / "out" / "villages" / "tpe.json").read_text(encoding="utf-8"))
            self.assertEqual([v["villcode"] for v in out["villages"]], ["63000110027", "63000120002"])
            self.assertEqual(
                out["villages"][0]["districts"],
                {"tpe_councilor": "tpe-council-01", "legislator": "ly-tpe-01"},
            )
            self.assertEqual(
                [(s["office"], s["source_url"]) for s in out["sources"]],
                [("legislator", "http://ly"), ("tpe_councilor", "http://c")],
            )


class TestFetchIpv4(unittest.TestCase):
    def test_ipv4_connection_uses_the_ipv4_only_connector(self):
        from etl.fetch import _V4Connection, _connect_v4
        self.assertIs(_V4Connection("example.com")._create_connection, _connect_v4)


class TestCountyRosterFlag(unittest.TestCase):
    def test_counties_json_flags_counties_with_councilor_office_facts_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
            for iso in ("nwt", "kee", "ila"):
                upsert(conn, "county", {"iso": iso, "moi_code": "1", "name": iso, "source_url": "http://m",
                                        "fetched_at": "2024-01-01T00:00:00Z"}, ("iso",))
            for did in ("nwt-council-01", "kee-council-01", "ila-mayor"):
                _add_district(conn, did)
            upsert_person(conn, "p1", "甲")
            upsert_fact(conn, "o1", "p1", "office", {"office": "nwt_councilor", "district_id": "nwt-council-01"},
                        "http://a", "2024-01-01T00:00:00Z")
            upsert_fact(conn, "c1", "p1", "candidacy", {"district_id": "kee-council-01"}, "http://a", "2024-01-01T00:00:00Z")
            upsert_fact(conn, "o2", "p1", "office", {"office": "ila_mayor", "district_id": "ila-mayor"},
                        "http://a", "2024-01-01T00:00:00Z")
            export(conn, Path(tmp) / "out")
            out = json.loads((Path(tmp) / "out" / "counties.json").read_text(encoding="utf-8"))
            self.assertEqual({c["iso"]: c["councilor_roster"] for c in out["counties"]},
                             {"nwt": True, "kee": False, "ila": False})


def _add_district(conn, district_id):
    upsert(conn, "district", {
        "district_id": district_id, "office": "tpe_councilor", "name": district_id,
        "seats": 12, "source_url": "http://d", "fetched_at": "2024-01-01T00:00:00Z",
    }, ("district_id",))


if __name__ == "__main__":
    unittest.main()
