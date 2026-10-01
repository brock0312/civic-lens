"""內政部國土測繪中心村里界（data.gov.tw 7438）的屬性表：全國現行村里、鄉鎮與縣市代碼。"""
import io
import re
import struct
import urllib.parse
import zipfile
from functools import lru_cache

from etl.fetch import get

# 資料集 https://data.gov.tw/dataset/7438，政府資料開放授權條款第 1 版；V2 驗證時是 115-08-17 版（VILLAGE_NLSC_1150817）
VILLAGE_ZIP_URL = "https://www.tgos.tw/tgos/VirtualDir/Product/a04697c8-64db-450a-a105-3eb471c45abd/" + urllib.parse.quote(
    "村(里)界(TWD97經緯度).zip"
)
DBF_NAME = re.compile(r"VILLAGE_NLSC_\d+\.dbf")

# 內政部村里名用「[X]」標記造字；改用中選會的寫法（2024 第 11 屆立委開票 JSON 的 L 檔 area_name，
# 以 VILLCODE 對照，2026-10-02 逐筆取得）。括號內常是替代字，不能只拿掉括號（例：[曹] → 𥕢）。
# 龜売里、檨林里的中選會原文是相容表意字 U+2F85A、U+2F8EB，這裡存 NFC 正規化後的 U+58F2、U+6AA8（同一字，字型支援較廣）。
# 水林鄉 [欍]埔村 中選會寫作「瓊埔村」，照錄。
CEC_VILLNAMES = {
    "10007010030": "磚磘里", "10007140010": "瓦磘村", "10008040005": "硘磘里", "10009130003": "瓦磘村",
    "10009170018": "瓦磘村", "10009180016": "萡子村", "10009180021": "萡東村", "10009200021": "瓊埔村",
    "10013170001": "瓦磘村", "10016010031": "嵵裡里", "10020020018": "磚磘里", "65000030017": "瓦磘里",
    "65000030054": "灰磘里", "65000070007": "獇寮里", "65000200004": "石\U00025562里", "66000220004": "龜売里",
    "67000140004": "檨林里", "67000180018": "\U00026C21拔里", "67000300008": "石\U00025562里",
    "67000350003": "塭南里", "67000350024": "公塭里",
}


def read_dbf(data):
    """dBase III 表 → [dict]。只處理文字欄（這份表全是 C 型欄位），跳過已刪除列。"""
    n, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields, pos = [], 32
    while data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\0")[0].decode("ascii")
        fields.append((name, data[pos + 16]))
        pos += 32
    rows = []
    for i in range(n):
        rec = data[header_len + i * record_len: header_len + (i + 1) * record_len]
        if rec[:1] == b"*":
            continue
        row, off = {}, 1
        for name, length in fields:
            row[name] = rec[off:off + length].decode("utf-8").strip()
            off += length
        rows.append(row)
    return rows


def villages_from_zip(zip_bytes):
    """回傳有名稱的現行村里（NOTE=未編定村里 的多邊形沒有 VILLNAME，排除）。"""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = [n for n in z.namelist() if DBF_NAME.fullmatch(n)]
        if len(names) != 1:
            raise ValueError(f"村里界 zip 內找不到唯一的 VILLAGE_NLSC_*.dbf：{z.namelist()}")
        rows = read_dbf(z.read(names[0]))
    out = [{**r, "VILLNAME": CEC_VILLNAMES.get(r["VILLCODE"], r["VILLNAME"])} for r in rows if r["VILLNAME"]]
    bad = [(r["VILLCODE"], r.get("TOWNNAME"), r["VILLNAME"]) for r in out
           if "[" in r["VILLNAME"] or "[" in r.get("TOWNNAME", "")]
    if bad:
        raise ValueError(f"村里表有未對照的造字標記，請補進 CEC_VILLNAMES：{bad}")
    codes = [r["VILLCODE"] for r in out]
    if len(codes) != len(set(codes)):
        raise ValueError("村里表 VILLCODE 重複")
    return out


# ponytail: 每次執行下載一次約 21 MB 的 zip，兩個來源共用快取；變慢再改成落地快取
@lru_cache(maxsize=1)
def villages():
    return villages_from_zip(get(VILLAGE_ZIP_URL))
