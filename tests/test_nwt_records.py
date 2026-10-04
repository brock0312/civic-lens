import tempfile
import unittest
from pathlib import Path

from etl.db import open_db, upsert_fact, upsert_person
from etl.sources import nwt_book, nwt_videos

BOOKS = """
<a href="/Home/BookAgenda?cBookMdslID=11111111-1111-1111-1111-111111111111" class="list-group-item">
    <p class="list-group-item-text" style="color: #0275d8">第4屆第6次定期會</p>
</a>
<a href="/Home/BookAgenda?cBookMdslID=22222222-2222-2222-2222-222222222222" class="list-group-item">
    <p class="list-group-item-text" style="color: #0275d8">第4屆成立大會</p>
</a>"""


def agenda_row(roc_date, *pdfs):
    links = "".join(f'<p><a href="https://ntpbook.ntp.gov.tw/Mam/BookAgendaAnnex/202510/{p}.pdf" target="_blank" '
                    f'class="ui-btn">摘要紀錄</a></p>' for p in pdfs)
    return f'<tr>\n<td style="width: 96px; text-align: center;">{roc_date}</td>\n<td>三</td>\n<td>{links}</td>\n</tr>'


def annex(*titles):
    links = "".join(f'<a href="https://ntpbook.ntp.gov.tw/Mam/BookAnnex/202601/{i}.pdf" target="_blank" class="list-group-item">'
                    f'<p class="list-group-item-text">&nbsp;&nbsp;<img src="/Images/document.png" />{t}</p></a>'
                    for i, t in enumerate(titles))
    return ('<a href="https://ntpbook.ntp.gov.tw/Mam/BookAnnex/202509/x.pdf" class="list-group-item"><p>市政總質詢順序表</p></a>'
            f'<div class="panel-heading">&nbsp;書面質詢及答復</div><div class="list-group">{links}</div>'
            '<div class="panel-heading">其他</div><a href="https://ntpbook.ntp.gov.tw/Mam/BookAnnex/202601/z.pdf"><p>'
            '114年1月1日乙議員個人書面質詢及答復</p></a>')


def summary(*names):
    return ("新北市議會第 4 屆第 6 次定期會第 1 次會議摘要紀錄\n時  間：中華民國 114 年 10 月 1 日\n"
            f"出  席：{'      '.join(names)}\n列  席：秘書長某某\n")


def vod_item(vid, agenda, speakers, roc_date, session="第4屆第8次定期會"):
    span = '<span onclick="showTip(this,event)" type="button" class="control-label " data-tip="{0}" style="">{0}</span>'
    return (f'<a href=ViewDetailMetaData/{vid} class="mov"><div class="playicon"><span class="timecode">02:00:34</span></div></a>'
            f'<h6>{span.format("屆次會期：" + session)}{span.format("議　　程：" + agenda)}'
            f'{span.format("發言議員：" + ",".join(speakers))}{span.format("開會日期：" + roc_date)}</h6>')


def vod_page(items, total):
    return f'<span class="fb24">x<span style="color:red">總筆數:{total}</span></span>' + "".join(items)


def new_conn(tmp, people):
    """people：[(person_id, name, 任職起日, 有 2026 candidacy)]，都是新北市議員。"""
    conn = open_db(Path(tmp) / "civic.db", Path(tmp) / "civic.sql")
    for pid, name, since, cand in people:
        upsert_person(conn, pid, name)
        upsert_fact(conn, f"office:{pid}", pid, "office", {"office": "nwt_councilor", "district_id": "nwt-council-01"},
                    "https://u", "t", date=since)
        if cand:
            upsert_fact(conn, f"cand:{pid}", pid, "candidacy", {"district_id": "nwt-council-01"}, "https://u", "t")
    return conn


def u(p):
    return f"https://ntpbook.ntp.gov.tw/Mam/BookAgendaAnnex/202510/{p}.pdf"


PEOPLE = [("p1", "陳偉杰", "2022-12-25", True), ("p2", "林國春", "2022-12-25", False),
          ("p3", "王小明", "2022-12-25", True), ("p4", "王小明", "2022-12-25", True),
          ("p5", "宋雨蓁 Nikar Falong", "2022-12-25", True), ("p6", "補選人", "2025-10-02", True)]


class TestNwtBookParse(unittest.TestCase):
    def test_books_keep_term_4_sessions_in_page_order(self):
        self.assertEqual([b["session"] for b in nwt_book.parse_books(BOOKS)], ["第4屆第6次定期會", "第4屆成立大會"])

    def test_agenda_rows_give_each_summary_record_with_its_date(self):
        page = agenda_row("114-09-30", "a") + "<tr><td>114-10-01</td><td>沒有紀錄</td></tr>" + agenda_row("114-10-02", "b", "c")
        self.assertEqual(nwt_book.parse_agenda(page), [{"date": "2025-09-30", "url": u("a")},
                                                       {"date": "2025-10-02", "url": u("b")},
                                                       {"date": "2025-10-02", "url": u("c")}])

    def test_present_list_joins_romanized_names_and_skips_page_marks(self):
        text = summary("林國春", "宋雨蓁 Nikar．Falong", "李翁月娥 呂家愷") + "x"
        text = text.replace("呂家愷", "\n第1/4頁\n呂家愷")
        self.assertEqual(nwt_book.parse_present(text), (["林國春", "宋雨蓁Nikar．Falong", "李翁月娥", "呂家愷"], [], []))
        with self.assertRaises(ValueError):
            nwt_book.parse_present("沒有出席段")

    def test_leave_list_is_split_from_the_present_list_and_official_duty_from_leave(self):
        text = summary("林國春", "陳偉杰").replace("列  席", "請   假：黃永昌     宋明宗\n        洪佳君（公假）\n列  席")
        self.assertEqual(nwt_book.parse_present(text), (["林國春", "陳偉杰"], ["黃永昌", "宋明宗"], ["洪佳君"]))

    def test_records_without_a_present_list_are_rejected(self):
        with self.assertRaises(ValueError):
            nwt_book.parse_present(summary("詳如簽到簿"))

    def test_written_section_keeps_personal_files_only(self):
        personal, other = nwt_book.parse_written(annex(
            "114年11月10日陳偉杰議員個人書面質詢及答復",
            "114年10月28日、11月7日鄭宇恩議員個人書面質詢及答復",
            "114年11月4日林裔綺、許昭興議員聯合書面質詢及答復",
            "114年11月5日、11月7日國民黨團聯合書面質詢及答復"))
        self.assertEqual([(p["name"], p["dates"]) for p in personal],
                         [("陳偉杰", "114年11月10日"), ("鄭宇恩", "114年10月28日、11月7日")])
        self.assertEqual(len(other), 2)
        self.assertEqual(nwt_book.parse_written("<p>沒有附錄</p>"), ([], []))

    def test_written_names_drop_titles_in_any_position(self):
        personal, other = nwt_book.parse_written(annex(
            "113年6月3日陳議員偉杰個人書面質詢及答復",
            "113年6月7日彭議員一書個人書面質詢及答復",
            "113年6月7日陳副議長鴻源個人書面質詢及答復",
            "113年6月11日呂議員家愷書個人面質詢及答復",
            "113年6月18日李翁議員月娥個人質詢書面質詢及答復",
            "114年10月31日蘇錦雄Paylang．Caya議員議員個人書面質詢及答復",
            "113年6月3日洪議員佳君、陳議員儀君個人書面質詢及答復"))
        self.assertEqual([p["name"] for p in personal],
                         ["陳偉杰", "彭一書", "陳鴻源", "呂家愷", "李翁月娥", "蘇錦雄Paylang．Caya"])
        self.assertEqual(len(other), 1)

    def test_first_date_is_the_earliest_link_date(self):
        self.assertEqual(nwt_book.first_date([{"dates": "114年11月10日"}, {"dates": "114年10月28日、11月7日"}]), "2025-10-28")


class TestNwtBookBuild(unittest.TestCase):
    def books(self):
        return [{"id": "B6", "session": "第4屆第6次定期會",
                 "agenda": agenda_row("114-10-01", "a") + agenda_row("114-10-02", "b") + agenda_row("114-10-03", "c"),
                 "annex": annex("114年11月10日陳偉杰議員個人書面質詢及答復", "114年11月11日陳偉杰議員個人書面質詢及答復",
                                "114年11月10日林國春議員個人書面質詢及答復", "114年11月10日王小明議員個人書面質詢及答復")},
                {"id": "B0", "session": "第4屆成立大會", "agenda": agenda_row("111-12-25", "z"), "annex": ""}]

    def texts(self):
        return {u("a"): summary("陳偉杰", "林國春", "王小明", "宋雨蓁 Nikar．Falong", "不明人"),
                u("b"): summary("陳偉杰").replace("列  席", "請  假：宋雨蓁 Nikar．Falong 補選人（公假）\n列  席"),
                u("c"): None,  # 沒抓到：不列入 M
                u("z"): summary("陳偉杰")}

    def test_only_unique_incumbent_candidates_get_attendance_and_written_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, PEOPLE)
            logs = []
            ts, att, wr = nwt_book.build(conn, self.books(), self.texts(), logs.append)
        self.assertEqual(len(ts), 5)
        self.assertEqual(sorted(att), ["p1", "p5", "p6"])  # p2 沒參選；p3、p4 同名
        self.assertEqual(sorted(wr), ["p1"])
        p1 = {d["session"]: (d["present"], d["meetings"]) for _, d, _, _ in att["p1"]}
        self.assertEqual(p1, {"第4屆第6次定期會": (2, 2), "第4屆成立大會": (1, 1)})
        self.assertEqual([(d["present"], d["leave"], d["duty"], d["meetings"]) for _, d, _, _ in att["p5"]], [(1, 1, 0, 2), (0, 0, 0, 1)])
        # 補選人只算任職起日以後的大會
        self.assertEqual([(d["present"], d["leave"], d["duty"], d["meetings"]) for _, d, _, _ in att["p6"]], [(0, 0, 1, 1)])
        key, data, url, date = wr["p1"][0]
        self.assertEqual(key, "ntpwritten:B6:p1")
        self.assertEqual(data["title"], "第6次定期大會書面質詢及答復（掃描檔）")
        self.assertEqual(len(data["files"]), 2)
        self.assertEqual((url, date), ("https://ntpbook.ntp.gov.tw/Mam/BookAnnex/202601/0.pdf", "2025-11-10"))
        self.assertTrue(any("不明人：名錄沒有此人" in x for x in logs))
        self.assertTrue(any("王小明：名錄同名" in x for x in logs))
        self.assertTrue(any("摘要紀錄未取得" in x for x in logs))

    def test_write_replaces_facts_and_deletes_stale_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, PEOPLE)
            upsert_fact(conn, "ntpattend:OLD:p1", "p1", "attendance", {}, "https://u", "t")
            upsert_fact(conn, "kattend:1:p1", "p1", "attendance", {}, "https://u", "t")
            _, att, _ = nwt_book.build(conn, self.books(), self.texts(), lambda _: None)
            n, stale = nwt_book.write(conn, "ntpattend", att, "attendance")
            self.assertEqual((n, stale), (5, 1))
            n, stale = nwt_book.write(conn, "ntpattend", att, "attendance")
            self.assertEqual((n, stale), (5, 0))
            keys = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE kind = 'attendance'")}
        self.assertIn("kattend:1:p1", keys)  # 別的縣市不動
        self.assertNotIn("ntpattend:OLD:p1", keys)


class TestNwtVideos(unittest.TestCase):
    ITEMS = [
        vod_item("v1", "市政總質詢", ["陳偉杰", "林國春"], "115-09-03"),
        vod_item("v2", "一至六審各機關聯合業務報告及質詢-國民黨團發言", ["林國春", "宋雨蓁Nikar．Falong", "王小明"], "115-05-20"),
        vod_item("v3", "市政總質詢-報告事項", ["陳偉杰"], "115-09-03"),
        vod_item("v4", "市政總質詢", ["陳偉杰"], "111-12-20", session="第3屆第8次定期會"),
        vod_item("v5", "市政總質詢", ["陳偉杰", "陳偉杰", "補選人"], "114-06-01"),
    ]

    def test_page_items_and_total(self):
        items, total = nwt_videos.parse_page(vod_page(self.ITEMS[:2], 848))
        self.assertEqual(total, 848)
        self.assertEqual(items[0], {"id": "v1", "session": "第4屆第8次定期會", "agenda": "市政總質詢",
                                    "speakers": ["陳偉杰", "林國春"], "date": "2026-09-03", "duration": "02:00:34"})
        with self.assertRaises(ValueError):
            nwt_videos.parse_page("<html></html>")

    def test_agendas_keep_interpellations_only(self):
        self.assertEqual(nwt_videos.parse_agenda("市政總質詢"), ("市政總質詢", "市政總質詢"))
        self.assertEqual(nwt_videos.parse_agenda("二、三審各機關聯合業務報告及質詢-民進黨團發言"),
                         ("業務質詢", "二、三審各機關聯合業務報告及質詢，民進黨團發言"))
        self.assertIsNone(nwt_videos.parse_agenda("市政總質詢-報告事項"))
        self.assertIsNone(nwt_videos.parse_agenda("報告事項"))
        with self.assertRaises(ValueError):
            nwt_videos.parse_agenda("質詢時間")

    def test_videos_go_only_to_listed_unique_incumbent_candidates_once(self):
        items, _ = nwt_videos.parse_page(vod_page(self.ITEMS, 5))
        with tempfile.TemporaryDirectory() as tmp:
            conn = new_conn(tmp, PEOPLE)
            logs = []
            ts, by_pid = nwt_videos.build(conn, items, logs.append)
            upsert_fact(conn, "ntpvideo:gone:p1", "p1", "interpellation", {}, "https://u", "t")
            upsert_fact(conn, "nvideo:yt1:p1", "p1", "interpellation", {}, "https://u", "t")  # 臺南的鍵，不能被刪
            n, stale = nwt_videos.write_videos(conn, by_pid, "t")
            self.assertIsNotNone(conn.execute("SELECT 1 FROM fact WHERE fact_key = 'nvideo:yt1:p1'").fetchone())
            rows = conn.execute("SELECT fact_key, date, data, source_url FROM fact WHERE fact_key LIKE 'ntpvideo:%' ORDER BY fact_key").fetchall()
        self.assertEqual({p: [v["id"] for v in vs] for p, vs in by_pid.items()}, {"p1": ["v5", "v1"], "p5": ["v2"]})
        self.assertEqual((n, stale), (3, 1))
        self.assertEqual([r["fact_key"] for r in rows], ["ntpvideo:v1:p1", "ntpvideo:v2:p5", "ntpvideo:v5:p1"])
        self.assertEqual(rows[0]["source_url"], "https://vod.ntp.gov.tw/VodCloudV2/VOD/ViewDetailMetaData/v1")
        self.assertIn('"whole_session": true', rows[0]["data"])
        self.assertIn('"group_size": 2', rows[0]["data"])
        self.assertTrue(any("王小明：名錄同名" in x for x in logs))


if __name__ == "__main__":
    unittest.main()
