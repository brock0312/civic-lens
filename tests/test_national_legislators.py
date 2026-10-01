import json
import tempfile
import unittest
from pathlib import Path

from etl.db import SCHEMA_PATH, connect, upsert
from etl.export import export
from etl.sources.national_legislators import village_rows


def li(dept, li_code, area, name="某里"):
    return {"prv_code": "68", "city_code": "000", "dept_code": dept, "li_code": li_code,
            "area_code": area, "area_name": name}


def vill(code, town, name):
    return {"VILLCODE": code, "COUNTYNAME": "桃園市", "TOWNCODE": code[:8], "TOWNNAME": town, "VILLNAME": name}


LI_ROWS = [
    li("010", "0001", "01"), li("010", "0002", "04"),  # 桃園區跨第 1、4 選區
    li("030", "0001", "02"),                           # 大溪區只屬第 2 選區
    li("030", "A001", "02", "合併開票單位"),
]


class TestLegislatorVillages(unittest.TestCase):
    def test_direct_hit_inherit_and_unmatched(self):
        rows, unmatched = village_rows("tao", [
            vill("68000010001", "桃園區", "甲里"),   # 代碼直接命中
            vill("68000030099", "大溪區", "新設里"),  # 沒命中，鄉鎮只屬一區 → 繼承
            vill("68000010099", "桃園區", "幸福里"),  # 沒命中，鄉鎮跨區 → 不猜
        ], LI_ROWS, "https://x/L.json", "T")
        self.assertEqual({r["villcode"]: r["district_id"] for r in rows},
                         {"68000010001": "ly-tao-01", "68000030099": "ly-tao-02"})
        self.assertEqual(unmatched, [("68000010099", "桃園市", "桃園區", "幸福里", ["01", "04"])])
        self.assertEqual({r["office"] for r in rows}, {"legislator"})


class TestExportCounties(unittest.TestCase):
    def test_counties_json_lists_districts_of_each_county(self):
        conn = connect(":memory:")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        upsert(conn, "county", {"iso": "tao", "moi_code": "68000", "name": "桃園市",
                                "source_url": "https://x", "fetched_at": "T"}, ("iso",))
        for did, office in (("tao-council-01", "tao_councilor"), ("tao-mayor", "tao_mayor"),
                            ("ly-tao-01", "legislator"), ("tpe-mayor", "tpe_mayor")):
            upsert(conn, "district", {"district_id": did, "office": office, "name": did, "seats": 1,
                                      "source_url": "https://x", "fetched_at": "T"}, ("district_id",))
        with tempfile.TemporaryDirectory() as tmp:
            export(conn, Path(tmp))
            got = json.loads((Path(tmp) / "counties.json").read_text(encoding="utf-8"))
        [county] = got["counties"]
        self.assertEqual((county["iso"], county["moi_code"], county["name"]), ("tao", "68000", "桃園市"))
        self.assertEqual([d["district_id"] for d in county["districts"]], ["ly-tao-01", "tao-council-01", "tao-mayor"])


if __name__ == "__main__":
    unittest.main()
