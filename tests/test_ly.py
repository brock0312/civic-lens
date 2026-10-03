"""立法院 API 來源（etl.lyapi、ly_legislators、ly_records）。

假資料的欄位名稱取自 openfunltd/ly.govapi.tw-v2 的 LYAPI/Type/*.php；日期寫法、單一選區縣市的選區名稱等值的格式
尚未在本機實測（雲端環境連不到 ly.govapi.tw），本機第一次跑 ETL 時要對照實際回應。
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from etl import lyapi
from etl.db import open_db, upsert, upsert_fact
from etl.sources import ly_legislators, ly_records
from etl.sources.ly_legislators import load_identity, office_data, plan

T = "2026-10-03T00:00:00Z"


def leg(name, area, bio, **kw):
    return {"屆": 11, "委員姓名": name, "選區名稱": area, "歷屆立法委員編號": bio, "黨籍": "民主進步黨",
            "到職日": "2024-02-01", **kw}


def cand(pid, name, did):
    return {"person_id": pid, "name": name, "district_id": did}


def identity_from(text):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "i.csv"
        p.write_text("bio_id,name,person_id,confirmed_by,confirmed_at,note\n" + text, encoding="utf-8")
        return load_identity(p)


class LyApiTest(unittest.TestCase):
    def test_area_maps_district_legislators_and_leaves_others_without_county(self):
        self.assertEqual(lyapi.area("臺南市第6選舉區"), ("tnn", "ly-tnn-06"))
        self.assertEqual(lyapi.area("台中市第2選區"), ("txg", "ly-txg-02"))
        self.assertEqual(lyapi.area("新竹市"), ("hsz", "ly-hsz-01"))
        self.assertEqual(lyapi.area("基隆市選舉區"), ("kee", "ly-kee-01"))
        self.assertEqual(lyapi.area("全國不分區及僑居國外國民"), (None, None))
        self.assertEqual(lyapi.area("平地原住民"), (None, None))
        self.assertEqual(lyapi.area(None), (None, None))

    def test_to_date_accepts_iso_slashes_datetimes_and_roc_years(self):
        self.assertEqual(lyapi.to_date("2024-02-01"), "2024-02-01")
        self.assertEqual(lyapi.to_date("2024/2/1"), "2024-02-01")
        self.assertEqual(lyapi.to_date("2024-10-24T09:00:00+08:00"), "2024-10-24")
        self.assertEqual(lyapi.to_date("113/02/01"), "2024-02-01")
        self.assertIsNone(lyapi.to_date("中華民國114年12月19日"))
        self.assertIsNone(lyapi.to_date(None))

    def test_is_current_drops_other_terms_and_anyone_with_a_leave_record(self):
        self.assertTrue(lyapi.is_current(leg("甲", "臺南市第6選舉區", 1)))
        self.assertTrue(lyapi.is_current(leg("甲", "臺南市第6選舉區", 1, 是否離職="否")))
        self.assertFalse(lyapi.is_current(leg("甲", "臺南市第6選舉區", 1, 屆=10)))
        self.assertFalse(lyapi.is_current(leg("甲", "臺南市第6選舉區", 1, 是否離職="是")))
        self.assertFalse(lyapi.is_current(leg("甲", "臺南市第6選舉區", 1, 離職日期="2025-02-27")))
        self.assertFalse(lyapi.is_current(leg("甲", "臺南市第6選舉區", 1, 離職原因="辭職")))

    def test_fetch_all_pages_until_total_page_and_checks_the_total(self):
        pages = {1: {"total": 3, "total_page": 2, "x": [1, 2]}, 2: {"total": 3, "total_page": 2, "x": [3]}}
        seen = []

        def get(url):
            seen.append(url)
            return pages[int(url.split("page=")[1].split("&")[0])]

        items, first = lyapi.fetch_all("x", {"屆": 11}, limit=2, get=get, sleep=0)
        self.assertEqual(items, [1, 2, 3])
        self.assertEqual(first, seen[0])
        self.assertTrue(first.startswith("https://ly.govapi.tw/v2/x?"))
        with self.assertRaises(ValueError):
            lyapi.fetch_all("x", {}, limit=2, get=lambda u: {"total": 5, "total_page": 1, "x": [1]}, sleep=0)
        with self.assertRaises(ValueError):
            lyapi.fetch_all("x", {}, get=lambda u: {"error": True, "message": "找不到資料"}, sleep=0)

    def test_fetch_all_refuses_to_page_past_the_search_window(self):
        with self.assertRaises(ValueError):
            lyapi.fetch_all("x", {}, limit=5000, get=lambda u: {"total": 20000, "total_page": 4, "x": [0] * 5000}, sleep=0)

    def test_token_header_only_when_the_env_var_is_set(self):
        with mock.patch.dict("os.environ", {"LYAPI_TOKEN": "t"}):
            self.assertEqual(lyapi.headers(), {"Authorization": "Bearer t"})
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(lyapi.headers())


class LyLegislatorsPlanTest(unittest.TestCase):
    def test_auto_links_a_district_legislator_running_in_the_same_county(self):
        rows, review = plan([leg("王大明", "臺南市第6選舉區", 1)], [cand("p1", "王大明", "tnn-mayor")], {})
        self.assertEqual(review, [])
        self.assertEqual(rows[0]["person_id"], "p1")
        self.assertIn("同縣市", rows[0]["verified_by"])

    def test_legislators_not_running_get_no_link_and_no_review(self):
        rows, review = plan([leg("王大明", "臺南市第6選舉區", 1)], [cand("p1", "李小華", "tnn-mayor")], {})
        self.assertEqual((rows[0]["person_id"], review), (None, []))

    def test_everything_short_of_certain_goes_to_review(self):
        cases = [
            (leg("王大明", "臺南市第6選舉區", 1), [cand("p1", "王大明", "khh-mayor")], "other_county"),
            (leg("王大明", "全國不分區及僑居國外國民", 1), [cand("p1", "王大明", "tnn-mayor")], "at_large_or_indigenous"),
            (leg("王大明", "臺南市第6選舉區", 1), [cand("p1", "王大明", "tnn-mayor"), cand("p2", "王大明", "nwt-council-01")],
             "duplicate_name"),
            (leg("王大明Sra", "山地原住民", 1), [cand("p1", "王大明", "hua-mayor")], "romanization_or_variant"),
            (leg("黄大明", "臺南市第6選舉區", 1), [cand("p1", "黃大明", "tnn-mayor")], "romanization_or_variant"),
        ]
        for r, cands, reason in cases:
            rows, review = plan([r], cands, {})
            self.assertIsNone(rows[0]["person_id"], reason)
            self.assertEqual([x["reason"] for x in review], [reason])

    def test_two_sitting_legislators_with_the_same_name_are_never_auto_linked(self):
        rows, review = plan([leg("王大明", "臺南市第6選舉區", 1), leg("王大明", "高雄市第1選舉區", 2)],
                            [cand("p1", "王大明", "tnn-mayor")], {})
        self.assertEqual([x["person_id"] for x in rows], [None, None])
        self.assertEqual({x["reason"] for x in review}, {"duplicate_name"})

    def test_manual_identity_wins_and_is_keyed_by_bio_id(self):
        ident = identity_from("1160,王大明,p9,Claude 初審；verifier 複核,2026-10-03,不分區參選市長\n")
        rows, review = plan([leg("王大明", "全國不分區及僑居國外國民", 1160)], [cand("p1", "王大明", "tnn-mayor")], ident)
        self.assertEqual((rows[0]["person_id"], review), ("p9", []))
        self.assertIn("人工確認", rows[0]["verified_by"])

    def test_identity_file_rejects_duplicates_and_missing_fields_and_may_be_absent(self):
        with self.assertRaises(ValueError):
            identity_from("1,甲,p1,x,2026-10-03,\n1,甲,p2,x,2026-10-03,\n")
        with self.assertRaises(ValueError):
            identity_from("1,甲,p1,,2026-10-03,\n")
        self.assertEqual(load_identity(Path("/nonexistent/identity.csv")), {})

    def test_office_data_keeps_district_only_when_the_district_table_has_it(self):
        d = office_data(leg("王大明", "臺南市第6選舉區", 1), {"ly-tnn-06"})
        self.assertEqual(d, {"office": "legislator", "title": "立法委員", "term": 11, "ly_name": "王大明",
                             "area_name": "臺南市第6選舉區", "district_id": "ly-tnn-06", "party": "民主進步黨"})
        self.assertNotIn("district_id", office_data(leg("王大明", "臺南市第6選舉區", 1), set()))
        self.assertNotIn("district_id", office_data(leg("王大明", "平地原住民", 1), {"ly-tnn-06"}))


class LyRecordsParseTest(unittest.TestCase):
    def test_interpellations_keep_only_rows_naming_the_legislator(self):
        rows = [{"質詢編號": "11-1-1-1", "質詢委員": ["王大明", "李小華"], "刊登日期": "2024-03-01", "事由": " 本院委員王大明，針對… ",
                 "會議代碼": "院會-11-1-1", "會期": 1, "質詢起始頁": 10, "質詢結束頁": 12},
                {"質詢編號": "11-1-1-2", "質詢委員": ["李小華"], "刊登日期": "2024-03-01", "事由": "x"}]
        out = ly_records.interpellation_facts(rows, "王大明")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["key"], "ly_interpellation:11-1-1-1")
        self.assertEqual(out[0]["date"], "2024-03-01")
        self.assertEqual(out[0]["data"]["title"], "本院委員王大明，針對…")
        self.assertEqual(out[0]["data"]["co_legislators"], ["李小華"])
        self.assertEqual(out[0]["source_url"], "https://ly.govapi.tw/v2/interpellation/11-1-1-1")

    def test_videos_link_the_official_ivod_page_over_https_and_skip_full_meetings(self):
        rows = [{"IVOD_ID": 156045, "IVOD_URL": "http://ivod.ly.gov.tw/Play/Clip/1M/156045", "委員名稱": "王大明",
                 "日期": "2024-10-24", "委員發言時間": "10:00:00 - 10:15:00",
                 "會議資料": {"標題": "第11屆第2會期內政委員會第5次全體委員會議", "會議代碼": "委員會-11-2-15-5",
                          "委員會代碼:str": ["內政委員會"]}},
                {"IVOD_ID": 1, "IVOD_URL": "https://ivod.ly.gov.tw/Play/Full/1M/1", "委員名稱": "完整會議", "日期": "2024-10-24"}]
        out = ly_records.video_facts(rows, "王大明")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source_url"], "https://ivod.ly.gov.tw/Play/Clip/1M/156045")
        self.assertEqual(out[0]["data"]["title"], "第11屆第2會期內政委員會第5次全體委員會議")
        self.assertEqual(out[0]["data"]["committees"], ["內政委員會"])

    def test_bills_count_proposers_only_not_cosigners(self):
        rows = [{"議案編號": "203110077970000", "議案名稱": "某某法修正草案", "提案人": ["王大明"], "連署人": ["李小華"],
                 "提案日期": "2024-05-01", "議案類別": "法律案", "議案狀態": "交付審查"},
                {"議案編號": "2", "議案名稱": "y", "提案人": ["李小華"], "連署人": ["王大明"]}]
        out = ly_records.bill_facts(rows, "王大明")
        self.assertEqual([f["key"] for f in out], ["ly_bill:203110077970000"])
        self.assertEqual(out[0]["data"]["status"], "交付審查")
        self.assertEqual(ly_records.bill_facts(rows, "李小華")[0]["key"], "ly_bill:2")


def _db(tmp):
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for did, office in (("tnn-mayor", "tnn_mayor"), ("ly-tnn-06", "legislator")):
        upsert(conn, "district", {"district_id": did, "office": office, "name": did, "seats": 1,
                                  "source_url": "http://d", "fetched_at": T}, ("district_id",))
    upsert(conn, "person", {"person_id": "p1", "name": "王大明"}, ("person_id",))
    upsert_fact(conn, "cand:p1", "p1", "candidacy", {"district_id": "tnn-mayor"}, "http://c", T)
    return conn


class LyRunTest(unittest.TestCase):
    def roster(self, extra=()):
        others = [leg(f"委員{i}", "全國不分區及僑居國外國民", 1000 + i) for i in range(110)]
        return [leg("王大明", "臺南市第6選舉區", 1), *extra, *others]

    def run_legislators(self, conn, roster):
        with mock.patch.object(lyapi, "fetch_all", return_value=(roster, "https://ly.govapi.tw/v2/legislators?x")), \
                mock.patch.object(ly_legislators, "load_identity", return_value={}), mock.patch("builtins.print"):
            ly_legislators.run(conn)

    def test_run_links_the_candidate_and_creates_hidden_people_for_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _db(tmp)
            self.run_legislators(conn, self.roster())
            office = conn.execute("SELECT person_id, date, data, source_url FROM fact WHERE fact_key = 'office:ly-11:p1'").fetchone()
            self.assertEqual(office["date"], "2024-02-01")
            self.assertEqual(json.loads(office["data"])["district_id"], "ly-tnn-06")
            self.assertEqual(office["source_url"], "https://ly.govapi.tw/v2/legislator/11/%E7%8E%8B%E5%A4%A7%E6%98%8E")
            self.assertEqual(conn.execute("SELECT count(*) FROM fact WHERE fact_key LIKE 'office:ly-11:%'").fetchone()[0], 111)
            self.assertEqual(conn.execute("SELECT count(*) FROM fact WHERE kind = 'candidacy'").fetchone()[0], 1)

    def test_run_refuses_an_implausible_roster_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _db(tmp)
            with self.assertRaises(ValueError):
                self.run_legislators(conn, [leg("王大明", "臺南市第6選舉區", 1)])

    def test_run_drops_offices_of_legislators_who_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _db(tmp)
            self.run_legislators(conn, self.roster())
            self.run_legislators(conn, [leg("王大明", "臺南市第6選舉區", 1, 離職原因="辭職"),
                                        *self.roster()[1:], leg("委員x", "平地原住民", 9)])
            self.assertIsNone(conn.execute("SELECT 1 FROM fact WHERE fact_key = 'office:ly-11:p1'").fetchone())

    def test_records_are_fetched_only_for_linked_candidates_and_replaced_wholesale(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _db(tmp)
            self.run_legislators(conn, self.roster())
            self.assertEqual(ly_records.linked_legislators(conn), [("p1", "王大明")])
            first = [{"key": "ly_bill:1", "date": "2024-05-01", "data": {"title": "a"}, "source_url": "https://x/1"},
                     {"key": "ly_bill:2", "date": "2024-05-02", "data": {"title": "b"}, "source_url": "https://x/2"}]
            with mock.patch.object(ly_records, "fetch_person", return_value=first), mock.patch("builtins.print"):
                ly_records.run(conn)
            with mock.patch.object(ly_records, "fetch_person", return_value=first[:1]), mock.patch("builtins.print"):
                ly_records.run(conn)
            keys = [k for (k,) in conn.execute("SELECT fact_key FROM fact WHERE kind = 'ly_bill'")]
            self.assertEqual(keys, ["ly_bill:1:p1"])
            # 串接撤銷後，候選人身上的立法院紀錄一併刪除
            conn.execute("DELETE FROM fact WHERE fact_key = 'office:ly-11:p1'")
            with mock.patch.object(ly_records, "fetch_person", side_effect=AssertionError), mock.patch("builtins.print"):
                ly_records.run(conn)
            self.assertEqual(conn.execute("SELECT count(*) FROM fact WHERE kind LIKE 'ly_%'").fetchone()[0], 0)

    def test_fetch_person_queries_term_11_by_name_for_each_endpoint(self):
        calls = []

        def fake(type_, params):
            calls.append((type_, params))
            return [], "u"

        ly_records.fetch_person("王大明", fetch_all=fake)
        self.assertEqual(calls, [("interpellations", {"屆": 11, "質詢委員": "王大明"}),
                                 ("ivods", {"屆": 11, "委員名稱": "王大明", "影片種類": "Clip"}),
                                 ("bills", {"屆": 11, "提案人": "王大明", "output_fields": ly_records.BILL_FIELDS})])
        self.assertIn("提案日期", ly_records.BILL_FIELDS)

    def test_list_url_repeats_the_key_for_list_values(self):
        url = lyapi.list_url("bills", {"output_fields": ["議案編號", "提案日期"]})
        self.assertIn("output_fields=%E8%AD%B0%E6%A1%88%E7%B7%A8%E8%99%9F&output_fields=%E6%8F%90%E6%A1%88%E6%97%A5%E6%9C%9F", url)


if __name__ == "__main__":
    unittest.main()
