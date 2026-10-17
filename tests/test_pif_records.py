import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import pif_book


def minutes(date, body, term=20):
    y, m, d = date
    return (f" 屏東縣議會第 {term} 屆第 7 次定期會會議紀錄\n三十九、第 26 次會議\n"
            f"時間：中華民國 {y} 年 {m} 月 {d} 日（星期四）上午 9 時整\n出席：詳如簽到簿\n"
            f"一、報告事項：（略）\n二、施政總質詢及答復：（另錄）\n{body}\n三、散會：上午 11 時 02 分\n")


TEXTS = {
    "1150702": minutes((115, 7, 2), "  質詢議員：蔣月惠、潘翠雲、王小明"),
    "1150528": minutes((115, 5, 28), "  發言議員：蔣月惠、曾義雄"),
    "1131126": minutes((113, 11, 26), "  （一）原排定質詢議員：張平原、陳志成、周議長、盧副議長\n （二）張平原議員、陳志成議員採書面質詢"),
    "1140625": minutes((114, 6, 25), "  （一）原排定質詢議員：曾義雄、潘翠雲\n  質詢議員：曾義雄、潘翠雲、周議長\n"
                                     " （二）潘翠雲議員採\n書面質詢"),
    "1150609": minutes((115, 6, 9), "  質詢議員：曾義雄"),
}
FILES = {roc: f"{i:08x}-0000-0000-0000-000000000000" for i, roc in enumerate(TEXTS)}
PEOPLE = [("p1", "蔣月惠", True), ("p2", "潘翠雲", True), ("p3", "曾義雄", True), ("p4", "張平原", True), ("p5", "陳志成", False)]


def new_conn(tmp):
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, cand in PEOPLE:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "pif_councilor", "district_id": "pif-council-01"},
                    "https://u", "t", date="2022-12-25")
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "pif-council-01"}, "https://u", "t")
    return conn


def build(texts=TEXTS):
    with tempfile.TemporaryDirectory() as tmp:
        logs = []
        out = pif_book.build(new_conn(tmp), FILES, texts, logs.append)
    return out, logs


class TestPifMinutes(unittest.TestCase):
    def test_collects_each_listed_asker_once_per_day_linked_to_that_days_minutes(self):
        (ts, days, by_pid), logs = build()
        k, d, url, date = by_pid["p1"][0]
        self.assertEqual((k, date), ("pifmin:2026-07-02:p1", "2026-07-02"))
        self.assertEqual(url, "https://www.ptcc.gov.tw/lib/GetFile.php?fil_guid=" + FILES["1150702"])
        self.assertEqual((d["councillors"], d["group_size"], d["session"]), (["蔣月惠", "潘翠雲", "王小明"], 3, "第20屆第7次定期會"))
        self.assertEqual(d["title"], "施政總質詢（會議紀錄列為質詢議員）；同場列名：蔣月惠、潘翠雲、王小明")
        self.assertNotIn("聯合", d["title"])
        self.assertEqual(len(by_pid["p1"]), 1)

    def test_speakers_on_department_report_days_are_not_collected(self):
        (ts, days, by_pid), logs = build()
        self.assertFalse(any(date == "2026-05-28" for fs in by_pid.values() for _, _, _, date in fs))

    def test_originally_scheduled_and_written_only_are_not_collected(self):
        (ts, days, by_pid), logs = build()
        self.assertNotIn("p4", by_pid)
        self.assertTrue(any("1131126 只有原排定質詢議員" in x for x in logs))

    def test_listed_asker_who_also_switched_to_written_is_excluded(self):
        (ts, days, by_pid), logs = build()
        self.assertNotIn("2025-06-25", [date for _, _, _, date in by_pid["p2"]])
        self.assertIn("2025-06-25", [date for _, _, _, date in by_pid["p3"]])
        self.assertTrue(any("潘翠雲 列為質詢議員但同日採書面質詢" in x for x in logs))
        d = next(d for d in days if d["roc"] == "1140625")
        self.assertEqual(d["names"], ["曾義雄"])

    def test_title_only_entries_are_not_attached(self):
        (ts, days, by_pid), logs = build()
        self.assertTrue(any("「周議長」不是姓名" in x for x in logs))

    def test_unknown_name_and_non_candidate_are_not_collected(self):
        (ts, days, by_pid), logs = build()
        self.assertTrue(any("王小明：名錄沒有此人" in x for x in logs))
        self.assertEqual(set(by_pid), {"p1", "p2", "p3"})

    def test_minutes_whose_date_differs_from_filename_is_dropped(self):
        texts = {**TEXTS, "1150609": minutes((115, 6, 10), "  質詢議員：曾義雄")}
        (ts, days, by_pid), logs = build(texts)
        self.assertNotIn("2026-06-09", [date for _, _, _, date in by_pid["p3"]])
        self.assertTrue(any("1150609 會議紀錄時間 115.6.10 與檔名日期不同" in x for x in logs))

    def test_written_note_for_someone_else_does_not_drop_listed_askers(self):
        text = minutes((113, 11, 19), "  (一)原排定施政總質詢：林郁虹、羅平道、潘翠雲\n     質詢議員：羅平道、潘翠雲\n  (二)林郁虹議員採書面質詢")
        self.assertEqual(pif_book.parse_minutes("1131119", text, lambda s: None)["names"], ["羅平道", "潘翠雲"])

    def test_wrapped_list_romanized_name_compat_char_and_parenthetical(self):
        logs = []
        text = minutes((113, 11, 25), "  質詢議員：黃明賢(蘇資婷、越秋女借用黃明賢質\n     詢時間)、潘芳泉\n     、李紀財 Mulaneng Paliuliu、高惠芬\n      周陳曉玟")
        text = text.replace("紀錄", "紀錄")  # 會議紀錄表頭的 CJK 相容字
        d = pif_book.parse_minutes("1131125", text, logs.append)
        self.assertEqual(d["names"], ["潘芳泉", "李紀財 Mulaneng Paliuliu", "高惠芬", "周陳曉玟"])
        self.assertTrue(any("含括號說明，整段不收" in x for x in logs))

    def test_parse_detail_keeps_plenary_minutes_and_skips_comments_and_committees(self):
        page = ("<td><a href=/lib/GetFile.php?fil_guid=d3dda0ef-ae05-22e8-00e5-308ae9d7f7d8 title='1150526會議紀錄.pdf_PDF格式(另開新視窗)'></td>"
                "<!-- <a href=/lib/GetFile.php?fil_guid=aaaaaaaa-ae05-22e8-00e5-308ae9d7f7d8 title='1150526會議紀錄.pdf_PDF格式(另開新視窗)'> -->"
                "<a href=/lib/GetFile.php?fil_guid=f2f33c1f-64e7-a0c4-6bff-c8f6717fc6c5 title='1150608會議記錄.pdf_PDF格式(另開新視窗)'>"
                "<a href=/lib/GetFile.php?fil_guid=4108d350-7632-38a0-b8dc-ef4dc86ba583 title='1150819財政審查會第1次會議紀錄.pdf_PDF格式(另開新視窗)'>"
                "<a href=/lib/GetFile.php?fil_guid=36769756-5781-e0fb-e21a-b9ab3adb0730 title='1150527縣長施政總報告簡報檔.pdf_PDF格式(另開新視窗)'>")
        self.assertEqual(pif_book.parse_detail(page), [("1150526", "d3dda0ef-ae05-22e8-00e5-308ae9d7f7d8"),
                                                       ("1150608", "f2f33c1f-64e7-a0c4-6bff-c8f6717fc6c5")])

    def test_day_files_dedupes_by_date_keeping_first_schedule(self):
        a = "<a href=/lib/GetFile.php?fil_guid=11111111-1111-1111-1111-111111111111 title='1150818會議紀錄.pdf_PDF格式'>"
        b = "<a href=/lib/GetFile.php?fil_guid=22222222-2222-2222-2222-222222222222 title='1150818會議紀錄.pdf_PDF格式'>"
        self.assertEqual(pif_book.day_files([("g1", "變更", a), ("g2", "原版", b)]),
                         {"1150818": "11111111-1111-1111-1111-111111111111"})


if __name__ == "__main__":
    unittest.main()
