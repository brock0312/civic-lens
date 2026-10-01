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
    out = [r for r in rows if r["VILLNAME"]]
    codes = [r["VILLCODE"] for r in out]
    if len(codes) != len(set(codes)):
        raise ValueError("村里表 VILLCODE 重複")
    return out


# ponytail: 每次執行下載一次約 21 MB 的 zip，兩個來源共用快取；變慢再改成落地快取
@lru_cache(maxsize=1)
def villages():
    return villages_from_zip(get(VILLAGE_ZIP_URL))
