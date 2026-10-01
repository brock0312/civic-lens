"""2026 臺北市長、議員候選人登記冊（M1）。來源：臺北市選委會文章 JSON → 登記冊 PDF。"""
import hashlib
import re

from etl.db import upsert, upsert_fact
from etl.fetch import get, get_json, now_utc, pdf_text

# ponytail: 登記冊是 115-09-08 製表的定稿文件；10/16 審定後的不合格者要另寫來源處理（刪除或標記屆時再定）
ARTICLES = {
    "tpe_mayor": "https://web.cec.gov.tw/api/mect/article/64441",
    "tpe_councilor": "https://web.cec.gov.tw/api/mect/article/64447",
}
SOURCE = "tpe_reg_2026"
VERIFIED_BY = "auto: 首次出現於 2026 臺北市登記冊，尚未與其他來源對齊"

ROW = re.compile(r"^\s*(臺北市\S*)\s+(\d{3}/\d{2}/\d{2})\s+(\d+)\s+(.*)$")
LATIN = re.compile(r"[A-Za-z]+(?: [A-Za-z]+)*")


def roc_to_iso(roc):
    y, m, d = roc.split("/")
    return f"{int(y) + 1911:04d}-{m}-{d}"


def district_id_for(area):
    if area == "臺北市":
        return "tpe-mayor"
    m = re.fullmatch(r"臺北市第([1-8])選舉區", area)
    if not m:
        raise ValueError(f"未知的選舉區：{area!r}")
    return f"tpe-council-0{m.group(1)}"


def parse_roster(text):
    """解析 pdftotext -layout 輸出的登記冊，回傳每位登記者一個 dict。"""
    counts = set(re.findall(r"列印筆數：(\d+)", text))
    if len(counts) != 1:
        raise ValueError(f"頁首列印筆數不是唯一值：{counts}")

    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        m = ROW.match(line)
        if not m:
            continue
        area, date, reg_no, rest = m.groups()
        toks = rest.split()
        prev = lines[i - 1].strip() if i else ""
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if len(toks) == 1:
            # 政黨名太長被拆成上下兩行，本行只剩姓名
            if not prev or not nxt or LATIN.fullmatch(toks[0]):
                raise ValueError(f"第 {i + 1} 行格式未知：{line!r}")
            name, party = toks[0], prev + nxt
        else:
            name, party = " ".join(toks[:-1]), toks[-1]
            if LATIN.fullmatch(name):
                # 原住民「漢名＋羅馬拼音」：漢名在上一行，拼音拆在本行與下一行
                if not prev or not LATIN.fullmatch(nxt):
                    raise ValueError(f"第 {i + 1} 行原住民姓名格式未知：{line!r}")
                name = f"{prev} {name} {nxt}"
        out.append({
            "area": area,
            "district_id": district_id_for(area),
            "date": roc_to_iso(date),
            "reg_no": int(reg_no),
            "name": name,
            "party": party,
        })

    expected = int(counts.pop())
    if len(out) != expected:
        raise ValueError(f"解析 {len(out)} 筆，頁首列印筆數 {expected}")
    seen = set()
    for r in out:
        key = (r["district_id"], r["name"])
        if key in seen:
            raise ValueError(f"同一選舉區姓名重複：{key}")
        seen.add(key)
    return out


def roster_pdf_url(article):
    files = [f for f in article["data"]["fileList"] if "登記冊" in f["fileName"]]
    if len(files) != 1:
        raise ValueError(f"fileList 中含「登記冊」的檔案不是恰好一個：{[f['fileName'] for f in files]}")
    return f"https://web.cec.gov.tw/api/file/{files[0]['fileId']}.pdf"


def person_id_for(conn, source_key):
    row = conn.execute(
        "SELECT person_id FROM person_source_id WHERE source = ? AND source_key = ?",
        (SOURCE, source_key),
    ).fetchone()
    if row:
        return row["person_id"]
    return "p" + hashlib.sha1(f"{SOURCE}:{source_key}".encode()).hexdigest()[:10]


def run(conn):
    fetched_at = now_utc()
    for office, article_url in ARTICLES.items():
        pdf_url = roster_pdf_url(get_json(article_url))
        for r in parse_roster(pdf_text(get(pdf_url))):
            expected_office = "tpe_mayor" if r["district_id"] == "tpe-mayor" else "tpe_councilor"
            if expected_office != office:
                raise ValueError(f"{article_url} 的登記冊出現其他選舉的選舉區：{r['area']}")
            write_row(conn, office, pdf_url, r, fetched_at)


def write_row(conn, office, pdf_url, r, fetched_at):
    source_key = f"{r['district_id']}:{r['name']}"
    person_id = person_id_for(conn, source_key)
    # 只寫 name：登記冊沒有生日，不能把其他來源補上的 birth_date／birth_year 蓋成 NULL
    upsert(conn, "person", {"person_id": person_id, "name": r["name"]}, ("person_id",))
    upsert(
        conn, "person_source_id",
        {"source": SOURCE, "source_key": source_key, "person_id": person_id, "verified_by": VERIFIED_BY},
        ("source", "source_key"),
    )
    upsert_fact(
        conn,
        f"candidacy:2026-local:{person_id}",
        person_id,
        "candidacy",
        {
            "election": "2026-local",
            "office": office,
            "district_id": r["district_id"],
            "party": r["party"],
            "reg_no": r["reg_no"],
            "status": "registered",
            # 登記冊由臺北市選委會發布，只是放在中選會的共用平台 web.cec.gov.tw 上；前端腳註不能依網域推論
            "publisher": "臺北市選舉委員會",
        },
        pdf_url,
        fetched_at,
        date=r["date"],
    )
