"""2022 選舉公報 C 家族（單欄橫列表格）、D 家族（雙欄橫列表格）與 B 家族（新北、臺南兩欄格子）的框線切格器與報告。

規格見 docs/validation/V13-l3a-basic.md §1.3–§1.5。只切格與報告，不寫資料庫。B 家族見 cut_pages_b()，關卡與輸出列相同。

做法：每頁算圖（沿用臺北 pdf_layers 的灰階頁，100 dpi）找長的深色水平線，相鄰兩條水平線之間是一個「橫帶」；
每個橫帶各自找貫穿整帶高度的垂直線，切成格子。表頭列（號次、姓名、學歷…）決定每一欄是什麼欄位，
不寫死欄序；D 家族一頁左右兩組表頭，標籤重複出現就開新的一組。資料列的格子依中心 x 對到表頭欄；
字詞歸給重疊面積最大的格（直排字的 bbox 會偏移半個字）。

防呆（沿用臺北：最怕把政見掛錯人）：
- 身分：號次、姓名、出生年、黨籍必須和中選會開票 JSON 該選區的候選人完全一致，否則整列不收。
  同一檔對不上的列 ≥ UNRELIABLE_MIN 且超過 UNRELIABLE_SHARE 就整檔不可靠（一列都不收）。
  選區：選舉區別欄（合併格）＞表頭上方最近一行標題＞檔案只涵蓋一區（etl.bulletin2022.file_map）。
- 學歷、經歷、政見：去空白後必須是 pdftotext -raw 的連續子字串；格內有圖片、亂碼比例超過 GARBLE_MAX、
  或有看不見／重疊的文字（臺北的 parse_pages 判斷）就丟該欄。
- 號次、姓名格有看不見的文字，整列不收。
"""
import json
import random
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from etl.bulletin2022 import file_map, parse_districts
from etl.cec2022 import SOURCES, parse_candidates
from etl.sources.national_districts import COUNTIES
from etl.sources.tpe_bulletin_2022 import (DPI, NO_PARTY, line_text, norm_name, overlaps, parse_pages,
                                           pdf_layers, squeeze, to_lines)

CACHE = Path("data/cache")
PDF_ROOT = CACHE / "bulletin2022"
CHECK_DIR = CACHE / "bulletin_grid_check"
INDEX = Path("tests/fixtures/bulletin2022_index.json")
CEC_FILES = ["c1", "c2", "c2r", "cec_T1_T1", "cec_T1_T2", "cec_T1_T3", "cec_T2_T1", "cec_T2_T2", "cec_T2_T3"]

C_FAMILY = ["桃園市", "臺中市", "高雄市", "苗栗縣", "南投縣", "嘉義縣", "花蓮縣", "金門縣", "連江縣", "基隆市", "嘉義市"]
D_FAMILY = ["彰化縣", "新竹縣", "新竹市"]
B_FAMILY = ["新北市", "臺南市"]
NO_TEXT_LAYER = {"雲林縣": "錯碼（㆒㈴㈻）且 pdftohtml 輸出非 UTF-8，V13 判定等同沒有文字層"}
# 單檔視同沒有文字層（整檔外框字或圖片，切不出任何列）：只放原檔連結（使用者 2026-10-02 決定）
_P = "01選舉公報/05直轄市議員/111年/"
NO_TEXT_FILES = {
    _P + "03桃園市/桃園市第7選舉區.pdf": "整檔外框字或圖片",
    _P + "03桃園市/桃園市第8選舉區.pdf": "整檔外框字或圖片",
    _P + "04臺中市/臺中市第15選區.pdf": "整檔外框字或圖片",
    _P + "04臺中市/臺中市第16選區.pdf": "整檔外框字或圖片",
    _P + "04臺中市/臺中市第17選區.pdf": "整檔外框字或圖片",
}

DARK = bytes.maketrans(bytes(range(256)), bytes(int(i < 128) for i in range(256)))
H_FRAC = 0.3     # 水平線：連續深色像素 ≥ 頁寬 30%（D 家族一組表格約佔頁寬 45%）
V_FRAC = 0.9     # 垂直線：在該橫帶內深色像素 ≥ 帶高 90%
GARBLE_MAX = 0.02  # 非 CJK／ASCII／常用標點的字元比例上限；正常欄位為 0，新竹縣、新竹市的錯碼段落遠高於此
# 一檔中有字的資料列，身分對不上的列數 ≥ UNRELIABLE_MIN 且比例 > UNRELIABLE_SHARE → 整檔不可靠（一列都不收）。
# 單一列對不上多半是異體字（黄／黃），該列已被擋下；多列對不上才像是欄位錯位、選區判錯這種會連累同檔其他列的錯。
UNRELIABLE_SHARE = 0.2
UNRELIABLE_MIN = 2

# (欄位, 標籤)：表頭格的字（不論順序）包含標籤的每個字就算該欄，依序比對、先中先贏。
# 花蓮縣長表頭印成「年月日生」「別」「推薦之黨」，所以有短標籤；「選舉區別」排在「別」之前。
LABELS = [("district", "選舉區"), ("district", "選舉類別"), ("district", "選區"), ("birthplace", "出生地"), ("birth", "年月日"),
          ("party", "政黨"), ("party", "推薦"), ("platform", "政見"), ("education", "學歷"), ("experience", "經歷"),
          ("no", "號次"), ("name", "姓名"), ("sex", "性別"), ("sex", "別"), ("photo", "相片")]
TEXT_FIELDS = ("education", "experience", "platform")
NOT_HERE = "選區不在此檔"
NAME_ONLY = ("姓名不符", "號次或姓名有看不見的文字")  # identify() 回這兩種時，號次、出生年、黨籍都已一致
OTHER = "其他選舉（鄉鎮長、代表、村里長）"
FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")


# ---------- 框線 ----------

def _merge(idx):
    groups = []
    for i in idx:
        if groups and i - groups[-1][-1] <= 2:
            groups[-1].append(i)
        else:
            groups.append([i])
    return [(g[0], g[-1]) for g in groups]


def h_lines(mask, w, h, frac=H_FRAC):
    """mask：每像素 0/1 的 bytes。回傳 [(y0, y1)] 水平線（像素，含線寬）。"""
    return _merge([y for y in range(h) if max(map(len, mask[y * w:(y + 1) * w].split(b"\0"))) >= frac * w])


def v_lines(mask, w, y0, y1, frac=V_FRAC):
    """橫帶 [y0, y1) 內貫穿 frac 帶高的垂直線，回傳 [(x0, x1)]。"""
    need = frac * (y1 - y0)
    return _merge([x for x in range(w) if mask[y0 * w + x:y1 * w:w].count(1) >= need])


S = 72 / DPI     # 像素 → pt


class Page:
    """一頁的深色遮罩與水平線。座標：像素；對外的 band／cell 一律 pt。"""

    def __init__(self, gray):
        self.w, self.h, px = gray
        self.mask = px.translate(DARK)
        self.rules = h_lines(self.mask, self.w, self.h)

    def crosses(self, rule, x0, x1):
        """水平線在 [x0, x1]（pt）內是否連續（≥ 90% 深色）：用來確認這條線切過號次欄，而不是格內的線。"""
        a, b = int(x0 / S) + 2, int(x1 / S) - 2
        if b <= a:
            return False
        return any(self.mask[y * self.w + a:y * self.w + b].count(1) >= 0.9 * (b - a) for y in range(rule[0], rule[1] + 1))

    def sub_rows(self, x0, x1, y0, y1):
        """格 [x0, x1]×[y0, y1]（pt）被貫穿整格寬（≥ 90%）的水平線切成的子格 [(sy0, sy1)]（pt）。"""
        a, b = int(x0 / S) + 2, int(x1 / S) - 2
        ys = [y for y in range(int(y0 / S), int(y1 / S))
              if b > a and self.mask[y * self.w + a:y * self.w + b].count(1) >= 0.9 * (b - a)]
        edges = [y0] + [v for r in _merge(ys) for v in (r[0] * S, (r[1] + 1) * S)] + [y1]
        return [(p, q) for p, q in zip(edges[::2], edges[1::2]) if q - p >= 5]

    def bands(self, rules, x0=0, x1=None):
        """相鄰兩條水平線之間的橫帶，各自切出 [x0, x1]（pt）內的格子：[(y0, y1, [(cx0, cx1), ...])]。"""
        x1 = self.w * S if x1 is None else x1
        out = []
        for (_, a), (b, _) in zip(rules, rules[1:]):
            y0, y1 = a + 3, b - 2
            if y1 - y0 < 5:
                continue
            vs = [v for v in v_lines(self.mask, self.w, y0, y1) if v[1] * S >= x0 - 6 and v[0] * S <= x1 + 6]
            out.append(((a + 1) * S, b * S, [((p[1] + 1) * S, q[0] * S) for p, q in zip(vs, vs[1:])]))
        return out


# ---------- 文字 ----------

def cell_text(words, x0, y0, x1, y1):
    """格內字詞排序：直排格（高 > 1.5 寬，且字詞多為單字或直條）由右而左、由上而下；否則橫排逐行。"""
    if not words:
        return ""
    vertical = (y1 - y0) > 1.5 * (x1 - x0) and sum((w[3] - w[1]) >= (w[2] - w[0]) for w in words) * 2 >= len(words)
    if not vertical:
        return "\n".join(line_text(l) for l in to_lines(words))
    cols = []  # [[左緣, 右緣, 字詞]]：x 範圍有重疊就算同一直行（直排中的橫寫數字會比單字偏左一點）
    for wd in sorted(words, key=lambda w: -w[2]):
        if cols and wd[2] > cols[-1][0]:
            cols[-1][0] = min(cols[-1][0], wd[0])
            cols[-1][2].append(wd)
        else:
            cols.append([wd[0], wd[2], [wd]])
    # 直行內同一高度的字詞（窄格裡折行的橫排，如「47年／12月／5日」）由左而右
    return "\n".join("".join(line_text(l) for l in to_lines(ws)) for _, _, ws in cols)


def label_of(text):
    t = squeeze(text)
    if not t or len(t) > 8:
        return None
    for field, lab in LABELS:
        if all(ch in t for ch in lab):
            return field
    return None


def header_groups(cells):
    """表頭列 [(x0, x1, text)] → [[(x0, x1, field), ...], ...]；同一標籤再出現就開新的一組（D 家族）。
    不足 5 個標籤或缺號次／姓名的組不算表頭。"""
    groups, cur = [], []
    for x0, x1, text in cells:
        f = label_of(text)
        if f is None:
            continue
        if any(c[2] == f for c in cur):
            groups.append(cur)
            cur = []
        cur.append((x0, x1, f))
    groups.append(cur)
    return [g for g in groups if len(g) >= 5 and {"no", "name"} <= {c[2] for c in g}]


def roc_birth_year(text):
    """「44年1月4日」→ 1955；直排拆行也可；找不到回 None。
    只取年：公報原文有月日錯字（臺南「54年l月6日」「79年6年29日」），身分關卡只比出生年。"""
    m = re.search(r"(\d{2,3})年", squeeze(text).translate(FULLWIDTH))
    return int(m.group(1)) + 1911 if m else None


def garble_ratio(text):
    """非 CJK／ASCII／常用標點的字元比例（不計空白與控制字）。私用區（Wingdings 符號）算亂碼：網頁上會變成方框。
    CJK 擴充 A（㕨䧮）也算：桃園有字型對應錯誤落在這一區，正常公報文字幾乎不用。"""
    chars = [c for c in text if not c.isspace() and ord(c) >= 0x20]  # Word 的 tab 控制字 \x07、\x08 無害（V13 §1.3）
    if not chars:
        return 0.0
    return sum(not _ok_char(c) for c in chars) / len(chars)


def _ok_char(c):
    o = ord(c)
    return (0x20 <= o < 0x7F or 0x4E00 <= o <= 0x9FFF or 0x3000 <= o <= 0x303F
            or 0xFF00 <= o <= 0xFFEF or 0x2000 <= o <= 0x206F or 0x2460 <= o <= 0x24FF or 0x25A0 <= o <= 0x25FF
            or 0x2160 <= o <= 0x217F or 0x2500 <= o <= 0x257F or 0xFE30 <= o <= 0xFE6F or 0x02B0 <= o <= 0x02FF or 0x2190 <= o <= 0x21FF or 0x2600 <= o <= 0x26FF or 0x2700 <= o <= 0x27BF
            or c in "·‧．、。，「」『』《》〈〉％＋－×÷～…—–‘’“”°※")


def section_of(text):
    """選舉區別欄或標題 → ("councilor", n)、("councilor", None)（議員、沒寫區號）、("mayor", None)、
    ("other", None)（同檔印的鄉鎮市長、代表、村里長）；看不出來或不只一區回 None。"""
    t = squeeze(text)
    try:
        ns = parse_districts(t)
    except KeyError:
        ns = []
    if len(ns) == 1:
        return ("councilor", ns[0])
    if ns:
        return None
    if re.search("[鄉鎮]長|代表|[村里]長", t):
        return ("other", None)
    if "議員" in t:
        return ("councilor", None)
    if re.search("[縣市]長", t):
        return ("mayor", None)
    return None


def _svg(pdf, pno):
    return subprocess.run(["pdftocairo", "-svg", "-f", str(pno), "-l", str(pno), str(pdf), "-"],
                          check=True, capture_output=True).stdout.decode("utf-8", "replace")


def blank_glyphs(svg):
    """pdftocairo -svg 的一頁 → 字形沒有輪廓（畫不出任何筆畫）的字的原點 [(x, 基線 y)]（pt）。
    同一原點（1pt 內）另有畫得出來的字形就不算：嘉義市、新竹縣在字前面有不佔寬度的空白（空字形），原點和字相同。"""
    empty = set(re.findall(r'<g id="(glyph-[\d-]+)">\s*</g>', svg))
    uses = [(g, float(x), float(y)) for g, x, y in re.findall(r'<use xlink:href="#(glyph-[\d-]+)" x="([-\d.]+)" y="([-\d.]+)"', svg)]
    inked = {(round(x), round(y)) for g, x, y in uses if g not in empty}
    return [(x, y) for g, x, y in uses if g in empty
            and not any((round(x) + i, round(y) + j) in inked for i in (-1, 0, 1) for j in (-1, 0, 1))]


def drop_blank(words, origins):
    """去掉字形是空的單字字詞：高雄議員公報範本殘留一個空字形的「媖」，疊在第 5、10、13 列的姓名格裡，
    算圖時旁邊的姓名字有墨跡，has_ink 看不出來，會讀成「湯詠瑜媖」。
    原點要在字框下段（基線）：上一行的空白字元（也是空字形）原點會落在下一行字框的上緣（南投姓名「洪」）。
    只看文字（isalnum）：臺南有「•」的文字是空字形、看得見的圓點是另一個沒有對應文字的字形，丟掉「•」反而對不上 -raw。
    ponytail: 只看單字字詞；多字字詞夾空字形就留著，由 -raw 與身分關卡擋下。"""
    return [w for w in words
            if not (len(w[4]) == 1 and w[4].isalnum() and any(abs(x - w[0]) < 1 and w[1] + 0.6 * (w[3] - w[1]) <= y <= w[3] + 1 for x, y in origins))]


# ---------- 切格 ----------

def _center_in(w, x0, y0, x1, y1):
    return x0 <= (w[0] + w[2]) / 2 < x1 and y0 <= (w[1] + w[3]) / 2 < y1


def _words_in(words, x0, y0, x1, y1):
    return [w for w in words if _center_in(w, x0, y0, x1, y1)]


def _join(ws):
    return "".join(w[4] for w in sorted(ws, key=lambda w: (w[1], w[0])))


def _overlap(w, b):
    return max(0, min(w[2], b[2]) - max(w[0], b[0])) * max(0, min(w[3], b[3]) - max(w[1], b[1]))


def _field_at(group, cx):
    for x0, x1, f in group:
        if x0 - 2 <= cx <= x1 + 2:
            return f
    return None


def cut_pages(pages, grays):
    """回傳 [{page, box, fields: {field: [(cell_box, words)]}, district_text, title}]，每個資料列一筆。
    表頭沿用到後面沒有表頭的頁；標題（選舉區、首長）沿用到下一個標題。"""
    rows, groups, title = [], None, None
    for pno, (pg, gray) in enumerate(zip(pages, grays), 1):
        page = Page(gray)
        words = [w for w in pg["words"] if _plain(w[4])]  # 只有 Word tab 控制字的字詞沒有墨跡，會被當成看不見的文字
        full = page.bands(page.rules)
        headers = []
        for y0, y1, cells in full:
            hg = header_groups([(x0, x1, cell_text(_words_in(words, x0, y0, x1, y1), x0, y0, x1, y1)) for x0, x1 in cells])
            if hg:
                headers.append((y0, y1, hg))
        table = [(y0, y1) for y0, y1, cells in full if len(cells) >= 5]
        segs, prev = [], 0
        for i, (hy0, hy1, hg) in enumerate(headers):
            above = [w for w in words if prev <= (w[1] + w[3]) / 2 < hy0
                     and not any(a <= (w[1] + w[3]) / 2 < b for a, b in table)]
            # 由近而遠逐行找：緊貼表頭的「第8屆縣長候選人：」比頁首「縣長、縣議員選舉」準
            lines = [line_text(l) for l in to_lines(above)]
            title = next((sec for sec in map(section_of, reversed(lines)) if sec), title)
            end = headers[i + 1][0] if i + 1 < len(headers) else page.h * S
            segs.append((hy1 - 3, end, hg, title))
            prev = hy1
        if not headers and groups:
            segs.append((0, page.h * S, groups, title))
        for sy0, sy1, hg, ttl in segs:
            groups = hg
            for g in hg:
                rows += _cut_group(page, words, pno, g, sy0, sy1, ttl)
    return rows


def _own(words, boxes):
    """字詞歸給重疊面積最大的格（直排字的 bbox 常往上偏半個字，用中心會掉到上一格），重疊不到 40% 不收。"""
    owned = {}
    for w in words:
        best = max(boxes, key=lambda b: _overlap(w, b), default=None)
        if best and _overlap(w, best) >= 0.4 * (w[2] - w[0]) * (w[3] - w[1]):
            owned.setdefault(best, []).append(w)
    return owned


def _fits(group, cells):
    """資料列的格線要涵蓋表頭每一欄的左緣（政見格內多出的分隔線不影響）；投開票所一覽表之類的別的表格不會符合。
    容差 6pt：桃園第 2 區第 3 號那列的經歷／政見分隔線比表頭偏右 5pt。"""
    return all(any(abs(c[0] - x0) < 6 for c in cells) for x0, _, _ in group)


def _cut_group(page, words, pno, group, sy0, sy1, title):
    nx0, nx1 = next((a, b) for a, b, f in group if f == "no")
    gx0, gx1 = min(c[0] for c in group), max(c[1] for c in group)
    rules = [r for r in page.rules if sy0 <= r[0] * S <= sy1 and page.crosses(r, nx0, nx1)]
    bands = [b for b in page.bands(rules, gx0, gx1) if _fits(group, b[2])]
    dcol = next(((a, b) for a, b, f in group if f == "district"), None)
    spans = []
    if dcol:  # 選舉區別欄常是合併格：用切過該欄的水平線找出合併範圍，範圍內的字都算這一格
        drules = [r for r in rules if page.crosses(r, *dcol)]
        spans = [(a, b, _words_in(words, dcol[0], a, dcol[1], b))
                 for a, b in (((p[1] + 1) * S, q[0] * S) for p, q in zip(drules, drules[1:]))]
    side = []
    if not dcol and bands:  # 花蓮：選區名直排印在表格左側框外，沒有表頭也沒有框線；依上下間隔分段
        for w in sorted((w for w in words if gx0 - 40 <= (w[0] + w[2]) / 2 < gx0
                         and bands[0][0] <= (w[1] + w[3]) / 2 < bands[-1][1]), key=lambda w: w[1]):
            if side and w[1] - side[-1][1] < 100:
                side[-1] = (side[-1][0], w[3], side[-1][2] + [w])
            else:
                side.append((w[1], w[3], [w]))
    owned = _own(words, [(x0, y0, x1, y1) for y0, y1, cells in bands for x0, x1 in cells])
    # 同一表頭下接著印下一區（高雄合併檔：「第13選舉區：…」印在兩列之間、沒有直線的橫帶）：列上方最近的區標題優先
    marks = []
    for y0, y1, cells in page.bands(rules, gx0, gx1):
        if len(cells) <= 1:
            lines = to_lines([w for w in words if gx0 <= (w[0] + w[2]) / 2 < gx1 and y0 <= (w[1] + w[3]) / 2 < y1])
            sec = next((s for s in map(section_of, map(line_text, lines)) if s), None)
            if sec:
                marks.append((y0, sec))
    out = []
    for y0, y1, cells in bands:
        title = next((sec for my, sec in reversed(marks) if my < y0), title)
        fields = {}
        for x0, x1 in cells:
            f = _field_at(group, (x0 + x1) / 2)
            if f:
                fields.setdefault(f, []).append(((x0, y0, x1, y1), owned.get((x0, y0, x1, y1), [])))
        if "no" not in fields or "name" not in fields:
            continue
        dtext = None
        if spans:  # 列中心所在的合併格
            mid = (y0 + y1) / 2
            dtext = next((_join(ws) for a, b, ws in spans if a <= mid < b), None)
        out.append({"page": pno, "box": (gx0, y0, gx1, y1), "fields": fields, "district_text": dtext, "title": title})
    if side:  # 選區名置中印在該區所有列的左側：號次從頭編起就是下一區，每段取中心落在段內的側標
        runs, last = [], None
        for r in out:
            no = squeeze(_text(r["fields"]["no"])).translate(FULLWIDTH)
            n = int(no) if no.isdigit() else last
            if not runs or (n is not None and last is not None and n <= last):
                runs.append([])
            runs[-1].append(r)
            last = n
        for run in runs:
            a, b = run[0]["box"][1], run[-1]["box"][3]
            text = "".join(_join(ws) for y0, y1, ws in side if a <= (y0 + y1) / 2 < b)
            for r in run:
                r["district_text"] = text or None
    return out


# ---------- B 家族（新北、臺南） ----------
# 左右兩欄、每格一人。一位候選人佔兩個橫帶：上帶是「號次｜照片｜姓名、出生年月日｜性別、出生地、推薦之政黨｜學歷」，
# 標籤與值各自一格、同一欄內用短橫線分上下；下帶是「經歷｜經歷內容｜政見｜政見內容」。
# 上帶每一欄再用貫穿整格寬的橫線切子格，標籤格的值就是右邊一欄中心落在標籤格高度內的子格（V13 §1.4）。

def pair_labels(columns):
    """columns：由左而右的欄，每欄 [(box, words)] 由上而下 → {欄位: [(box, words)]}。
    號次格的值是同格裡「號次」以外的字；其他標籤格的值是右邊一欄、中心落在標籤格高度內的子格。
    已當作值的格不再當標籤（生日「48年9月25日」含「年月日」三字）。"""
    fields, taken = {}, set()
    for i, col in enumerate(columns):
        for box, ws in col:
            if box in taken:
                continue
            if any(w[4] == "號次" for w in ws):
                fields["no"] = [(box, [w for w in ws if w[4] != "號次"])]
                continue
            f = label_of(cell_text(ws, *box))
            if f in (None, "no", "photo") or i + 1 == len(columns):
                continue
            fields[f] = [(b, v) for b, v in columns[i + 1] if box[1] <= (b[1] + b[3]) / 2 < box[3]]
            taken.update(b for b, _ in fields[f])
    return fields


def cut_pages_b(pages, grays):
    """B 家族的 cut_pages：回傳格式相同（district_text 一律 None，選區看候選人上方最近的標題）。
    每個「號次」字詞是一位候選人：只用切過號次欄的水平線（＝格子上緣、上下帶分界、格子下緣），
    旁邊另一欄的表格（臺南合併區檔右下的電視政見日程表）或政見框裡的圖表橫線不會把格子切斷。"""
    rows, title = [], None
    for pno, (pg, gray) in enumerate(zip(pages, grays), 1):
        page = Page(gray)
        words = [w for w in pg["words"] if _plain(w[4])]
        prev = 0
        for a in sorted((w for w in words if w[4] == "號次"), key=lambda w: (round(w[1]), w[0])):
            rules = [r for r in page.rules if page.crosses(r, a[0], a[2])]
            above = [r for r in rules if r[1] * S <= a[1] + 1]
            below = [r for r in rules if r[0] * S >= a[3]]
            if not above or len(below) < 2:
                continue
            y0, y1, cells = (page.bands([above[-1], below[0]]) or [(0, 0, [])])[0]
            ly0, ly1, lcells = page.bands(below[:2])[0]
            k = next((j for j, (x0, x1) in enumerate(cells) if x0 <= (a[0] + a[2]) / 2 < x1), None)
            if k is None:
                continue
            # 一人的欄到學歷值為止（學歷標籤的右邊一欄），也不越過下一個號次格
            end = len(cells)
            for j in range(k + 1, len(cells)):
                text = cell_text(_words_in(words, cells[j][0], y0, cells[j][1], y1), cells[j][0], y0, cells[j][1], y1)
                if "號次" in text:
                    end = j
                    break
                if label_of(text) == "education":
                    end = min(j + 2, len(cells))
                    break
            gx0, gx1 = cells[k][0], cells[end - 1][1]
            # 合併區檔：由近而遠找上一列候選人之後的標題（「第12選舉區（平地原住民）候選人」「市長候選人」）
            lines = [line_text(l) for l in to_lines([w for w in words if prev <= (w[1] + w[3]) / 2 < y0])]
            title = next((sec for sec in map(section_of, reversed(lines)) if sec), title)
            prev = max(prev, ly1)
            upper = [[(x0, sy0, x1, sy1) for sy0, sy1 in ([(y0, y1)] if j == k else page.sub_rows(x0, x1, y0, y1))]
                     for j, (x0, x1) in enumerate(cells[k:end], k)]
            # 新北的照片圖框下緣壓過上下帶分界線約 2pt，下帶格子上緣內縮 2pt，免得經歷欄被當成有圖片
            lower = [[(x0, ly0 + 2, x1, ly1)] for x0, x1 in lcells if gx0 - 2 <= x0 and x1 <= gx1 + 2]
            owned = _own(words, [b for col in upper + lower for b in col])
            fields = {}
            for cols in (upper, lower):
                fields.update(pair_labels([[(b, owned.get(b, [])) for b in col] for col in cols]))
            if "no" in fields and "name" in fields:
                rows.append({"page": pno, "box": (gx0, y0, gx1, ly1), "fields": fields, "district_text": None,
                             "title": title})
    return rows


# ---------- 關卡 ----------

def _text(parts):
    return "\n".join(cell_text(ws, *box) for box, ws in sorted(parts, key=lambda p: p[0][0]) if ws)


def readings(parts):
    """身分格的兩種讀法（依格子形狀的讀法、逐行橫讀）：窄格裡也有橫排折行（基隆生日），兩種都試，比對仍要完全一致。"""
    ws = [w for _, p in parts for w in p]
    return {squeeze(_text(parts)), squeeze("".join(line_text(l) for l in to_lines(ws))) if ws else ""}


def _plain(text):
    """去空白與控制字（Word 的 \x07、\x08 在 -bbox 與 -raw 裡出現的位置不一定相同）。"""
    return re.sub(r"[\s\x00-\x1f]+", "", text)


def gate_field(parts, images, suspect, flat_raw):
    """學歷／經歷／政見一欄 → (文字, None) 或 (None, 丟棄原因)。"""
    words = [w for _, ws in parts for w in ws]
    for (x0, y0, x1, y1), ws in parts:  # 先看圖片：整格是圖片時也沒有字，不能當成「空白」（候選人沒填）
        if any(overlaps(im, x0 + 2, y0 + 2, x1 - 2, y1 - 2) for im in images):
            return None, "圖片"
    if not words:
        return None, "空白"
    for (x0, y0, x1, y1), ws in parts:
        if any(_overlap(w, (x0, y0, x1, y1)) < 0.8 * (w[2] - w[0]) * (w[3] - w[1]) for w in ws):
            return None, "跨格"
    if suspect & set(words):
        return None, "看不見的文字"
    text = _text(parts)
    if garble_ratio(text) > GARBLE_MAX:
        return None, "亂碼"
    if _plain(text) not in flat_raw:
        return None, "-raw 對不上"
    return re.sub(r"[\x00-\x08\x0b-\x1f]+", "", text), None


def load_cec(cache=CACHE / "v13"):
    """{(iso, "mayor"|"councilor", district_n): {cand_no: 候選人}}，讀 V13 存下的開票 JSON。"""
    out = {}
    for (kind, _), name in zip(SOURCES, CEC_FILES):
        for c in parse_candidates(json.loads((cache / f"{name}.json").read_text()), kind):
            key = (c["iso"], "mayor" if kind == "mayor" else "councilor", c["district_n"])
            out.setdefault(key, {})[c["cand_no"]] = c
    return out


def same_party(name):
    """政黨比對時「台」「臺」視為同字（只用於政黨；姓名異體字不放寬）。"""
    return name.replace("台", "臺")


def identify(row, iso, districts, cec):
    """回傳 (section, 號次, 開票候選人, None) 或 (..., 原因)。"""
    f = row["fields"]
    no_t = _plain(_text(f["no"])).translate(FULLWIDTH)
    sec = (section_of(row["district_text"]) if row["district_text"] else None) or row["title"]
    councils = [d for d in districts if d[0] == "councilor"]
    if sec == ("councilor", None) and len(councils) == 1:
        sec = tuple(councils[0])
    elif sec is None and len(districts) == 1:
        sec = tuple(districts[0])
    if sec is None or sec == ("councilor", None):
        return None, None, None, "選區不明"
    if sec[0] == "other":
        return sec, None, None, OTHER
    if list(sec) not in districts:
        return sec, None, None, NOT_HERE
    if not re.fullmatch(r"\d+", no_t):
        return sec, None, None, "號次不是數字"
    c = cec.get((iso, *sec), {}).get(int(no_t))
    if c is None:
        return sec, int(no_t), None, "號次不在開票名單"
    # 出生年、黨籍先比：之後的兩種原因（NAME_ONLY）就代表號次、出生年、黨籍都已和該號次的候選人一致
    if c["birth_year"] not in {roc_birth_year(t) for t in readings(f.get("birth", []))}:
        return sec, int(no_t), c, "出生年不符"
    if same_party(c["party"]) not in {same_party(NO_PARTY.get(t, t)) for t in readings(f.get("party", []))}:
        return sec, int(no_t), c, "黨籍不符"
    if any(w in row["suspect"] for _, ws in f["no"] + f["name"] for w in ws):
        return sec, int(no_t), c, "號次或姓名有看不見的文字"
    if norm_name(c["name"]) not in {norm_name(t) for t in readings(f["name"])}:
        return sec, int(no_t), c, "姓名不符"
    return sec, int(no_t), c, None


def process(pdf, iso, districts, cec, cutter=cut_pages):
    """一份公報 → {rows: [通過身分關卡的列], rejects: Counter, drops: {欄: Counter}, cut, no_text, unreliable}。
    cutter：cut_pages（C、D 家族）或 cut_pages_b（B 家族）。"""
    bbox, raw, xml, grays = pdf_layers(pdf.read_bytes())
    pages = [{**pg, "words": drop_blank(pg["words"], blank_glyphs(_svg(pdf, i)))}
             for i, pg in enumerate(parse_pages(bbox, xml, grays), 1)]
    flat = _plain(raw)
    cut = cutter(pages, grays)
    rep = {"cut": 0, "no_text": 0, "rows": [], "rejects": Counter(), "drops": {f: Counter() for f in TEXT_FIELDS},
           "suspect_in_cells": 0, "name_only": 0}
    seen = Counter()
    staged = []
    for r in cut:
        pg = pages[r["page"] - 1]
        r["suspect"] = pg["suspect"]
        if not squeeze(_text(r["fields"]["name"])):
            if not any(squeeze(_text(r["fields"].get(f, []))) for f in ("birth", "party", "education", "experience")):
                rep["no_text"] += 1 if squeeze(_text(r["fields"]["no"])) else 0  # 臺中：只有號次是文字，其餘是圖片
                continue
            rep["cut"] += 1
            rep["rejects"]["姓名格沒有字"] += 1
            rep["name_only"] += identify(r, iso, districts, cec)[3] in NAME_ONLY
            continue
        rep["cut"] += 1
        rep["suspect_in_cells"] += sum(w in pg["suspect"] for parts in r["fields"].values() for _, ws in parts for w in ws)
        sec, no, c, why = identify(r, iso, districts, cec)
        if why:
            rep["rejects"][why] += 1
            rep["name_only"] += why in NAME_ONLY
            continue
        seen[(sec, no)] += 1
        staged.append((r, sec, no, c, pg))
    for r, sec, no, c, pg in staged:
        if seen[(sec, no)] > 1:
            rep["rejects"]["同一號次切出多列"] += 1
            continue
        out = {"district_n": sec[1], "office": sec[0], "cand_no": no, "name": c["name"], "birth_year": c["birth_year"],
               "party": c["party"], "page": r["page"], "box": r["box"]}
        out["dropped"] = {}
        for f in TEXT_FIELDS:
            out[f], why = gate_field(r["fields"].get(f, []), pg["images"], pg["suspect"], flat)
            if why:
                rep["drops"][f][why] += 1
                out["dropped"][f] = why
        rep["rows"].append(out)
    # 印明是別的選舉（臺中議員檔第 1 頁的市長、連江議員檔後面的鄉長與村長），不是切錯，不計入；
    # 只有姓名格出問題（號次、出生年、黨籍都和該號次一致）的列也不計入：那是姓名字的問題（異體字、罕用字缺字、
    # 疊字），不是欄位錯位。這些列本身照樣不收。
    # 但過半的列都只有姓名格出問題，就像新竹市整檔直排字框偏移，仍算整檔不可靠。
    bad = sum(n for why, n in rep["rejects"].items() if why not in (NOT_HERE, OTHER)) - rep["name_only"]
    rep["unreliable"] = (rep["cut"] == 0 or (bad >= UNRELIABLE_MIN and bad > UNRELIABLE_SHARE * rep["cut"])
                         or 2 * rep["name_only"] > rep["cut"])
    if rep["unreliable"]:
        rep["rows"] = []
    return rep


# ---------- 報告 ----------

def crop(pdf, page, box, out):
    """把一列算圖裁切成 PNG（72 dpi，座標即 pt）。"""
    x0, y0, x1, y1 = (int(v) for v in box)
    subprocess.run(["pdftoppm", "-png", "-r", "72", "-f", str(page), "-l", str(page), "-singlefile",
                    "-x", str(x0), "-y", str(y0), "-W", str(x1 - x0), "-H", str(y1 - y0), str(pdf), str(out)],
                   check=True, capture_output=True)
    return out.with_suffix(".png")


def main(seed=2022):
    cec = load_cec()
    order = C_FAMILY + D_FAMILY + list(NO_TEXT_LAYER) + B_FAMILY
    files = [f for f in file_map(json.loads(INDEX.read_text()))
             if (PDF_ROOT / f["path"]).exists() and _county_name(f["iso"]) in order]
    CHECK_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    passed = {}
    for f in sorted(files, key=lambda f: order.index(_county_name(f["iso"]))):
        county, name = _county_name(f["iso"]), f["path"].rsplit("/", 1)[-1]
        if county in NO_TEXT_LAYER or f["path"] in NO_TEXT_FILES:
            print(f"{county} {name}：跳過（{NO_TEXT_LAYER.get(county) or NO_TEXT_FILES[f['path']]}）", flush=True)
            continue
        rep = process(PDF_ROOT / f["path"], f["iso"], f["districts"], cec,
                      cut_pages_b if county in B_FAMILY else cut_pages)
        drops = "；".join(f"{fld} " + "、".join(f"{k}{v}" for k, v in c.items()) for fld, c in rep["drops"].items() if c)
        print(f"{county} {name}：切出 {rep['cut']} 列、通過身分 {len(rep['rows'])}"
              f"{'（整檔不可靠）' if rep['unreliable'] else ''}；沒有文字 {rep['no_text']}；"
              f"身分不收 {dict(rep['rejects']) or 0}；欄位丟棄 {drops or 0}；格內看不見的字詞 {rep['suspect_in_cells']}", flush=True)
        passed.setdefault(county, []).extend((f["path"], r) for r in rep["rows"])
    print("\n人工抽查（C、D 每縣市隨機 1 位；B 議員檔 2 位、市長檔 1 位；seed=%d）：" % seed)
    for county, rows in passed.items():
        if county in B_FAMILY:  # 新北市長檔與 12 號議員檔是同一份，市長只從市長檔抽、議員只從議員檔抽
            council = [(p, r) for p, r in rows if "議員/" in p and r["office"] == "councilor"]
            mayor = [(p, r) for p, r in rows if "長/" in p.split("111年")[0] and r["office"] == "mayor"]
            picks = rng.sample(council, min(2, len(council))) + rng.sample(mayor, min(1, len(mayor)))
        else:
            picks = [rng.choice(rows)] if rows else []
        if not picks:
            print(f"{county}：沒有通過的列")
        for path, r in picks:
            png = crop(PDF_ROOT / path, r["page"], r["box"], CHECK_DIR / f"{county}_{r['district_n'] or 'mayor'}_{r['cand_no']}")
            plat = (r["platform"] or "（未收）").replace("\n", "")[:30]
            edu = (r["education"] or "（未收）").replace("\n", "")[:20] if county in B_FAMILY else None
            print(f"{county} {png.name}：{r['name']}｜" + (f"學歷開頭 {edu}｜" if edu else "") + f"政見開頭 {plat}")


def _county_name(iso):
    return next(n for i, n in COUNTIES if i == iso)


if __name__ == "__main__":
    sys.exit(main())
