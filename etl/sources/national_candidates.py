"""2026 全國直轄市長、縣市長、議員候選人（L1，V11 §1）。

來源：中選會 web.cec.gov.tw 文章 64709 的附件 1-1／2-1／3-1／4-1（登記彙總表），
以 1-2／2-2／3-2／4-2（政黨推薦彙總表）的每區「合計」與「應選名額」驗證。
臺北由 tpe_candidates 負責（臺北登記冊有登記序號）；這裡只拿臺北的名單和 DB 交叉核對。
"""
import hashlib
import re
import time

from etl import cec_pdf
from etl.db import upsert, upsert_fact
from etl.fetch import get, get_json, now_utc, pdf_text
from etl.sources.national_districts import ISO, council_id
from etl.sources.tpe_candidates import SOURCE as TPE_SOURCE, roc_to_iso

ARTICLE_URL = "https://web.cec.gov.tw/api/central/article/64709"
SOURCE = "cec_reg_2026"
VERIFIED_BY = "auto: 首次出現於中選會 2026 候選人登記彙總表（article 64709），尚未與其他來源對齊"
PUBLISHER = "中央選舉委員會"
# 附件前綴：(登記彙總表, 政黨推薦彙總表, 職位)
TABLES = [("1-1", "1-2", "mayor"), ("2-1", "2-2", "councilor"), ("3-1", "3-2", "mayor"), ("4-1", "4-2", "councilor")]

DATE = re.compile(r"^\d{3}/\d{2}/\d{2}$")
AREA = re.compile(r"(\S{2}[縣市])(?:第(\d+)選舉區)?")
HEADERS = ("選舉區", "登記日期", "姓名", "推薦之政黨", "備註")
SEPARATORS = "．‧·・"
LATIN_CHAR_WIDTH = 6  # 登記表的拉丁字母寬 6pt、漢字 12pt


def is_latin(ch):
    return ch.isalpha() and ord(ch) < 0x2E80


def join_name(parts, full_width):
    """把跨行的姓名接回來。parts = [(該行文字, 該行寬度)]。

    - 行內原有的空白已由 line_text 保留。
    - 間隔號（．‧·・）前後不加空白：Excel 在全形標點前後都會斷行，行內也從不在間隔號旁留空白。
    - 漢字與拼音之間加一個半形空白（與臺北登記冊 `林筱薇 Icyang Tamana` 一致）。
    - 拼音接拼音：Excel 只在空白處斷行，除非單字比整格還寬。所以上一行沒寫滿 → 原文是空白；
      上一行寫滿、下一行小寫開頭 → 單字被硬切（如 Drusaljiya／n），直接相連；大寫開頭 → 新的單字，加空白。
    """
    out = parts[0][0]
    for (prev, width), (cur, _) in zip(parts, parts[1:]):
        a, b = prev[-1], cur[0]
        if a in SEPARATORS or b in SEPARATORS:
            sep = ""
        elif is_latin(a) and is_latin(b):
            full = width + LATIN_CHAR_WIDTH > full_width + 0.5
            sep = "" if full and b.islower() else " "
        elif is_latin(a) or is_latin(b):
            sep = " "
        else:
            sep = ""
        out += sep + cur
    return out


def parse_roster(bbox):
    """登記彙總表 → [{"area", "date", "name", "party", "note"}]，依原表順序。"""
    cells = []  # 先收集所有格，姓名欄的滿格寬度要看整份文件
    for words in cec_pdf.pages(bbox):
        hdr = {t: (x0, x1) for x0, _, x1, _, t in words if t in HEADERS}
        if len(hdr) < len(HEADERS):
            continue
        hy = max(y0 for _, y0, _, _, t in words if t == "登記日期")
        bounds = [
            (hdr["選舉區"][1] + hdr["登記日期"][0]) / 2,
            hdr["登記日期"][1] + 8,
            (hdr["姓名"][1] + hdr["推薦之政黨"][0]) / 2,
            (hdr["推薦之政黨"][1] + hdr["備註"][0]) / 2,
        ]

        def col(w):
            return sum((w[0] + w[2]) / 2 > b for b in bounds)  # 0 選舉區 1 日期 2 姓名 3 政黨 4 備註

        body = [w for w in words if w[1] > hy + 5]
        page_rows = [{"yc": (w[1] + w[3]) / 2, "date": w[4]} for w in body if col(w) == 1 and DATE.match(w[4])]
        page_rows.sort(key=lambda r: r["yc"])
        if not page_rows:
            continue
        for c in (0, 2, 3, 4):
            lines = cec_pdf.group_lines([w for w in body if col(w) == c])
            ys = sorted(lines)
            groups = cec_pdf.assign(ys, lines, [r["yc"] for r in page_rows], optional=(c == 4))
            for r, g in zip(page_rows, groups):
                r[c] = [(cec_pdf.line_text(lines[y]), lines[y][-1][1] - lines[y][0][0]) for y in g]
        for r in page_rows:
            if not r[0] or not r[2] or not r[3]:
                raise ValueError(f"登記表缺欄位：{r}")
        cells += page_rows

    if not cells:
        raise ValueError("登記表沒有任何資料列")
    full_width = max(w for r in cells for _, w in r[2])
    return [{"area": "".join(t for t, _ in r[0]), "date": r["date"], "name": join_name(r[2], full_width),
             "party": "".join(t for t, _ in r[3]), "note": "".join(t for t, _ in r[4])} for r in cells]


def parse_summary(text):
    """政黨推薦彙總表 → {選舉區: (合計, 應選名額)}。每列最後兩個數字就是這兩欄；
    有些列和直排的表頭字夾在同一行（例如「… 1 推 1 2 額 1」），只取數字即可。"""
    out, widths = {}, set()
    for line in text.splitlines():
        m = re.match(r"^\s*(\S+)\s+(.*)$", line)
        if not m or not AREA.fullmatch(m.group(1)) or AREA.fullmatch(m.group(1)).group(1) not in ISO:
            continue
        nums = [int(x) for x in re.findall(r"\d+", m.group(2))]
        widths.add(len(nums))
        if m.group(1) in out:
            raise ValueError(f"彙總表選舉區重複：{m.group(1)}")
        out[m.group(1)] = (nums[-2], nums[-1])
    if len(widths) != 1:
        raise ValueError(f"彙總表各列的數字欄數不一致：{widths}")
    return out


def district_for(area, kind):
    m = AREA.fullmatch(area)
    if not m or m.group(1) not in ISO:
        raise ValueError(f"未知的選舉區：{area!r}")
    iso, n = ISO[m.group(1)], m.group(2)
    if (kind == "mayor") != (n is None):
        raise ValueError(f"選舉區 {area!r} 與表別 {kind} 不符")
    if kind == "mayor":
        return f"{iso}-mayor", f"{iso}_mayor"
    return council_id(iso, int(n)), f"{iso}_councilor"


def check_counts(rows, summary, seats):
    """登記人數逐區對 x-2 的合計；x-2 的應選名額對 district 表。對不上就 raise。

    seats：{district_id: 名額}（DB 的 district 表）。
    """
    counts = {}
    for r in rows:
        counts[r["area"]] = counts.get(r["area"], 0) + 1
    want = {a: total for a, (total, _) in summary.items() if total}
    if counts != want:
        diff = {a: (counts.get(a), want.get(a)) for a in set(counts) | set(want) if counts.get(a) != want.get(a)}
        raise ValueError(f"登記人數與政黨推薦彙總表合計不符：{diff}")
    for area, (_, s) in summary.items():
        kind = "councilor" if "選舉區" in area else "mayor"
        district_id, _ = district_for(area, kind)
        if seats.get(district_id) != s:
            raise ValueError(f"{area} 應選名額 {s} 與 district 表 {seats.get(district_id)} 不符")


def with_order(rows, kind):
    """加上 district_id、office、list_order（該區在官方名冊中的列序，從 1 開始）。"""
    seen, out = {}, []
    for r in rows:
        district_id, office = district_for(r["area"], kind)
        seen[district_id] = seen.get(district_id, 0) + 1
        out.append({**r, "district_id": district_id, "office": office, "list_order": seen[district_id]})
    keys = [(r["district_id"], r["name"]) for r in out]
    if len(keys) != len(set(keys)):
        raise ValueError("同一選舉區姓名重複")
    return out


def check_taipei(conn, rows):
    """全國名冊裡的臺北名單必須和 tpe_candidates 寫進 DB 的完全相同（選區＋姓名）。"""
    national = {f"{r['district_id']}:{r['name']}" for r in rows if r["district_id"].startswith("tpe-")}
    db = {row["source_key"] for row in conn.execute(
        "SELECT source_key FROM person_source_id WHERE source = ?", (TPE_SOURCE,))}
    if national != db:
        raise ValueError(f"臺北交叉核對不符：只在全國名冊 {sorted(national - db)}；只在 DB {sorted(db - national)}")
    return len(national)


def person_id_for(conn, source_key):
    row = conn.execute(
        "SELECT person_id FROM person_source_id WHERE source = ? AND source_key = ?", (SOURCE, source_key)
    ).fetchone()
    if row:
        return row["person_id"]
    return "p" + hashlib.sha1(f"{SOURCE}:{source_key}".encode()).hexdigest()[:10]


def write_row(conn, r, pdf_url, fetched_at):
    source_key = f"{r['district_id']}:{r['name']}"
    person_id = person_id_for(conn, source_key)
    upsert(conn, "person", {"person_id": person_id, "name": r["name"]}, ("person_id",))
    upsert(conn, "person_source_id",
           {"source": SOURCE, "source_key": source_key, "person_id": person_id, "verified_by": VERIFIED_BY},
           ("source", "source_key"))
    upsert_fact(
        conn, f"candidacy:2026-local:{person_id}", person_id, "candidacy",
        {"election": "2026-local", "office": r["office"], "district_id": r["district_id"], "party": r["party"],
         "status": "registered", "list_order": r["list_order"], "publisher": PUBLISHER},
        pdf_url, fetched_at, date=roc_to_iso(r["date"]),
    )


def file_url(article, prefix):
    files = [f for f in article["data"]["fileList"] if f["fileName"].startswith(prefix + "(")]
    if len(files) != 1:
        raise ValueError(f"文章 64709 找不到唯一的附件 {prefix}")
    return f"https://web.cec.gov.tw/api/file/{files[0]['fileId']}.pdf"


def run(conn):
    fetched_at = now_utc()
    article = get_json(ARTICLE_URL)
    seats = {row["district_id"]: row["seats"] for row in conn.execute("SELECT district_id, seats FROM district")}
    parsed = []
    for reg, summ, kind in TABLES:
        reg_url, summ_url = file_url(article, reg), file_url(article, summ)
        time.sleep(1.1)
        rows = parse_roster(cec_pdf.bbox_html(get(reg_url)))
        time.sleep(1.1)
        check_counts(rows, parse_summary(pdf_text(get(summ_url))), seats)
        parsed.append((reg_url, with_order(rows, kind)))

    n_tpe = check_taipei(conn, [r for _, rows in parsed for r in rows])
    counts = {}
    for pdf_url, rows in parsed:
        for r in rows:
            if r["district_id"].startswith("tpe-"):
                continue
            write_row(conn, r, pdf_url, fetched_at)
            key = (r["district_id"].split("-")[0], r["office"].split("_")[1])
            counts[key] = counts.get(key, 0) + 1
    print(f"全國候選人：臺北交叉核對 {n_tpe} 人相符；寫入 {sum(counts.values())} 人 {sorted(counts.items())}")
