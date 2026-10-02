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


if __name__ == "__main__":
    unittest.main()
