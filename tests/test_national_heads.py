import tempfile
import unittest
from pathlib import Path

from etl.sources.national_heads import STATUS_PATH, head_data, load_status, split

HEADER = ("iso,date,event,acting_name,acting_position,acting_title,source_url,source_label,"
          "acting_source_url,acting_source_label,fetched_at\n")


def head(iso, name="某某"):
    return {"iso": iso, "name": name, "party": "無", "source_url": "https://db.cec.gov.tw/x.json"}


def status_from(text):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.csv"
        p.write_text(HEADER + text, encoding="utf-8")
        return load_status(p)


class NationalHeadsTest(unittest.TestCase):
    def test_repo_status_table_has_only_the_three_v14_events(self):
        s = load_status(STATUS_PATH)
        self.assertEqual(sorted(s), ["hsz", "ila"])
        self.assertEqual([e["event"] for e in s["hsz"]], ["suspended", "reinstated"])
        self.assertEqual(s["ila"][0]["acting_name"], "林茂盛")
        self.assertEqual(s["hsz"][1]["date"], "2025-12-17")
        self.assertNotIn("acting_name", s["hsz"][1], "空欄位不寫進事件")

    def test_events_sort_by_date_within_a_county(self):
        s = status_from("hsz,2025-12-17,reinstated,,,,https://a,說明,,,2026-10-02\n"
                        "hsz,2024-07-26,suspended,甲,副市長,代理市長,https://b,公告,,,2026-10-02\n")
        self.assertEqual([e["date"] for e in s["hsz"]], ["2024-07-26", "2025-12-17"])

    def test_suspension_without_acting_person_is_rejected(self):
        with self.assertRaises(ValueError):
            status_from("ila,2024-12-31,suspended,,,,https://a,公告,,,2026-10-02\n")

    def test_unknown_event_or_taipei_is_rejected(self):
        with self.assertRaises(ValueError):
            status_from("ila,2024-12-31,removed,,,,https://a,公告,,,2026-10-02\n")
        with self.assertRaises(ValueError):
            status_from("tpe,2024-12-31,reinstated,,,,https://a,公告,,,2026-10-02\n")

    def test_head_data_attaches_status_events_only_when_present(self):
        events = load_status(STATUS_PATH)["ila"]
        d = head_data(head("ila"), events)
        self.assertEqual(d["status_events"], events)
        self.assertEqual((d["office"], d["district_id"], d["title"]), ("ila_mayor", "ila-mayor", "宜蘭縣長"))
        self.assertEqual(d["elected_on"], "2022-11-26")
        self.assertNotIn("status_events", head_data(head("kee"), []))

    def test_chiayi_city_uses_the_rerun_election_date_and_note(self):
        d = head_data(head("cyi"), [])
        self.assertEqual((d["elected_on"], d["election_note"], d["title"]), ("2022-12-18", "重行選舉", "嘉義市長"))
        self.assertNotIn("election_note", head_data(head("cyq"), []))

    def test_split_links_unique_match_and_leaves_review_and_unregistered_unlinked(self):
        heads = [head("hsz", "高虹安"), head("ila", "林姿妙"), head("khh", "陳其邁"), head("kee", "黃大明")]
        cands = [
            {"person_id": "p1", "name": "高虹安", "district_id": "hsz-mayor"},
            {"person_id": "p2", "name": "陳其邁", "district_id": "khh-mayor"},
            {"person_id": "p3", "name": "陳其邁", "district_id": "khh-council-01"},
            {"person_id": "p4", "name": "黄大明", "district_id": "kee-mayor"},
        ]
        linked, review = split(heads, cands)
        self.assertEqual(linked, {"hsz": "p1", "ila": None, "khh": None, "kee": None})
        self.assertEqual(sorted(review), ["kee", "khh"])
