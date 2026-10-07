"""資料不變式：把 docs/HANDOFF.md §3 的網站規則寫成測試，在 CI 的 test job（python -m unittest）擋下違規。

做法：把 repo 內的 data/civic.sql 載入記憶體 SQLite，用 etl.export.export() 匯出到暫存目錄，再檢查 dump 與匯出結果。
只讀不寫：不改資料、不改規則。整個檔只匯出一次（setUpClass），只用標準函式庫。
"""
import csv
import json
import re
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from etl.db import SCHEMA_PATH
from etl.export import export

ROOT = Path(__file__).resolve().parent.parent
DUMP = ROOT / "data" / "civic.sql"
SUMMARIES = ROOT / "data" / "summaries"
SITE = ROOT / "site"
HTTP = re.compile(r"^https?://")
THIRD_PARTY = ("council2026.taiwangogo.tw", "local2026.taiwangogo.tw")


def load_dump(path=DUMP):
    """與 etl.db.open_db 相同的載入方式（禁止 ATTACH、載入時關 FK），但放在記憶體，不碰 data/civic.db。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(path.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def walk(obj, path=()):
    """遞迴列出 (鍵路徑, 鍵, 值)。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path, k, v
            yield from walk(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, path + (i,))


def tracked(pattern):
    """git 追蹤中、符合 pattern 的檔；沒有 git（例如解壓的原始碼）就退回目錄比對。"""
    try:
        out = subprocess.run(["git", "ls-files", "--", pattern], cwd=ROOT, capture_output=True, text=True, check=True)
        return [ROOT / p for p in out.stdout.splitlines()]
    except (OSError, subprocess.CalledProcessError):
        return sorted(ROOT.glob(pattern))


class DataInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = load_dump()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        export(cls.conn, cls.out)
        cls.files = {p.relative_to(cls.out).as_posix(): p.read_text(encoding="utf-8") for p in cls.out.rglob("*.json")}
        cls.json = {k: json.loads(v) for k, v in cls.files.items()}
        cls.candidates = {r[0] for r in cls.conn.execute("SELECT DISTINCT person_id FROM fact WHERE kind = 'candidacy'")}

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def people(self):
        return {k: v for k, v in self.json.items() if k.startswith("people/")}

    # §3 第 2 條：生日不進公開 dump
    def test_birthdays_are_never_in_the_dump_or_the_exported_json(self):
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(person)") if "birth" in r["name"]]
        self.assertTrue(cols, "person 表應有生日欄位可檢查")
        for c in cols:
            n = self.conn.execute(f'SELECT count(*) FROM person WHERE "{c}" IS NOT NULL').fetchone()[0]
            self.assertEqual(n, 0, f"person.{c} 有 {n} 列不是 NULL")
        bad = [(f, "/".join(map(str, p + (k,)))) for f, obj in self.json.items()
               for p, k, _ in walk(obj) if "birth" in str(k).lower()]
        self.assertEqual(bad, [], "匯出 JSON 含生日相關鍵")

    # §3 第 3 條：質詢摘要必須審閱通過才上線
    def test_exported_summaries_come_only_from_approved_sessions(self):
        approved = set()
        for path in sorted(SUMMARIES.glob("14-*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            if (doc.get("review") or {}).get("status") == "approved":
                approved.add(doc["label"])
        bad = [(f, s["data"].get("session")) for f, p in self.people().items()
               for s in p["facts"].get("summary", []) if s["data"].get("session") not in approved]
        self.assertEqual(bad, [], "匯出的摘要來自未核可的會期")

    def test_no_unapproved_summary_file_is_committed(self):
        bad = []
        for path in tracked("data/summaries/14-*.json"):
            status = (json.loads(path.read_text(encoding="utf-8")).get("review") or {}).get("status")
            if status != "approved":
                bad.append((path.name, status))
        self.assertEqual(bad, [], "git 追蹤了 review.status 不是 approved 的摘要檔")

    # 摘要引文的公報原文（cited_text）會點名非公職人員，網站用不到，不進任何公開輸出；審閱者看 data/cache
    def test_citation_excerpts_are_never_published(self):
        bad = [f"civic.sql fact {r['fact_key']}" for r in self.conn.execute("SELECT fact_key, data FROM fact")
               if "cited_text" in (r["data"] or "")]
        bad += [f"export {f}" for f, text in self.files.items() if "cited_text" in text]
        site_data = SITE / "data"
        if site_data.is_dir():  # 本機 ETL 匯出的網站資料（gitignored，CI 上不存在）
            bad += [p.relative_to(ROOT).as_posix() for p in site_data.rglob("*.json")
                    if "cited_text" in p.read_text(encoding="utf-8")]
        bad += [p.relative_to(ROOT).as_posix() for p in tracked("data/summaries/*.json")
                if "cited_text" in p.read_text(encoding="utf-8")]
        self.assertEqual(bad[:20], [], f"{len(bad)} 個公開輸出含 cited_text")

    # §3 第 9 條：網站只呈現 2026 候選人
    def test_people_files_are_exactly_the_2026_candidates(self):
        exported = {k.split("/", 1)[1].removesuffix(".json") for k in self.people()}
        self.assertEqual(len(exported), len(self.candidates))
        self.assertEqual(exported, self.candidates)

    def test_district_files_list_only_candidacy_entries(self):
        bad = [(f, e.get("person_id"), e.get("kind")) for f, d in self.json.items() if f.startswith("districts/")
               for e in d["people"] if e.get("kind") != "candidacy"]
        self.assertEqual(bad, [], "選區檔列了 candidacy 以外的條目")

    def test_every_person_id_in_the_export_has_a_people_file(self):
        have = {k.split("/", 1)[1].removesuffix(".json") for k in self.people()}
        bad = sorted({(f, v) for f, obj in self.json.items() for _, k, v in walk(obj)
                      if k == "person_id" and v not in have})
        self.assertEqual(bad, [], "匯出 JSON 引用了沒有人物檔的 person_id")

    # §3 第 5 條：不顯示「無前科」
    def test_no_clean_record_wording_in_site_sources_or_export(self):
        # 只看頁面實際載入的檔；*.test.mjs 是把這個詞列為禁用字的測試，不會顯示
        sources = [p for p in SITE.rglob("*") if p.is_file() and p.suffix in (".html", ".js", ".css", ".svg", ".json")
                   and not p.name.endswith(".test.mjs") and "data" not in p.relative_to(SITE).parts]
        self.assertTrue(sources)
        bad = [p.relative_to(ROOT).as_posix() for p in sources if "無前科" in p.read_text(encoding="utf-8", errors="ignore")]
        bad += [f for f, text in self.files.items() if "無前科" in text]
        self.assertEqual(bad, [], "出現「無前科」")

    # §3 第 4 條：不轉載第三方前科資料庫（頁尾與 app.js 的網站層級連結是允許的，只查匯出資料）
    def test_exported_data_never_carries_third_party_record_sites(self):
        bad = [(f, host) for f, text in self.files.items() for host in THIRD_PARTY if host in text]
        self.assertEqual(bad, [], "匯出資料含第三方前科資料庫")

    # README「每一筆資料都附原始出處連結與擷取時間」
    def test_every_exported_fact_has_a_source_url_and_fetch_time(self):
        bad = []
        for f, p in self.people().items():
            for kind, facts in p["facts"].items():
                for i, x in enumerate(facts):
                    if not HTTP.match(x.get("source_url") or "") or not x.get("fetched_at"):
                        bad.append((f, kind, i))
        for f, d in self.json.items():
            if f.startswith("districts/"):
                for e in d["people"]:
                    if not HTTP.match(e.get("source_url") or "") or not e.get("fetched_at"):
                        bad.append((f, e.get("person_id")))
                if not HTTP.match(d.get("source_url") or "") or not d.get("fetched_at"):
                    bad.append((f, "district"))
        self.assertEqual(bad[:20], [], f"{len(bad)} 筆缺出處或擷取時間")

    # 結構完整：22 縣市、匯出的村里數等於資料庫的村里數（不寫死，內政部新設或裁併村里不擋部署）、村里引用的選區都存在
    def test_counties_villages_and_district_references_are_complete(self):
        counties = self.json["counties.json"]["counties"]
        self.assertEqual(len(counties), 22)
        districts = {d["district_id"] for c in counties for d in c["districts"]}
        villages = [v for f, obj in self.json.items() if f.startswith("villages/") for v in obj["villages"]]
        in_db = self.conn.execute("SELECT count(DISTINCT villcode) FROM village_district").fetchone()[0]
        self.assertGreater(in_db, 0)
        self.assertEqual(len(villages), in_db)
        bad = sorted({(v["villcode"], did) for v in villages for did in v["districts"].values() if did not in districts})
        self.assertEqual(bad[:20], [], f"{len(bad)} 個村里引用了不存在的選區")

    # §5 第 2 項：人工確認表的每一列都要有確認紀錄，且確實是該縣市的 2026 候選人
    def test_national_identity_rows_are_confirmed_candidates_of_their_county(self):
        cand_iso = {}
        for pid, data in self.conn.execute("SELECT person_id, data FROM fact WHERE kind = 'candidacy'"):
            cand_iso.setdefault(pid, set()).add(json.loads(data)["district_id"].split("-")[0])
        with open(ROOT / "data" / "identity_national.csv", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertTrue(rows)
        bad = []
        for r in rows:
            if not r["confirmed_by"].strip() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["confirmed_at"].strip()):
                bad.append((r["iso"], r["roster_name"], "缺 confirmed_by 或 confirmed_at"))
            if r["iso"] not in cand_iso.get(r["person_id"], set()):
                bad.append((r["iso"], r["roster_name"], f"{r['person_id']} 不是 {r['iso']} 的 2026 候選人"))
        self.assertEqual(bad, [])

    # §4「縣市長狀態重查」的輸入檔：網址都是 https、日期都是 YYYY-MM-DD
    def test_head_status_rows_use_https_and_iso_dates(self):
        with open(ROOT / "data" / "head_status.csv", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertTrue(rows)
        bad = []
        for i, r in enumerate(rows, 2):
            for k, v in r.items():
                v = (v or "").strip()
                if k.endswith("url") and v and not v.startswith("https://"):
                    bad.append((i, k, v))
                if (k == "date" or k.endswith("_at")) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                    bad.append((i, k, v))
            if not r.get("source_url"):
                bad.append((i, "source_url", "（空白）"))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
