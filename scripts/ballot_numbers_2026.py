"""官方號次清單（CSV）→ data/candidates_2026_status.csv 的 ballot 列（11/12 縣市長、11/17 議員名單公告後用）。

2026 的官方格式還沒出來；依 2022 前例（data.gov.tw「地方首長民意代表候選人」CSV：選舉區、姓名、抽籤號次）寫成
欄名寬鬆辨識：含「選舉區」或「選區」的欄、含「姓名」的欄、含「號次」的欄；選舉區沒寫縣市時，用含「縣市」或「選舉名稱」的欄補。
PDF 公告請先轉成 CSV（例如 pdftotext 後整理）再餵進來。

輸出的列 confirmed_by、confirmed_at 留空：人工逐區核對官方公告後填上，candidates_2026_status 才會收（缺欄位會 raise）。

用法：python3 scripts/ballot_numbers_2026.py 官方.csv 公告網址 公告日期(YYYY-MM-DD) > /tmp/ballot.csv
      對不上 district 的列印到 stderr，exit 1。
"""
import csv
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from etl.sources.candidates_2026_status import FIELDS  # noqa: E402
from etl.sources.national_districts import ISO, council_id  # noqa: E402

_AREA = re.compile(r"(..[縣市])?\s*(?:第\s*0*(\d+)\s*選(?:舉)?區)?")
_CN = {c: i for i, c in enumerate("一二三四五六七八九", 1)}


def _col(header, *keys):
    return next((i for i, h in enumerate(header) if any(k in h for k in keys)), None)


def district_of(area, county=""):
    """'臺北市第01選舉區' → 'tpe-council-01'；'新竹縣' → 'hsq-mayor'；選舉區沒寫縣市時用 county 補。對不上回 None。"""
    area = str(area).strip().replace("台", "臺")
    county = str(county).strip().replace("台", "臺")[:3]
    m = _AREA.fullmatch(area)
    if not m:
        return None
    name = m.group(1) or county
    if name not in ISO:
        return None
    return council_id(ISO[name], int(m.group(2))) if m.group(2) else f"{ISO[name]}-mayor"


def convert(text, source_url, announced_on):
    """回傳 (status 列, 對不上的原始列)。純函式。"""
    rows = [r for r in csv.reader(io.StringIO(text.lstrip("﻿"))) if any(c.strip() for c in r)]
    header, body = rows[0], rows[1:]
    area_i, name_i, no_i = _col(header, "選舉區", "選區"), _col(header, "姓名"), _col(header, "號次")
    county_i = _col(header, "縣市", "選舉名稱")
    if None in (area_i, name_i, no_i):
        raise ValueError(f"認不得欄名（需要選舉區、姓名、號次）：{header}")
    out, bad = [], []
    for r in body:
        did = district_of(r[area_i], r[county_i] if county_i is not None else "")
        no = r[no_i].strip()
        if not did or not no.isdigit():
            bad.append(r)
            continue
        out.append({"event": "ballot", "district_id": did, "name": r[name_i].strip(), "value": str(int(no)),
                    "source_url": source_url, "announced_on": announced_on, "confirmed_by": "", "confirmed_at": "",
                    "note": ""})
    return out, bad


def main(argv):
    path, url, on = argv[1:4]
    rows, bad = convert(Path(path).read_text(encoding="utf-8-sig"), url, on)
    w = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(rows)
    for r in bad:
        print(f"對不上：{r}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
