"""全國 22 縣市：county 表、2026 縣市長與議員選區、村里 → 議員選區（L1，V11 §2–§4）。

選區全部以中選會 1153150253 號公告為準；村里以內政部村里表（data.gov.tw 7438）為主表。
臺北市的區域選區、市長與里對照由 tpe_districts 負責，這裡只寫臺北的原住民選區 village_district 列。
"""
import re

from etl import cec_pdf, moi
from etl.db import upsert
from etl.fetch import get, now_utc, pdf_text
from etl.sources.tpe_districts import COUNCIL_URL as ANN_URL

# 縣市代碼 = ISO 3166-2:TW 的小寫後三碼。
# 出處：https://en.wikipedia.org/wiki/ISO_3166-2:TW（2026-09-30 取原始碼逐列核對 22 碼皆相符），
# 權威版本見 ISO Online Browsing Platform https://www.iso.org/obp/ui/#iso:code:3166:TW
# 順序同 1153150253 號公告「三、(三)(四)」議員表的縣市順序（parse_announcement 依此對應）。
COUNTIES = [
    ("tpe", "臺北市"), ("nwt", "新北市"), ("tao", "桃園市"), ("txg", "臺中市"), ("tnn", "臺南市"),
    ("khh", "高雄市"), ("hsq", "新竹縣"), ("mia", "苗栗縣"), ("cha", "彰化縣"), ("nan", "南投縣"),
    ("yun", "雲林縣"), ("cyq", "嘉義縣"), ("pif", "屏東縣"), ("ila", "宜蘭縣"), ("hua", "花蓮縣"),
    ("ttt", "臺東縣"), ("pen", "澎湖縣"), ("kin", "金門縣"), ("lie", "連江縣"), ("kee", "基隆市"),
    ("hsz", "新竹市"), ("cyi", "嘉義市"),
]
ISO = {name: iso for iso, name in COUNTIES}
KINDS = {"平地原住民": "plains", "山地原住民": "mountain"}

ANCHOR = re.compile(r"^第(\d+)選舉區$")


def council_id(iso, n):
    return f"{iso}-council-{n:02d}"


def parse_council_tables(bbox):
    """公告的直轄市議員、縣市議員選舉區表 → {縣市名: [{"n", "seats", "range"}]}。

    欄位位置（選舉區 x0<205、範圍 200≤x0<300、名額 340≤x0<385）是這份公告的版面；版面不同時，
    後續的名額總和與鄉鎮展開檢查會 raise。
    """
    rows = []
    for words in cec_pdf.pages(bbox):
        headers = [y0 for _, y0, _, _, t in words if t == "範圍"]
        anchors = sorted(((y0 + y1) / 2, int(ANCHOR.match(t).group(1)))
                         for x0, y0, x1, y1, t in words if ANCHOR.match(t) and x0 < 205)
        if not anchors:
            continue
        seat_words = [((y0 + y1) / 2, int(t)) for x0, y0, x1, y1, t in words
                      if re.fullmatch(r"\d+", t) and 340 <= x0 < 385]
        cells = [w for w in words
                 if 200 <= w[0] < 300 and not re.fullmatch(r"[\d,]+", w[4]) and "選舉區" not in w[4]
                 and not any(hy - 50 <= w[1] <= hy + 10 for hy in headers)]
        lines = cec_pdf.group_lines(cells)
        ys = sorted(lines)
        page_rows = [{"n": n, "yc": yc, "seats": next((s for sy, s in seat_words if abs(sy - yc) < 3), None)}
                     for yc, n in anchors]
        # 上一頁最後一列的範圍可能跨到本頁頁首：跳過開頭 k 行、把它們併回上一列
        err = None
        for k in range(10):
            try:
                groups = cec_pdf.assign(ys[k:], lines, [r["yc"] for r in page_rows], optional=False, loose_last=True)
                break
            except ValueError as e:
                err = e
        else:
            raise err
        if k:
            rows[-1]["lines"] += [cec_pdf.line_text(lines[y]) for y in ys[:k]]
        for r, g in zip(page_rows, groups):
            rows.append({**r, "lines": [cec_pdf.line_text(lines[y]) for y in g]})

    out, ci = {}, -1
    for r in rows:
        if r["n"] == 1:
            ci += 1
        if ci >= len(COUNTIES) or r["seats"] is None:
            raise ValueError(f"公告議員表解析失敗：{r}")
        out.setdefault(COUNTIES[ci][1], []).append(
            {"n": r["n"], "seats": r["seats"], "range": "".join(r["lines"]).replace(" ", "")})
    if list(out) != [name for _, name in COUNTIES]:
        raise ValueError(f"公告議員表的縣市數不符：{list(out)}")
    for county, ds in out.items():
        if [d["n"] for d in ds] != list(range(1, len(ds) + 1)):
            raise ValueError(f"{county} 選舉區編號不連續：{[d['n'] for d in ds]}")
    return out


def parse_totals(text):
    """公告各縣市「合計」格：[{"total", "regional", "plains", "mountain"}]，依公告順序。"""
    blocks = re.split(r"議員總額：", text)[1:]
    if len(blocks) != len(COUNTIES):
        raise ValueError(f"「議員總額」出現 {len(blocks)} 次，應為 {len(COUNTIES)}")
    out = []
    for b in blocks:
        def num(label):
            m = re.search(label + r"：\s*(\d+)\s*名", b)
            return int(m.group(1)) if m else None
        total = int(re.match(r"\s*(\d+)\s*名", b).group(1))
        plains, mountain = num("平地原住民") or 0, num("山地原住民") or 0
        # 沒有原住民選區的縣市（澎湖、金門、連江、嘉義市）只寫議員總額，沒有區域小計
        regional = num("區域")
        if regional is None:
            if plains or mountain:
                raise ValueError(f"合計格有原住民小計卻沒有區域小計：{b[:80]!r}")
            regional = total
        out.append({"total": total, "regional": regional, "plains": plains, "mountain": mountain})
    return out


def parse_mayors(text):
    """公告「三、(一)(二)」→ {縣市名: 名額}。原文的「市」有時寫成異體字「巿」。"""
    m = re.search(r"三、選舉區劃分.*?\(一\)直轄市長(.*?)\(三\)", text.replace("巿", "市"), re.S)
    if not m:
        raise ValueError("公告找不到直轄市長、縣（市）長名額表")
    got = {name: int(seats) for name, seats in re.findall(r"(\S+[縣市])\s+(\d+)\s+[\d,]+", m.group(1))}
    if set(got) != set(ISO):
        raise ValueError(f"縣市長名額表的縣市不符：{sorted(set(got) ^ set(ISO))}")
    return got


def kind_of(rng):
    for label, kind in KINDS.items():
        if rng.endswith("之" + label):
            return kind
    return None


def check_totals(tables, totals):
    """每縣市：各選區名額總和＝議員總額，區域／平地／山地小計也要相符；不符就 raise。"""
    for (county, ds), t in zip(tables.items(), totals):
        got = {"total": sum(d["seats"] for d in ds), "regional": 0, "plains": 0, "mountain": 0}
        for d in ds:
            got[kind_of(d["range"]) or "regional"] += d["seats"]
        if got != t:
            raise ValueError(f"{county} 名額總和 {got} 與公告合計 {t} 不符")


def expand_regional(county, rng, universe):
    """把區域選區的「範圍」字串展開成 universe 內的 (鄉鎮, 村里) 集合；對不到或不唯一就 raise。"""
    towns = {t for t, _ in universe}
    out, cur_town = set(), None
    for tok in rng.split("、"):
        if tok in towns:
            out |= {(t, v) for t, v in universe if t == tok}
            cur_town = None
            continue
        m = re.match(r"^(.+?[鄉鎮市區])(.+[村里])$", tok)
        if m and m.group(1) in towns:
            cur_town, tok = m.group(1), m.group(2)
        hits = [(t, v) for t, v in universe if v == tok and (cur_town is None or t == cur_town)]
        if len(hits) != 1:
            raise ValueError(f"{county} 範圍字詞 {tok!r} 對到 {hits}")
        out.add(hits[0])
    return out


def indigenous_towns(county, rng, towns):
    """原住民選區的範圍 → 鄉鎮集合。「○○縣之山地原住民」代表全縣市。"""
    body = rng[: -len("之平地原住民")]
    if body == county:
        return set(towns)
    got = set(re.split(r"[、及]", body))
    unknown = got - set(towns)
    if unknown:
        raise ValueError(f"{county} 原住民選區範圍有未知鄉鎮：{sorted(unknown)}")
    return got


def district_rows(tables, mayors):
    rows = []
    for county, ds in tables.items():
        iso = ISO[county]
        if iso == "tpe":
            continue  # tpe_districts 負責
        for d in ds:
            kind = kind_of(d["range"])
            label = {"plains": "（平地原住民）", "mountain": "（山地原住民）"}.get(kind, "")
            rows.append({"district_id": council_id(iso, d["n"]), "office": f"{iso}_councilor",
                         "name": f"{county}第{d['n']}選舉區{label}", "seats": d["seats"], "source_url": ANN_URL})
        rows.append({"district_id": f"{iso}-mayor", "office": f"{iso}_mayor", "name": county,
                     "seats": mayors[county], "source_url": ANN_URL})
    return rows


def village_rows(tables, villages, fetched_at):
    """村里 → 議員選區：非臺北的區域選區，以及所有縣市（含臺北）的平地／山地原住民選區。

    每個村里在每種 office 恰好一列；原住民選區的鄉鎮集合必須剛好涵蓋該縣市每個鄉鎮一次（V11 §2.3）。
    """
    by_county = {}
    for v in villages:
        by_county.setdefault(v["COUNTYNAME"], []).append(v)
    if set(tables) - set(by_county):
        raise ValueError(f"村里表缺縣市：{sorted(set(tables) - set(by_county))}")

    rows = []
    for county, ds in tables.items():
        iso = ISO[county]
        vs = by_county[county]
        universe = [(v["TOWNNAME"], v["VILLNAME"]) for v in vs]
        towns = sorted({t for t, _ in universe})
        assigned = {}  # office → {(town, vill) 或 town: n}

        for d in ds:
            kind = kind_of(d["range"])
            if kind is None:
                office, keys = f"{iso}_councilor", expand_regional(county, d["range"], universe)
            else:
                office, keys = f"{iso}_councilor_{kind}", indigenous_towns(county, d["range"], towns)
            seen = assigned.setdefault(office, {})
            dup = keys & set(seen)
            if dup:
                raise ValueError(f"{county} {office} 重複歸區：{sorted(dup)[:5]}")
            seen.update({k: d["n"] for k in keys})

        for office, seen in assigned.items():
            regional = office == f"{iso}_councilor"
            missing = [k for k in (universe if regional else towns) if k not in seen]
            if missing:
                raise ValueError(f"{county} {office} 未歸區：{missing[:10]}")
            if regional and iso == "tpe":
                continue  # 臺北區域選區的里對照由 tpe_districts 負責
            for v in vs:
                n = seen[(v["TOWNNAME"], v["VILLNAME"])] if regional else seen[v["TOWNNAME"]]
                rows.append({"villcode": v["VILLCODE"], "office": office, "town": v["TOWNNAME"],
                             "village": v["VILLNAME"], "district_id": council_id(iso, n),
                             "source_url": ANN_URL, "fetched_at": fetched_at})
    return rows


def county_rows(villages, fetched_at):
    codes = {}
    for v in villages:
        codes.setdefault(v["COUNTYNAME"], set()).add(v["COUNTYCODE"])
    bad = {c: s for c, s in codes.items() if len(s) != 1}
    if bad or set(codes) != set(ISO):
        raise ValueError(f"村里表縣市代碼異常：{bad or sorted(set(codes) ^ set(ISO))}")
    return [{"iso": iso, "moi_code": next(iter(codes[name])), "name": name,
             "source_url": moi.VILLAGE_ZIP_URL, "fetched_at": fetched_at} for iso, name in COUNTIES]


def run(conn):
    fetched_at = now_utc()
    pdf = get(ANN_URL)
    text = pdf_text(pdf)
    tables = parse_council_tables(cec_pdf.bbox_html(pdf))
    check_totals(tables, parse_totals(text))
    mayors = parse_mayors(text)
    villages = moi.villages()

    for row in county_rows(villages, fetched_at):
        upsert(conn, "county", row, ("iso",))
    for d in district_rows(tables, mayors):
        upsert(conn, "district", {**d, "fetched_at": fetched_at}, ("district_id",))
    for row in village_rows(tables, villages, fetched_at):
        upsert(conn, "village_district", row, ("villcode", "office"))
