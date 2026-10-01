"""2022 選舉公報（臺北市議員 8 區＋臺北市長）的政見與學經歷，掛到現任議員與市長（M6）。

版面：每頁左右兩欄、每欄數個固定大小的候選人格。格內上半是「號次·姓名／學歷／經歷」三欄，
下半左側是個人資料（生日、性別、出生地、推薦之政黨），右側是政見框。
pdftotext -layout 會把個人資料與政見逐行交錯，所以改用 -bbox-layout 的字詞座標切格。

防呆（最怕把政見掛錯人）：
- 每個看得見的字詞都必須落在某一格的某一區，或是已知的頁面雜項（標題、頁碼），否則 raise。
- 公報 PDF 裡有「看不見的文字」：被裁掉或被蓋住、但 pdftotext 照樣抽得出來（第 01 區第 1–2 頁
  每格底下都疊著下一格的號次、姓名、學經歷）。用 pdftoppm 算圖，字詞框內沒有墨跡就視為看不見；
  兩個不同字詞疊在同一位置也視為可疑。可疑字詞出現在號次、姓名、個人資料 → 整份公報不可靠
  （UnreliableBulletin），落在學經歷或政見 → 只丟掉那一欄。
- 切出的候選人（號次、姓名、出生年、黨籍）必須與中選會開票 JSON 完全一致，否則 raise。
- 政見框裡有圖片（候選人交圖檔）就不收政見，學經歷欄有圖片就不收學經歷。
- 切出的文字（去空白後）必須是 pdftotext -raw（內容流順序，另一條獨立的抽取路徑）的連續子字串，
  對不上就不收，擋跨欄、跨格拼接錯誤。
"""
import html
import json
import re
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

from etl.db import upsert, upsert_fact
from etl.fetch import get, get_json, now_utc
from etl.sources.tcc_councilors import load_identity

BULLETIN = "https://bulletin.cec.gov.tw/"
COUNCIL_PDF = "01選舉公報/05直轄市議員/111年/01臺北市/臺北市第{:02d}選舉區.pdf"  # 07、08 兩個檔內容相同，都含兩個原住民選區
MAYOR_PDF = "01選舉公報/03直轄市長/111年/臺北市市長.pdf"

TICKETS = "https://db.cec.gov.tw/static/elections/data/tickets/ELC"
CEC_COUNCIL = [  # 111 年直轄市議員：T1 區域、T2 平地原住民、T3 山地原住民；A 層級臺北市
    f"{TICKETS}/T1/T1/25e12c45f9f5641aab4193598d5aff6e/A/63_000_00_000_0000.json",
    f"{TICKETS}/T1/T2/44cf35b1708568b94bb3b4c38a3fc74c/A/63_000_00_000_0000.json",
    f"{TICKETS}/T1/T3/699b1ece9739edf4ec4662cea25a0bb3/A/63_000_00_000_0000.json",
]
CEC_MAYOR = f"{TICKETS}/C1/00/05cc7b904c7a30cc7c88d5b10898c98e/C/00_000_00_000_0000.json"  # 六都合一，取 prv_code 63

ELECTION = "2022-local"
VOTE_DATE = "2022-11-26"
MAYOR_SOURCE = "cec_2022_mayor"
MAYOR_TERM = 8  # 市長公報抬頭「臺北市第 8 屆市長／臺北市議會第 14 屆議員選舉」
MAYOR_TERM_START = "2022-12-25"  # 臺北市政府「一級機關首長名錄」：市長蔣萬安【到職日】111 年 12 月 25 日
NO_PARTY = {"無": "無黨籍及未經政黨推薦"}  # 公報寫「無」，開票 JSON 寫全稱

# 格內各區相對於「號次」字樣左緣的 x 位移（pt）。實測 9 份 PDF：個人資料 ≤ +100、學歷與政見 ≥ +122、經歷 ≥ +331、學歷 ≤ +310
X_SIDE = 118   # 左：號次、姓名、照片、個人資料；右：學歷、經歷、政見
X_EXP = 320    # 學歷｜經歷
PITCH = 493    # 同一欄上下兩格表頭的間距（實測 491–494）
LINE_TOL = 0.35  # 同一行判定：字詞垂直中心差 < 0.35 × 較矮字詞高度
DPI = 100
INK = 160      # 灰階 < 160 算墨跡
BULLET = re.compile(r"^(?:[•⊙●○◎■□◆◇★☆▲△▶►‧・．\-─]|\d{1,2}\s*[.、．)）]|[（(]\d{1,2}[)）]|[一二三四五六七八九十]+、)")
FURNITURE = re.compile(r"^(?:中選會|第\d+頁（共\d+頁）)$")  # 比對前先去空白
BIRTH = re.compile(r"^出生年月日：\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日$")


class UnreliableBulletin(ValueError):
    """公報的號次、姓名或個人資料區有看不見或互相重疊的文字，無法確定格子屬於誰。"""


def bulletin_url(path):
    return BULLETIN + urllib.parse.quote(path)


# ---------- PDF → 字詞、圖片、墨跡 ----------

def pdf_layers(data):
    """回傳 (bbox_html, raw_text, image_xml, [灰階頁面])。"""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "in.pdf"
        pdf.write_bytes(data)
        run = lambda *a: subprocess.run(a, capture_output=True, check=True).stdout.decode("utf-8")
        bbox = run("pdftotext", "-bbox-layout", str(pdf), "-")
        raw = run("pdftotext", "-raw", str(pdf), "-")
        subprocess.run(["pdftohtml", "-xml", "-q", "-zoom", "1", str(pdf), f"{tmp}/o"], capture_output=True, check=True)
        xml = Path(f"{tmp}/o.xml").read_text(encoding="utf-8")
        subprocess.run(["pdftoppm", "-r", str(DPI), "-gray", str(pdf), f"{tmp}/g"], capture_output=True, check=True)
        grays = [read_pgm(p.read_bytes()) for p in sorted(Path(tmp).glob("g-*.pgm"), key=lambda p: int(p.stem.split("-")[1]))]
    return bbox, raw, xml, grays


def read_pgm(data):
    magic, size, _maxval, px = data.split(b"\n", 3)
    if magic != b"P5":
        raise ValueError("pdftoppm 輸出不是 P5 PGM")
    w, h = map(int, size.split())
    return w, h, px


WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
IMAGE = re.compile(r'<image top="(-?\d+)" left="(-?\d+)" width="(\d+)" height="(\d+)"')


def parse_pages(bbox, xml, grays):
    """回傳每頁 {width, words: [(x0, y0, x1, y1, text)], images: [(x0, y0, x1, y1)], suspect: set(words)}。"""
    chunks = bbox.split("<page ")[1:]
    img_chunks = xml.split("<page ")[1:]
    if not (len(chunks) == len(img_chunks) == len(grays)):
        raise ValueError(f"頁數不一致：pdftotext {len(chunks)}、pdftohtml {len(img_chunks)}、pdftoppm {len(grays)}")
    pages = []
    for chunk, img_chunk, gray in zip(chunks, img_chunks, grays):
        width = float(re.match(r'width="([\d.]+)"', chunk).group(1))
        words = [(float(a), float(b), float(c), float(d), html.unescape(t)) for a, b, c, d, t in WORD.findall(chunk)]
        words = [w for w in words if w[4].strip()]
        words = dedupe(words)
        suspect = stacked(words) | {w for w in words if not has_ink(w, gray)}
        images = [(int(l), int(t), int(l) + int(w), int(t) + int(h)) for t, l, w, h in IMAGE.findall(img_chunk)]
        pages.append({"width": width, "words": words, "images": images, "suspect": suspect})
    return pages


def dedupe(words):
    # 同一段文字在同一位置（4pt 內）印兩次：假粗體、陰影字或重複圖層，讀起來只有一份，只留一份
    out = []
    for w in words:
        if not any(o[4] == w[4] and abs(o[0] - w[0]) < 4 and abs(o[1] - w[1]) < 4 for o in out):
            out.append(w)
    return out


def stacked(words):
    """兩個不同字詞疊在同一位置（同一基線附近、水平大半重疊）：其中一個必定被遮住，兩個都列為可疑。"""
    out = set()
    for i, a in enumerate(words):
        for b in words[i + 1:]:
            if abs(a[1] - b[1]) < 4 and abs((a[3] - a[1]) - (b[3] - b[1])) < 4:
                ix = min(a[2], b[2]) - max(a[0], b[0])
                if ix > 0.5 * min(a[2] - a[0], b[2] - b[0]):
                    out.update((a, b))
    return out


def has_ink(w, gray):
    # 只看字框中段 40% 的高度：字框含行距，上下緣會吃到鄰行的墨跡
    gw, gh, px = gray
    s = DPI / 72
    h = w[3] - w[1]
    y0, y1 = int((w[1] + 0.3 * h) * s), int((w[3] - 0.3 * h) * s) + 1
    x0, x1 = int(w[0] * s), int(w[2] * s) + 1
    for y in range(max(y0, 0), min(y1, gh)):
        row = px[y * gw + max(x0, 0): y * gw + min(x1, gw)]
        if row and min(row) < INK:
            return True
    return False


# ---------- 排版工具 ----------

def cy(w):
    return (w[1] + w[3]) / 2


def to_lines(words):
    """把字詞依垂直中心分行、行內依 x 排序，回傳 [[word, ...], ...]（由上而下）。"""
    lines = []
    for w in sorted(words, key=cy):
        h = w[3] - w[1]
        if lines:
            last = lines[-1]
            ref = sum(cy(x) for x in last) / len(last)
            if abs(cy(w) - ref) < LINE_TOL * min(h, min(x[3] - x[1] for x in last)):
                last.append(w)
                continue
        lines.append([w])
    return [sorted(line) for line in lines]


def line_text(line):
    # 字詞之間有間隙才補一個半形空白（pdftotext 會在字型切換處斷字，例如「容積」「450」「％上限」緊貼）
    out = line[0][4]
    for prev, w in zip(line, line[1:]):
        out += (" " if w[0] - prev[2] > 1.0 else "") + w[4]
    return re.sub(r"\s+", " ", out).strip()


def join_wrapped(a, b):
    # 同一項目折行：中文直接接上；兩側都是英數字時補空白
    return a + (" " if re.search(r"[A-Za-z0-9]$", a) and re.match(r"[A-Za-z0-9]", b) else "") + b


def items(lines):
    """學歷／經歷欄：有項目符號就依符號分項（折行接回前一項）；整欄沒有符號就整欄一項、保留換行。"""
    texts = [line_text(l) for l in lines]
    if not texts:
        return []
    if not any(BULLET.match(t) for t in texts):
        return ["\n".join(texts)]
    out = []
    for t in texts:
        if BULLET.match(t) or not out:
            out.append(t)
        else:
            out[-1] = join_wrapped(out[-1], t)
    return out


def overlaps(box, x0, y0, x1, y1):
    return box[0] < x1 and box[2] > x0 and box[1] < y1 and box[3] > y0


def squeeze(text):
    return re.sub(r"\s+", "", text)


# ---------- 切格 ----------

def find_headers(words):
    """「號次」「·」「姓名」三個字詞一組，回傳「號次」字詞。"""
    out = []
    for i, w in enumerate(words):
        if w[4] == "號次":
            if i + 2 >= len(words) or words[i + 1][4] != "·" or words[i + 2][4] != "姓名":
                raise UnreliableBulletin(f"「號次」後面不是「·姓名」：{words[i:i + 3]}")
            out.append(w)
    return out


def section_titles(words):
    """回傳 [(y, 標題, 字詞)]；議員公報是「第 N 選舉區…議員候選人」，市長公報是「市長候選人」。

    只取與標題字同高度、字級相近的字詞：01 區第 1 頁標題後面疊著一層被遮住的舊格子文字。
    """
    out = []
    for w in words:
        h = w[3] - w[1]
        if h < 40 or not ("選舉區" in w[4] or "候選人" in w[4]):
            continue
        line = sorted(x for x in words if abs(cy(x) - cy(w)) < 0.3 * h and x[3] - x[1] > 0.5 * h)
        t = line_text(line).replace(" ", "")
        m = re.match(r"^第(\d)選舉區.*議員候選人$", t)
        if m:
            title = f"council-{int(m.group(1))}"
        elif t == "市長候選人":
            title = "mayor"
        else:
            continue  # 例如市長公報前言；認錯或漏認標題會讓候選人歸錯區，由開票名單核對擋下
        if all(line[0][1] != o[0] for o in out):
            out.append((line[0][1], title, line))
    return out


def parse_bulletin(pages):
    """回傳所有候選人格：[{section, page, no, name, birth_date, gender, birthplace, party, education, experience, platform, notes}]。

    education／experience／platform 為 None 表示不收，原因寫在 notes。看得見的字詞無法歸位就 raise。
    """
    cands = []
    section = None
    for pno, page in enumerate(pages, 1):
        words, mid, suspect = page["words"], page["width"] / 2, page["suspect"]
        headers = find_headers(words)
        if not headers:
            raise ValueError(f"第 {pno} 頁找不到候選人格")
        titles = section_titles(words)
        used = set()
        for _, _, line in titles:
            used.update(line)
        # 頁碼、「中選會」：左右半頁分開分行，免得和另一欄同高度的字併成一行
        for half in (0, 1):
            for line in to_lines([w for w in words if (w[0] >= mid) == half and w not in suspect]):
                if FURNITURE.match(line_text(line).replace(" ", "")):
                    used.update(line)
        # 第一列格子以上是頁首（標題、市長公報的前言），不屬於任何格
        top = min(h[1] for h in headers) - 2
        used.update(w for w in words if w[3] <= top)
        for w in words:
            if w not in used and w[0] < mid < w[2]:
                raise ValueError(f"第 {pno} 頁字詞跨左右兩欄：{w}")
        page_section = section
        for side in (0, 1):
            col = sorted((h for h in headers if (h[0] >= mid) == side), key=lambda h: h[1])
            for i, hdr in enumerate(col):
                bottom = hdr[1] + PITCH
                if i + 1 < len(col):
                    if col[i + 1][1] < bottom - 5:
                        raise ValueError(f"第 {pno} 頁兩格表頭間距 {col[i + 1][1] - hdr[1]:.0f} 小於格高")
                    bottom = min(bottom, col[i + 1][1])
                bottom = min([bottom] + [t[0] for t in titles if t[0] > hdr[1]])
                above = [t for t in titles if t[0] < hdr[1]]
                section = max(above)[1] if above else page_section
                if section is None:
                    raise ValueError(f"第 {pno} 頁的候選人格前沒有選舉區標題")
                x0, x1 = (0, mid) if side == 0 else (mid, page["width"])
                cell_words = [w for w in words if x0 <= w[0] < x1 and hdr[1] - 2 <= cy(w) < bottom and w not in used]
                used.update(cell_words)
                images = [im for im in page["images"] if overlaps(im, x0, hdr[1], x1, bottom)]
                try:
                    cand = parse_cell(cell_words, images, hdr, suspect)
                except UnreliableBulletin as e:
                    raise UnreliableBulletin(f"第 {pno} 頁 {section}：{e}") from None
                cand["section"] = section
                cand["page"] = pno
                cands.append(cand)
        section = max(titles)[1] if titles else page_section
        left = [w for w in words if w not in used and w not in suspect]
        if left:
            raise ValueError(f"第 {pno} 頁有 {len(left)} 個字詞不屬於任何候選人格：{[w[4] for w in left[:10]]}")
    return cands


def parse_cell(words, images, hdr, suspect=frozenset()):
    hx, hy1 = hdr[0], hdr[3]
    label_row = [w for w in words if cy(w) < hy1]
    if [w[4] for w in sorted(label_row)] != ["號次", "·", "姓名", "學歷", "經歷"] or suspect & set(label_row):
        raise UnreliableBulletin(f"格子表頭不是「號次·姓名 學歷 經歷」：{[w[4] for w in sorted(label_row)]}")
    rest = [w for w in words if cy(w) >= hy1]
    pj = [w for w in rest if w[4] == "政見" and hx + X_SIDE <= w[0] < hx + X_EXP + 100 and w not in suspect]
    if len(pj) != 1:
        raise UnreliableBulletin(f"號次欄 x={hx:.0f} y={hdr[1]:.0f} 的格子「政見」標籤不是恰好一個：{pj}")
    pj = pj[0]
    upper = [w for w in rest if cy(w) < pj[1]]
    lower = [w for w in rest if cy(w) > pj[3]]
    if len(upper) + len(lower) + 1 != len(rest):
        raise ValueError(f"「政見」標籤同一列還有其他字詞：{[w[4] for w in rest if w not in upper + lower]}")
    for w in rest:
        if w[0] < hx + X_SIDE < w[2] or (w in upper and w[0] < hx + X_EXP < w[2]):
            raise ValueError(f"字詞跨欄：{w}")

    name_col = [w for w in upper if w[0] < hx + X_SIDE]
    edu_col = [w for w in upper if hx + X_SIDE <= w[0] < hx + X_EXP]
    exp_col = [w for w in upper if w[0] >= hx + X_EXP]
    side = [w for w in lower if w[0] < hx + X_SIDE]
    plat = [w for w in lower if w[0] >= hx + X_SIDE]
    bad = suspect & set(name_col + side)
    if bad:
        raise UnreliableBulletin(f"號次、姓名或個人資料區有看不見或重疊的文字：{sorted(w[4] for w in bad)}")

    nums = [w for w in name_col if re.fullmatch(r"\d+", w[4])]
    if len(nums) != 1:
        raise ValueError(f"號次欄數字不是恰好一個：{[w[4] for w in name_col]}")
    name_lines = [line_text(l) for l in to_lines([w for w in name_col if w is not nums[0]])]
    cand = {"no": int(nums[0][4]), "name": " ".join(name_lines), "notes": []}
    cand.update(parse_side(to_lines(side)))

    right = hx + X_SIDE
    if any(overlaps(im, right, hy1, right + 10000, pj[1]) for im in images):
        cand["education"] = cand["experience"] = None
        cand["notes"].append("學經歷欄有圖片")
    elif suspect & set(edu_col + exp_col):
        cand["education"] = cand["experience"] = None
        cand["notes"].append("學經歷欄有看不見或重疊的文字")
    else:
        cand["education"] = items(to_lines(edu_col))
        cand["experience"] = items(to_lines(exp_col))
    if any(overlaps(im, right, pj[3], right + 10000, float("inf")) for im in images):
        cand["platform"] = None
        cand["notes"].append("政見框有圖片（圖片政見不收）")
    elif suspect & set(plat):
        cand["platform"] = None
        cand["notes"].append("政見框有看不見或重疊的文字")
    elif not plat:
        cand["platform"] = None
        cand["notes"].append("政見框沒有文字")
    else:
        cand["platform"] = "\n".join(line_text(l) for l in to_lines(plat))
    return cand


def parse_side(lines):
    texts = [line_text(l) for l in lines]
    out = {"birth_date": None, "gender": None, "birthplace": None, "party": None}
    if "推薦之政黨" not in texts:
        raise ValueError(f"個人資料缺「推薦之政黨」：{texts}")
    k = texts.index("推薦之政黨")
    for t in texts[:k]:
        m = BIRTH.match(t)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            out["birth_date"] = f"{y + 1911:04d}-{mo:02d}-{d:02d}"
        elif t.startswith("性別："):
            out["gender"] = t[3:].strip()
        elif t.startswith("出生地："):
            out["birthplace"] = t[4:].strip()
        elif t != "個人資料":
            raise ValueError(f"個人資料有未知的行：{t!r}")
    out["party"] = "".join(texts[k + 1:]).replace(" ", "")
    if not out["birth_date"] or not out["party"]:
        raise ValueError(f"個人資料缺生日或政黨：{texts}")
    return out


def check_raw(cands, raw):
    """切出的政見、學經歷去空白後必須是 -raw 文字的連續子字串；對不上的欄位改成不收（回傳新的 list）。"""
    flat = squeeze(raw)
    out = []
    for c in cands:
        c = dict(c, notes=list(c["notes"]))
        if c["platform"] is not None and squeeze(c["platform"]) not in flat:
            c["platform"] = None
            c["notes"].append("政見與 pdftotext -raw 對不上")
        if c["education"] is not None and not all(squeeze(t) in flat for t in c["education"] + c["experience"]):
            c["education"] = c["experience"] = None
            c["notes"].append("學經歷與 pdftotext -raw 對不上")
        out.append(c)
    return out


def parse_pdf(data):
    bbox, raw, xml, grays = pdf_layers(data)
    return check_raw(parse_bulletin(parse_pages(bbox, xml, grays)), raw)


# ---------- 與中選會開票 JSON 核對 ----------

def flatten(obj):
    return [row for rows in obj.values() for row in rows]


def norm_name(name):
    # 原住民姓名：開票 JSON「高為人Sayun Watan」、公報「高為人 Sayun Watan」，比對時去掉全部空白
    return squeeze(name)


def check_against_cec(cands, rows, label):
    """公報候選人與開票 JSON 的號次、姓名、出生年、黨籍必須一一對上，否則 raise。回傳 {號次: 開票列}。"""
    got = {(c["no"], norm_name(c["name"])) for c in cands}
    want = {(r["cand_no"], norm_name(r["cand_name"])) for r in rows}
    if len(got) != len(cands) or len(want) != len(rows) or got != want:
        raise ValueError(f"{label} 公報與開票名單不一致：公報多 {sorted(got - want)}，公報少 {sorted(want - got)}")
    by_no = {r["cand_no"]: r for r in rows}
    for c in cands:
        r = by_no[c["no"]]
        if c["birth_date"][:4] != r["cand_birthyear"]:
            raise ValueError(f"{label} {c['name']} 公報生日 {c['birth_date']} 與開票出生年 {r['cand_birthyear']} 不符")
        if NO_PARTY.get(c["party"], c["party"]) != r["party_name"]:
            raise ValueError(f"{label} {c['name']} 公報黨籍 {c['party']} 與開票黨籍 {r['party_name']} 不符")
    return by_no


# ---------- 寫入 ----------

def write_bulletin_facts(conn, person_id, cand, office, district_id, url, fetched_at):
    """寫 platform／profile，回傳實際寫入的 kind。"""
    written = []
    if cand["platform"] is not None:
        upsert_fact(
            conn, f"platform:{ELECTION}:{person_id}", person_id, "platform",
            {"election": ELECTION, "office": office, "district_id": district_id,
             "title": "2022 選舉公報政見", "text": cand["platform"]},
            url, fetched_at, date=VOTE_DATE,
        )
        written.append("platform")
    if cand["education"] is not None:
        upsert_fact(
            conn, f"profile:{ELECTION}:{person_id}", person_id, "profile",
            {"election": ELECTION, "title": "2022 選舉公報學經歷",
             "education": cand["education"], "experience": cand["experience"]},
            url, fetched_at, date=VOTE_DATE,
        )
        written.append("profile")
    return written


def load_incumbents(conn):
    """回傳 [{name, person_id, birth_date, district_id}]：有 identity 對照的第 14 屆議員。"""
    rows = conn.execute(
        "SELECT s.source_key, s.person_id, p.birth_date, f.data FROM person_source_id s "
        "JOIN person p ON p.person_id = s.person_id "
        "JOIN fact f ON f.fact_key = 'office:tcc14:' || s.person_id "
        "WHERE s.source = 'tcc14' ORDER BY s.source_key"
    ).fetchall()
    return [
        {"name": r[0], "person_id": r[1], "birth_date": r[2], "district_id": json.loads(r[3])["district_id"]}
        for r in rows
    ]


def match_incumbent(inc, cands):
    """三點都成立才算同一人：姓名相同、同一選區（呼叫端只給該區候選人）、議會個人頁生日＝公報生日。回傳 (cand, 原因)。"""
    same = [c for c in cands if norm_name(c["name"]) == inc["name"]]
    if len(same) != 1:
        return None, f"2022 公報同區同名者 {len(same)} 人"
    if not inc["birth_date"]:
        return None, "議會個人頁沒有生日"
    if inc["birth_date"] != same[0]["birth_date"]:
        return None, f"生日不符（議會 {inc['birth_date']}，公報 {same[0]['birth_date']}）"
    return same[0], None


def attach_councilors(conn, district_no, cands, incumbents, url, fetched_at):
    district_id = f"tpe-council-{district_no:02d}"
    report = []
    for inc in incumbents:
        if inc["district_id"] != district_id:
            continue
        cand, why = match_incumbent(inc, cands)
        if cand is None:
            report.append((inc["name"], [], why))
            continue
        written = write_bulletin_facts(conn, inc["person_id"], cand, "tpe_councilor", district_id, url, fetched_at)
        report.append((inc["name"], written, "；".join(cand["notes"])))
    return report


def run_mayor(conn, fetched_at):
    rows = [r for r in flatten(get_json(CEC_MAYOR)) if r["prv_code"] == "63"]
    winners = [r for r in rows if r["is_victor"] == "*"]
    if len(winners) != 1:
        raise ValueError(f"2022 臺北市長開票 JSON 當選人不是恰好一位：{[r['cand_name'] for r in winners]}")
    win = winners[0]
    identity = load_identity(source=MAYOR_SOURCE)
    if win["cand_name"] not in identity:
        print(f"警告：2022 臺北市長當選人 {win['cand_name']} 不在 identity.csv（{MAYOR_SOURCE}），跳過")
        return
    person_id, verified_by = identity[win["cand_name"]]
    # identity.csv 的依據是「2026 登記冊 tpe-mayor 同名同黨」；執行時再確認一次對照沒變
    reg = conn.execute(
        "SELECT person_id FROM person_source_id WHERE source = 'tpe_reg_2026' AND source_key = ?",
        (f"tpe-mayor:{win['cand_name']}",),
    ).fetchone()
    if not reg or reg[0] != person_id:
        raise ValueError(f"identity.csv 的 {win['cand_name']} → {person_id} 與 2026 登記冊對照不一致：{reg and reg[0]}")
    upsert(conn, "person_source_id",
           {"source": MAYOR_SOURCE, "source_key": win["cand_name"], "person_id": person_id, "verified_by": verified_by},
           ("source", "source_key"))
    upsert_fact(
        conn, f"office:tpe-mayor-2022:{person_id}", person_id, "office",
        {"office": "tpe_mayor", "term": MAYOR_TERM, "district_id": "tpe-mayor", "party": win["party_name"],
         "title": f"臺北市長（第{MAYOR_TERM}屆）"},
        CEC_MAYOR, fetched_at, date=MAYOR_TERM_START,
    )
    url = bulletin_url(MAYOR_PDF)
    cands = [c for c in parse_pdf(get(url)) if c["section"] == "mayor"]
    check_against_cec(cands, rows, "臺北市長")  # 號次、姓名、出生年、黨籍一致才往下
    cand = next(c for c in cands if c["no"] == win["cand_no"])
    written = write_bulletin_facts(conn, person_id, cand, "tpe_mayor", "tpe-mayor", url, fetched_at)
    print(f"市長 {win['cand_name']}：office；公報 {written or '無'} {'；'.join(cand['notes'])}")


def run(conn):
    fetched_at = now_utc()
    cec = {}
    for u in CEC_COUNCIL:
        for r in flatten(get_json(u)):
            cec.setdefault(int(r["area_code"]), []).append(r)
    incumbents = load_incumbents(conn)
    for n in range(1, 9):
        url = bulletin_url(COUNCIL_PDF.format(n))
        try:
            cands = [c for c in parse_pdf(get(url)) if c["section"] == f"council-{n}"]
        except UnreliableBulletin as e:
            # ponytail: 整區跳過而不 raise，否則其他區也會被 rollback；2022 公報是定稿，這區每天都會一樣跳過
            names = [i["name"] for i in incumbents if i["district_id"] == f"tpe-council-{n:02d}"]
            print(f"警告：第 {n:02d} 選舉區公報無法可靠切分，跳過 {len(names)} 位現任：{e}")
            continue
        check_against_cec(cands, cec.get(n, []), f"第 {n:02d} 選舉區")
        report = attach_councilors(conn, n, cands, incumbents, url, fetched_at)
        print(f"第 {n:02d} 選舉區：公報 {len(cands)} 人，現任 {len(report)} 人，"
              f"有寫入 {sum(1 for _, w, _ in report if w)} 人")
        for name, written, why in report:
            print(f"  {name}：{'、'.join(written) or '未寫入'} {why}")
    run_mayor(conn, fetched_at)
