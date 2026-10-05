import unittest

from etl import rosters as r


def _tnn(*names):
    return "".join(f"<span class=\"peoplebold\" style=\"x\">{n}</span>" for n in names)


class RosterTest(unittest.TestCase):
    def test_nwt_reads_names_per_district(self):
        h = ('<h4><span>第1選區議員介紹</span></h4><a href="councilor-detail?A=1"><img alt="x"/>'
             '<p>\n 陳偉杰 \n</p></a><h4><span>第2選區議員介紹</span></h4>'
             '<a href="councilor-detail?A=2"><p>甲乙</p></a><p>議事直播</p>')
        self.assertEqual([(x["district_n"], x["name"]) for x in r.parse_nwt(h)], [(1, "陳偉杰"), (2, "甲乙")])

    def test_tao_strips_title_and_skips_headings(self):
        pages = ["<p>本屆議員</p><p> 李曉鐘 副議長 </p><p>凌濤 議員</p>", "<p>王小明 議員</p>"]
        self.assertEqual([(x["district_n"], x["name"]) for x in r.parse_tao(pages)],
                         [(1, "李曉鐘"), (1, "凌濤"), (2, "王小明")])

    def test_txg_converts_chinese_district_numbers(self):
        h = ('<div class="Mcouncillor_title">第十五選區<span>x</span></div>'
             '<div class="list_note"><a href="m">吳建德 </a></div>')
        self.assertEqual([(x["district_n"], x["name"]) for x in r.parse_txg(h)], [(15, "吳建德")])

    def test_tnn_deceased_note_is_split_and_not_current(self):
        row = r.parse_tnn([_tnn("蔡育輝", "張世賢(歿)")])[1]
        self.assertEqual((row["name"], row["note"], row["current"]), ("張世賢", "歿", False))
        self.assertTrue(r.parse_tnn([_tnn("蔡育輝")])[0]["current"])

    def test_tnn_dismissal_note_with_date(self):
        row = r.parse_tnn([_tnn("蔡淑惠(解職自115.06.30起生效)")])[0]
        self.assertEqual((row["name"], row["current"]), ("蔡淑惠", False))

    def test_khh_became_legislator_note_is_split_and_not_current(self):
        h = ('<h4>第 <span>04</span> 選區</h4><li><a class="kcc-link link" href="x">'
             '<img alt="a"><span>李柏毅(轉任立委)</span></a></li>'
             '<li><a class="kcc-link link" href="x"><img alt="a"><span>高忠德(Taki ludun‧Anu)</span></a></li>')
        a, b = r.parse_khh(h)
        self.assertEqual((a["district_n"], a["name"], a["note"], a["current"]), (4, "李柏毅", "轉任立委", False))
        self.assertTrue(b["current"])

    def _dn(self, rows):
        return [(x["district_n"], x["name"]) for x in rows]

    def test_hsq_reads_names_per_chinese_district(self):
        h = ('<h3 class="member-container-title">第二選區：竹北市：</h3><ul>'
             '<li class="member-container-bottom"><a href="m?C=1" title="陳栢誠">陳栢誠</a></li></ul>')
        self.assertEqual(self._dn(r.parse_hsq(h)), [(2, "陳栢誠")])

    def test_cha_splits_tooltip_names_on_separators(self):
        h = ("{key: 'area3',toolTip: '<strong style=x >第三選區&nbsp;和美鎮</strong><br/>"
             "<span style=y >甲乙、丙丁<br/>戊己</span>' }")
        self.assertEqual(self._dn(r.parse_cha(h)), [(3, "甲乙"), (3, "丙丁"), (3, "戊己")])

    def test_nan_reads_district_from_href_and_dedups(self):
        a = '<a href="p02.aspx?district=8&period=20#林庭秝(AliWalis)">'
        self.assertEqual(self._dn(r.parse_nan(a + a)), [(8, "林庭秝(AliWalis)")])

    def test_yun_reads_caption_names_under_district_tab(self):
        h = ('<a  href="#"   title="第四選區" data-name="x"  >第四選區</a>'
             '<div class="caption">蕭慧敏</div><a  href="#"  title="第五選區">x</a><div class="caption">王又民</div>')
        self.assertEqual(self._dn(r.parse_yun(h)), [(4, "蕭慧敏"), (5, "王又民")])

    def test_pif_reads_names_per_district_row(self):
        h = ('<td rowspan="2" class="list evacategory" nowrap>第十六選區</td>'
             '<a href="?Page=PersionalDetail&Guid=ab-1">甲乙</a> <a href="?Page=PersionalDetail&Guid=ab-2">丙丁</a>')
        self.assertEqual(self._dn(r.parse_pif(h)), [(16, "甲乙"), (16, "丙丁")])

    def test_ila_strips_spaces_inside_name(self):
        h = ('<img src="x" alt="第1選區(宜蘭)"><a target="_parent" title="林 麗議員相關資料">林 麗</a>'
             '<img src="x" alt="第2選區(頭城)"><a title="黃雯如議員相關資料">黃雯如</a>')
        self.assertEqual(self._dn(r.parse_ila(h)), [(1, "林麗"), (2, "黃雯如")])

    def test_hua_removes_title_inserted_between_surname_and_given_name(self):
        h = ('<h3 class="text-normal">第三選區</h3><p class="text-header"><a href="c?1">魏議員 嘉賢</a></p>'
             '<p class="text-header"><a href="c?2">張議長峻</a></p>')
        self.assertEqual(self._dn(r.parse_hua(h)), [(3, "魏嘉賢"), (3, "張峻")])

    def test_pen_has_no_district_and_drops_officer_title(self):
        h = ('<a href="meet.php?councillor=M24080001">陳毓仁 議長</a>'
             '<a href="meet.php?councillor=M24080003">陳海山</a><a href="meet.php?x=1">議場</a>')
        self.assertEqual(self._dn(r.parse_pen(h)), [(None, "陳毓仁"), (None, "陳海山")])

    def test_kin_ignores_menu_links_after_last_district_list(self):
        h = ('<h3>第三選區/烈嶼鄉</h3><ul><li> <a target="_self" title="吳佩雯">吳佩雯</a> </li></ul>'
             '<ul><li><a title="公告資訊">公告資訊</a></li></ul>')
        self.assertEqual(self._dn(r.parse_kin(h)), [(3, "吳佩雯")])

    def test_lie_reads_officers_and_members_per_district(self):
        h = ('<img alt="第一選區－南竿鄉" /><div class="group"><a>副議長 ：林明揚 </a><a>議員：曹以標</a></div>'
             '<img alt="第四選區－東引鄉" /><div class="group"><a>議長：張永江</a></div></ul>')
        self.assertEqual(self._dn(r.parse_lie(h)), [(1, "林明揚"), (1, "曹以標"), (4, "張永江")])

    def test_kee_numbers_districts_by_order_and_drops_fullwidth_space(self):
        sq = '<i class="fa fa-square" aria-hidden="true"></i> '
        h = (sq + '中正區</h2><h3><a href="x" itemprop="url">藍敏煌 議員</a></h3>'
             + sq + '信義區</h2><h3><a href="x" itemprop="url">陳\u3000宜 議員</a></h3>')
        self.assertEqual(self._dn(r.parse_kee(h)), [(1, "藍敏煌"), (2, "陳宜")])

    def test_cyq_one_page_per_district_and_strips_title_inside_name(self):
        pages = ['<option value="">選擇議員</option><option value="1">王啓澧 議員</option>',
                 '<option value="">選擇議員</option><option value="2">張議長明達 議員</option>']
        self.assertEqual(self._dn(r.parse_cyq(pages)), [(1, "王啓澧"), (2, "張明達")])

    def test_mia_one_page_per_district_unescapes_and_strips_titles(self):
        cell = '<TD width="50%" bgcolor="#E4E4E4">{}</TD>'
        pages = [cell.format("副議長  張淑芬") + cell.format("&#28201;俊勇"), cell.format("議長  李文斌")]
        self.assertEqual(self._dn(r.parse_mia(pages)), [(1, "張淑芬"), (1, "温俊勇"), (2, "李文斌")])

    def test_hsz_numbers_districts_by_area_name_across_pages(self):
        sp = "<section><span>{}議員 {}</span></section>"
        pages = [sp.format("東區", "余邦彥") + sp.format("東區", "鄭美娟"), sp.format("平地原住民", "林慈愛")]
        self.assertEqual(self._dn(r.parse_hsz(pages)), [(1, "余邦彥"), (1, "鄭美娟"), (6, "林慈愛")])

    def test_ttt_unions_townships_by_id_and_reads_district_from_type(self):
        a = '{"id":1,"member":"吳秀華","type":"第一選區(區域縣議員)"}'
        b = '{"id":9,"member":"蔡玉玲","type":"第十五選區(山地原住民)"}'
        self.assertEqual(self._dn(r.parse_ttt([f"[{a}]", f"[{a},{b}]"])), [(1, "吳秀華"), (15, "蔡玉玲")])

    def test_nan_trusts_bundled_twca_cyber_root_from_mozilla(self):
        import hashlib, ssl
        der = ssl.PEM_cert_to_DER_cert(r._CA["nan"].read_text())
        self.assertEqual(hashlib.sha256(der).hexdigest().upper(),
                         "3F63BB2814BE174EC8B6439CF08D6D56F0B7C405883A5648A334424D6B3EC558")

    def test_get_with_cafile_still_connects_over_ipv4_when_asked(self):
        from unittest import mock
        from etl import fetch
        with mock.patch.object(fetch, "_connect_v4", side_effect=OSError("v4 path")):
            with self.assertRaisesRegex(OSError, "v4 path"):
                fetch.get("https://example.invalid/", ipv4=True, cafile=r._CA["nan"])


if __name__ == "__main__":
    unittest.main()


class FetchRetryTest(unittest.TestCase):
    def test_retries_transient_disconnects_but_not_http_errors(self):
        import http.client
        import urllib.error
        from etl import rosters
        calls = []

        def flaky(iso):
            calls.append(iso)
            if len(calls) < 3:
                raise http.client.RemoteDisconnected("closed")
            return ["ok"]
        saved = rosters._fetch_roster
        rosters._fetch_roster = flaky
        try:
            self.assertEqual(rosters.fetch_roster("nwt", wait=0), ["ok"])
            self.assertEqual(len(calls), 3)

            def broken(iso):
                calls.append(iso)
                raise urllib.error.HTTPError("u", 404, "nf", None, None)
            rosters._fetch_roster = broken
            calls.clear()
            with self.assertRaises(urllib.error.HTTPError):
                rosters.fetch_roster("nwt", wait=0)
            self.assertEqual(len(calls), 1)
        finally:
            rosters._fetch_roster = saved
