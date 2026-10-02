"""五都議會官網的現任議員名錄解析（純函式）。以官網名錄為現任依據。"""
import re

from etl.fetch import get

_TNN = "https://www.tncc.gov.tw/subhome.asp?orcaid=C56635AE-3C35-4233-8561-7B2CAA2DF01F&orcaid2="
# 臺南 13 個選區頁的 orcaid2
TNN_GUIDS = [
    "2EA7C45E-0A30-47A1-B6E8-903F9106F680",
    "7D86624A-5FF3-4E34-B1D6-3899EEA0E90D",
    "ECECDC5D-54AC-41D9-9C64-C7B6C971C673",
    "F8FB1DF0-F5A9-46CC-8EA5-CBF5BA021C86",
    "11EA1727-57A4-4D44-9A91-51298F0F909E",
    "28D59728-B4F9-4F47-89E1-E08A4B2AEDE7",
    "775CE00E-4BA7-40AA-A45E-EA973CFB28BA",
    "E9E12C20-847F-4FAB-B514-09D7D1F18CF6",
    "F28D4D0E-6FBA-47C6-A39D-09985BCE9138",
    "B9A563CB-864A-40B8-9BAF-CD77404D2161",
    "CE4A0D3B-E8AF-4EB2-979A-2542DC560C18",
    "97CC8734-8DE1-4B85-B806-1D44689C25AD",
    "C032D0E4-3164-42F9-B7C6-27E034EC562F",
]
ROSTER_URLS = {
    "nwt": "https://www.ntp.gov.tw/councilor-all?program=37",
    "tao": [f"https://www.tycc.gov.tw/TC/councilor-all.aspx?mid=39&area={n}" for n in range(1, 15)],
    "txg": "https://www.tccc.gov.tw/wb_introduction01.asp",
    "tnn": [_TNN + g for g in TNN_GUIDS],
    "khh": "https://www.kcc.gov.tw/Member_List3.aspx?n=39&sms=9028",
}
# 臺南、高雄在姓名後加註離職
_MARK = re.compile(r"\((歿|解職[^)]*|轉任[^)]*)\)")
_NUM = {c: i for i, c in enumerate("一二三四五六七八九十", 1)}


def _row(iso, n, name):
    m = _MARK.search(name)
    return {"iso": iso, "district_n": n, "name": _MARK.sub("", name).strip(),
            "current": m is None, "note": m.group(1) if m else ""}


def _cn(s):  # 一～十九
    return 10 + _NUM.get(s[1:], 0) if s.startswith("十") else _NUM[s]


def parse_nwt(html):
    out = []
    for sec in re.split(r'<h4><span>第(?=\d+選區議員介紹)', html)[1:]:
        n = int(re.match(r"\d+", sec).group())
        out += [_row("nwt", n, x) for x in re.findall(r"<a href=\"councilor-detail[^>]*>.*?<p>\s*([^<]*?)\s*</p>", sec, re.S)]
    return out


def parse_tao(pages):
    """pages：14 個選區頁 HTML，依選區順序。"""
    return [_row("tao", i, re.sub(r"\s+(副?議長|議員)$", "", x))
            for i, h in enumerate(pages, 1)
            for x in re.findall(r"<p>\s*([^<]*?)\s*</p>", h) if re.search(r"\s(副?議長|議員)$", x)]


def parse_txg(html):
    out = []
    for sec in re.split(r'Mcouncillor_title">第', html)[1:]:
        n = _cn(re.match(r"[一二三四五六七八九十]+(?=選區)", sec).group())
        out += [_row("txg", n, x.strip()) for x in re.findall(r'list_note"><a[^>]*>([^<]*)<', sec)]
    return out


def parse_tnn(pages):
    """pages：13 個選區頁 HTML，依選區順序。"""
    return [_row("tnn", i, x) for i, h in enumerate(pages, 1)
            for x in re.findall(r"peoplebold[^>]*>([^<]*)<", h)]


def parse_khh(html):
    out = []
    for sec in re.split(r"<h4>第 <span>", html)[1:]:
        n = int(re.match(r"\d+", sec).group())
        out += [_row("khh", n, x) for x in re.findall(r'class="kcc-link link"[^>]*>.*?<span>([^<]*)</span>', sec)]
    return out


PARSERS = {"nwt": parse_nwt, "tao": parse_tao, "txg": parse_txg, "tnn": parse_tnn, "khh": parse_khh}


def fetch_roster(iso):
    url = ROSTER_URLS[iso]
    if isinstance(url, list):
        pages = [get(u).decode("utf-8") for u in url]
        return PARSERS[iso](pages)
    return PARSERS[iso](get(url).decode("utf-8"))


if __name__ == "__main__":
    import json
    import re
    from pathlib import Path

    from etl.cec2022 import SOURCES, parse_candidates
    from etl.match import _norm

    cache = Path("data/cache/v13")
    names = ["c1", "c2", "c2r", "cec_T1_T1", "cec_T1_T2", "cec_T1_T3", "cec_T2_T1", "cec_T2_T2", "cec_T2_T3"]
    won = [c for (kind, _), n in zip(SOURCES, names)
           for c in parse_candidates(json.loads((cache / f"{n}.json").read_text()), kind)
           if c["kind"] and c["elected"]]
    ros = cache / "ros"
    rd = lambda f: (ros / f).read_text()
    pages = {
        "nwt": rd("nwt_all.html"), "txg": rd("txg_list.html"), "khh": rd("khh_list.html"),
        "tao": [rd(f"tao_a{i}.html") for i in range(1, 15)],
        "tnn": [rd(f"tnn_a{i}.html") for i in range(1, 14)],
    }
    VAR = str.maketrans("黄啓釆", "黃啟采")
    han = lambda name: re.sub(r"[^一-鿿]", "", _norm(name))  # 原住民姓名中英並列，只比漢字
    key = lambda n, name: (n, han(name).translate(VAR))
    for iso, parse in PARSERS.items():
        rows = parse(pages[iso])
        cur = [r for r in rows if r["current"]]
        w = [c for c in won if c["iso"] == iso]
        wk = {key(c["district_n"], c["name"]) for c in w}
        rk = {key(r["district_n"], r["name"]) for r in rows}
        raw = {(c["district_n"], han(c["name"])) for c in w}
        var = [r["name"] for r in rows if key(r["district_n"], r["name"]) in wk
               and (r["district_n"], han(r["name"])) not in raw]
        gone = [c["name"] for c in w if key(c["district_n"], c["name"]) not in rk]
        left = [r["name"] for r in rows if not r["current"]]
        new = [(r["district_n"], r["name"]) for r in cur if key(r["district_n"], r["name"]) not in wk]
        print(f"{iso}: 列出 {len(rows)} 現任 {len(cur)} 離職 {left + gone} 遞補 {new} 異體字 {var}")
