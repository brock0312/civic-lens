"""2022（111 年）選舉公報目錄：爬 bulletin.cec.gov.tw，建「PDF → 涵蓋選區」對照表。

規格見 docs/validation/V13-l3a-basic.md §1.1、§1.2。不拼檔名：爬目錄後從檔名（或子目錄名）解析區號，
再以 OVERRIDES 處理檔名沒寫出來的合併（首長與議員同檔、原住民選區併入區域檔等）。
"""
import re
import time
import urllib.parse
import urllib.request

from etl.fetch import UA, get
from etl.sources.national_districts import ISO

BASE = "https://bulletin.cec.gov.tw/"
ROOTS = [f"01選舉公報/{c}/111年" for c in ("03直轄市長", "04縣市長", "05直轄市議員", "06縣市議員")]
_P = "01選舉公報/"

# 檔名沒寫出來的涵蓋範圍：path → 完整 districts（取代解析結果）。依據皆為 V13 §1.2。
OVERRIDES = {
    # 彰化第 01 檔標題「第一、九選舉區」（第 9 區平地原住民）
    _P + "06縣市議員/111年/09彰化縣/彰化縣第01選舉區.pdf": [["councilor", 1], ["councilor", 9]],
    # 基隆第 1 檔標題「第一、八選區」（第 8 區平地原住民）
    _P + "06縣市議員/111年/20基隆市/第1選舉區/基隆市選舉公報_第一選區.pdf": [["councilor", 1], ["councilor", 8]],
    # 新北市長檔與 12 號議員檔是同一份 PDF（md5 相同）：第 1 頁市長＋第 13 區（山地），第 2 頁第 12 區（平地原住民）
    _P + "03直轄市長/111年/新北市市長.pdf": [["councilor", 12], ["councilor", 13], ["mayor", None]],
    _P + "05直轄市議員/111年/02新北市/12-新北市選舉公報-第十二、十三選區.pdf":
        [["councilor", 12], ["councilor", 13], ["mayor", None]],
    # 新竹市第 6 區也印在市長公報第 1 頁
    _P + "04縣市長/111年/01紙本公報/新竹市市長.pdf": [["councilor", 6], ["mayor", None]],
    # 宜蘭第 1 檔標題「第一、十一、十二選舉區」，縣長也印在這檔
    _P + "06縣市議員/111年/14宜蘭縣/宜蘭縣第1選舉區.pdf":
        [["councilor", 1], ["councilor", 11], ["councilor", 12], ["mayor", None]],
    # 金門、連江縣長也印在議員檔
    _P + "06縣市議員/111年/18金門縣/02議員第一選區公報.pdf": [["councilor", 1], ["mayor", None]],
    _P + "06縣市議員/111年/18金門縣/02議員第二選區公報.pdf": [["councilor", 2], ["mayor", None]],
    _P + "06縣市議員/111年/18金門縣/02議員第三選區公報.pdf": [["councilor", 3], ["mayor", None]],
    _P + "06縣市議員/111年/19連江縣/連江縣第01選舉區.pdf": [["councilor", 1], ["mayor", None]],
    _P + "06縣市議員/111年/19連江縣/連江縣第02選舉區.pdf": [["councilor", 2], ["mayor", None]],
    _P + "06縣市議員/111年/19連江縣/連江縣第03選舉區.pdf": [["councilor", 3], ["mayor", None]],
    _P + "06縣市議員/111年/19連江縣/連江縣第04選舉區.pdf": [["councilor", 4], ["mayor", None]],
    # 臺中市長公報與第 1 區議員同一份（兩份 PDF 第 1 頁相同）
    _P + "03直轄市長/111年/臺中市市長.pdf": [["councilor", 1], ["mayor", None]],
    # 臺北 07、08 兩檔內容相同，都含第 7、8 區
    _P + "05直轄市議員/111年/01臺北市/臺北市第07選舉區.pdf": [["councilor", 7], ["councilor", 8]],
    _P + "05直轄市議員/111年/01臺北市/臺北市第08選舉區.pdf": [["councilor", 7], ["councilor", 8]],
    # 切格實測（etl/bulletin_grid.py 報告）：金門縣長檔也含議員第一區。
    # ponytail: 新竹縣第 01 檔也印了第 2、3 區，但兩區各有自己的檔，切格器把它們當「不在此檔」丟掉即可，不覆寫
    _P + "04縣市長/111年/01紙本公報/金門縣縣長.pdf": [["councilor", 1], ["mayor", None]],
    # 屏東第 1 區拆兩檔，檔名結尾的 1、2 是分冊序號不是區號
    _P + "06縣市議員/111年/13屏東縣/屏東縣第01選舉區1.pdf": [["councilor", 1]],
    _P + "06縣市議員/111年/13屏東縣/屏東縣第01選舉區2.pdf": [["councilor", 1]],
}

_CN = {c: i for i, c in enumerate("一二三四五六七八九", 1)}
_DIST = re.compile(r"第([0-9一二三四五六七八九十、.及\-第]+?)選")


def _num(s):
    if s.isdigit():
        return int(s)
    if "十" in s:  # 十、十一～十九
        head, _, tail = s.partition("十")
        return (_CN[head] if head else 1) * 10 + (_CN[tail] if tail else 0)
    return _CN[s]


def parse_districts(name):
    """'第8、13-16選舉區' → [8, 13, 14, 15, 16]；找不到「第…選」回 []。"""
    m = _DIST.search(name)
    if not m:
        return []
    out = set()
    for tok in re.split(r"[、.及]", m.group(1).replace("第", "")):
        a, _, b = tok.partition("-")
        out.update(range(_num(a), _num(b) + 1) if b else [_num(a)])
    return sorted(out)


def _county(path):
    parts = path.split("/")
    if parts[1] in ("03直轄市長", "04縣市長"):
        name = parts[-1]
    else:
        name = parts[3].lstrip("0123456789")
    return ISO[name.replace("台", "臺")[:3]]


def file_map(index):
    """[{path, size}] → [{path, iso, districts}]；排除罷免公告。無法解析的檔 raise。"""
    out = []
    for f in index:
        path = f["path"]
        if "罷免" in path:  # 新竹市罷免公告（114 年），不是 2022 公報
            continue
        if path in OVERRIDES:
            districts = OVERRIDES[path]
        elif "長/" in path.split("111年")[0]:  # 03直轄市長、04縣市長
            districts = [["mayor", None]]
        else:
            name = path.rsplit("/", 1)[-1]
            ns = parse_districts(name) or parse_districts(path.rsplit("/", 2)[-2])
            if not ns:
                raise ValueError(f"檔名找不到區號：{path}")
            districts = [["councilor", n] for n in ns]
        out.append({"path": path, "iso": _county(path),
                    "districts": sorted(districts, key=lambda d: (d[0], d[1] or 0))})
    return out


_last = [0.0]


def _req(url, method="GET"):
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    try:
        if method == "GET":
            return get(url)
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method=method)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.headers
    finally:
        _last[0] = time.time()


def _ls(d):
    html = _req(BASE + "?dir=" + urllib.parse.quote(d)).decode("utf-8")
    main = html.split('id="main-content"', 1)[1].split("</main>", 1)[0]
    dirs = [urllib.parse.unquote(h) for h in re.findall(r'href="\?dir=([^"]+)"', main)]
    files = re.findall(r'href="([^"?#]+\.pdf)"', main, re.I)
    return dirs, files


def crawl_index():
    """遞迴列出 4 個 111 年目錄，HEAD 每個 PDF 取大小。約 200 檔 × 1.1 秒。"""
    out, stack = [], list(ROOTS)
    while stack:
        dirs, files = _ls(stack.pop(0))
        stack += dirs
        for f in files:
            size = int(_req(BASE + urllib.parse.quote(f), "HEAD").get("Content-Length", -1))
            out.append({"path": f, "size": size})
    return out


if __name__ == "__main__":
    import json
    import sys

    idx = crawl_index()
    json.dump(idx, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
    print("files", len(idx), "mapped", len(file_map(idx)))
