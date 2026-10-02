"""五都議會官網的現任議員名錄解析（純函式）。以官網名錄為現任依據。"""
import re
import time
from pathlib import Path

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
    # 單頁靜態縣市（V13 §3.2；robots 都未擋名錄路徑）
    "hsq": "https://www.hcc.gov.tw/member?lang=&program=190",
    "cha": "https://www.chcc.gov.tw/member/index.aspx?Parser=99,6,40",
    "nan": "https://www.ntcc.gov.tw/tw/rep/index.aspx",
    "yun": "https://www.ylcc.gov.tw/cp.aspx?n=22126",
    "pif": "https://www.ptcc.gov.tw/?Page=Persional&Guid=1c445ed1-8f2f-4c7f-75f6-6d6aafa3516e",
    "ila": "https://www.ilcc.gov.tw/Html/H_05/H_05.asp",
    "hua": "https://www.hlcc.gov.tw/councillor.php",
    "pen": "https://www.phcouncil.gov.tw/meet.php",
    "kin": "https://www.kmcc.gov.tw/8844/54357/55476/",
    "lie": "https://www.mtcc.gov.tw/ch/counciler_introlist/7190",
    "kee": "https://www.kmc.gov.tw/index.php/mac/mi",
}
_OLD = {"nwt", "tao", "txg", "tnn", "khh"}
_ENC = {"ila": "big5"}
_IPV4 = {"tao"}  # 桃園議會的 IPv6 位址連不上（2026-10-02 實測）
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


def _nm(x):  # 去掉所有空白（含全形），「林 麗」「陳　宜」→ 無空白
    return re.sub(r"\s", "", x)


def parse_hsq(html):
    out = []
    for sec in re.split(r'member-container-title">第', html)[1:]:
        n = _cn(re.match(r"[一二三四五六七八九十]+", sec).group())
        out += [_row("hsq", n, _nm(x)) for x in re.findall(r'<li class="member-container-bottom"><a [^>]*title="([^"]*)"', sec)]
    return out


def parse_cha(html):
    out = []
    for n, body in re.findall(r"key: 'area(\d+)',toolTip: '<strong[^>]*>[^<]*</strong><br/><span[^>]*>(.*?)</span>", html):
        out += [_row("cha", int(n), _nm(x)) for x in re.split(r"、|<br/>", body) if x.strip()]
    return out


def parse_nan(html):  # 正副議長在頁面上出現兩次，去重
    pairs = dict.fromkeys(re.findall(r'p02\.aspx\?district=(\d+)&period=\d+#([^"]+)"', html))
    return [_row("nan", int(n), _nm(x)) for n, x in pairs]


def parse_yun(html):
    out = []
    for n, sec in re.findall(r'<a\s+href="#"\s+title="第([一二三四五六七八九十]+)選區"(.*?)(?=<a\s+href="#"\s+title="第|$)', html, re.S):
        out += [_row("yun", _cn(n), _nm(x)) for x in re.findall(r'<div class="caption">([^<]*)</div>', sec)]
    return out


def parse_pif(html):
    out = []
    for sec in re.split(r'evacategory"[^>]*>第', html)[1:]:
        n = _cn(re.match(r"[一二三四五六七八九十]+", sec).group())
        out += [_row("pif", n, _nm(x)) for x in re.findall(r'PersionalDetail&Guid=[^"]*">([^<]*)<', sec)]
    return out


def parse_ila(html):
    out = []
    for sec in re.split(r'alt="第(?=\d+選區)', html)[1:]:
        n = int(re.match(r"\d+", sec).group())
        out += [_row("ila", n, _nm(x)) for x in re.findall(r'title="([^"]*?)議員相關資料"', sec)]
    return out


def parse_hua(html):
    out = []
    for sec in re.split(r'<h3 class="text-normal">第', html)[1:]:
        n = _cn(re.match(r"[一二三四五六七八九十]+", sec).group())
        out += [_row("hua", n, re.sub(r"副?議[長員]|\s", "", x)) for x in re.findall(r'text-header"><a[^>]*>([^<]*)<', sec)]
    return out


def parse_pen(html):
    # 名錄頁沒有選區資訊，district_n 一律 None
    return [_row("pen", None, _nm(re.sub(r"副?議[長員]$", "", x.strip())))
            for x in re.findall(r'meet\.php\?councillor=M\d+">([^<]*)<', html)]


def parse_kin(html):
    out = []
    for sec in re.split(r"<h3>第", html)[1:]:
        m = re.match(r"([一二三四五六七八九十]+)選區/", sec)
        if m:
            out += [_row("kin", _cn(m.group(1)), _nm(x)) for x in re.findall(r'<li>\s*<a [^>]*title="([^"]*)"', sec.split("</ul>")[0])]
    return out


def parse_lie(html):
    out = []
    for sec in re.split(r'alt="第(?=[一二三四五六七八九十]+選區－)', html)[1:]:
        n = _cn(re.match(r"[一二三四五六七八九十]+", sec).group())
        out += [_row("lie", n, _nm(x)) for x in re.findall(r"(?:副?議長|議員)\s*：\s*([^<]*)<", sec.split("</ul>")[0])]
    return out


def parse_kee(html):
    out = []
    for n, sec in enumerate(re.split(r'<i class="fa fa-square" aria-hidden="true"></i>', html)[1:], 1):
        out += [_row("kee", n, _nm(re.sub(r"議員$", "", x.strip()))) for x in re.findall(r'itemprop="url">([^<]*議員)</a></h3>', sec)]
    return out


PARSERS = {"nwt": parse_nwt, "tao": parse_tao, "txg": parse_txg, "tnn": parse_tnn, "khh": parse_khh,
           "hsq": parse_hsq, "cha": parse_cha, "nan": parse_nan, "yun": parse_yun, "pif": parse_pif, "ila": parse_ila,
           "hua": parse_hua, "pen": parse_pen, "kin": parse_kin, "lie": parse_lie, "kee": parse_kee}


def fetch_roster(iso):
    url = ROSTER_URLS[iso]
    if isinstance(url, list):
        pages = []
        for u in url:  # 同一主機逐頁抓，間隔 1.1 秒
            time.sleep(1.1)
            pages.append(get(u, ipv4=iso in _IPV4).decode("utf-8"))
        return PARSERS[iso](pages)
    html = get(url, ipv4=iso in _IPV4).decode(_ENC.get(iso, "utf-8"))
    if iso not in _OLD:  # 新縣市存快取供測試與重跑；單頁、每縣市一個主機，不需間隔
        (Path("data/cache/rosters") / f"{iso}.html").write_text(html, encoding="utf-8")
    return PARSERS[iso](html)


if __name__ == "__main__":
    import json

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
    for iso in PARSERS.keys() - _OLD:
        pages[iso] = (Path("data/cache/rosters") / f"{iso}.html").read_text(encoding="utf-8")
    VAR = str.maketrans("黄啓釆姫", "黃啟采姬")
    han = lambda name: re.sub(r"[^一-鿿]", "", _norm(name.replace("@FA3E@", "慨")))  # 原住民姓名中英並列，只比漢字
    key = lambda n, name: (None if iso == "pen" else n,  # 澎湖名錄無選區
                            han(name).translate(VAR))
    for iso, parse in PARSERS.items():
        rows = parse(pages[iso])
        cur = [r for r in rows if r["current"]]
        w = [c for c in won if c["iso"] == iso]
        wk = {key(c["district_n"], c["name"]) for c in w}
        rk = {key(r["district_n"], r["name"]) for r in rows}
        raw = {(key(c["district_n"], "")[0], han(c["name"])) for c in w}
        var = [r["name"] for r in rows if key(r["district_n"], r["name"]) in wk
               and (key(r["district_n"], "")[0], han(r["name"])) not in raw]
        gone = [c["name"] for c in w if key(c["district_n"], c["name"]) not in rk]
        left = [r["name"] for r in rows if not r["current"]]
        new = [(r["district_n"], r["name"]) for r in cur if key(r["district_n"], r["name"]) not in wk]
        print(f"{iso}: 列出 {len(rows)} 現任 {len(cur)} 當選 {len(w)} 離職 {left + gone} 遞補 {new} 異體字 {var}")
