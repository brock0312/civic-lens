"""南投縣議會第 20 屆議事錄（www.ntcc.gov.tw/tw/news/p03.aspx?kind=23）：縣政總質詢「議員建議事項」（V16）。

議事錄每個會期一冊 PDF（有文字層）。定期會的縣政總質詢會議紀錄之後附「南投縣議會第 20 屆第 N 次定期會議員建議事項（第 M 會次）」
表格，三欄：類別、議員姓名、建議事項，一格一列（一位議員一個類別一列）。題目照官方原文全文（V16 已定案第 6 點、
使用者 2026-10-08 決定），每列一筆 fact，日期是該會次的日期，連到 PDF 該頁。第三人規則（HANDOFF §3 第 5 條）：
data/nan_withheld.csv 列出的列不收（只寫原因，不寫姓名）。

表格靠框線切格，不靠 -layout 的文字對齊：姓名、類別在格內垂直置中，用文字行切會把題目併到上一位（花蓮的教訓 ①）。
每頁算圖（100 dpi 灰階）找表格的垂直線（必須恰好 4 條）與各欄自己的水平線（合併儲存格時，姓名欄的格線比題目欄少）；
題目欄的每一格對到包含它中點的姓名格、類別格。姓名欄有格線而題目欄沒有（題目跨兩位議員）時整頁不收。
跨頁：續頁第一格的類別、姓名都空白，是上一頁最後一格的延續，文字接回去；其他姓名空白的格，官方寫法是延續上一位議員。

不收：出缺勤（會議紀錄寫「出席：（如簽到簿）」）、影片（一場一支，標題沒有姓名）、書面質詢（沒有）。
只寫給有南投縣議員任職 fact 且有 2026 candidacy 的人；姓名以 etl.match 的漢字正規化對全部南投縣議員名錄，
名錄同名或對不到的不收（印 log）。
自我檢查：python3 -m etl.sources.nan_book [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import csv
import html
import json
import re
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

from etl.bulletin_grid import DARK, _merge
from etl.fetch import get
from etl.rosters import _CA
from etl.sources.hua_book import resolve_token, split_names, write
from etl.sources.nwt_book import resolve, roster_index, targets
from etl.sources.tpe_bulletin_2022 import join_wrapped, line_text, read_pgm, to_lines

HOST = "https://www.ntcc.gov.tw"
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "nan"
WITHHELD = ROOT / "data" / "nan_withheld.csv"
OFFICE = "nan_councilor"
TERM = 20
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔（robots.txt 404，V16）
DPI = 100
S = 72 / DPI  # 像素 → pt
DOC_TYPE = "議員建議事項"

ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL = re.compile(r"<td>\s*([^<]*?)\s*</td>")
FILE = re.compile(r"upload/news/(\d+)\.pdf")
WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
# 以下都比對「去掉空白」後的文字；「屆」可省（第 5 次定期會第 2 會次的表頭漏印）
HEADING = re.compile(rf"南投縣議會第{TERM}屆?第(\d+)次(定期會|臨時會)議員建議事項[（(]第(\d+)會次[)）](\d{{2,3}})年(\d{{1,2}})月(\d{{1,2}})日")
OTHER_HEAD = re.compile(r"會議[紀記]錄|議事錄|目錄|時間：中華民國|^第\d+次會議")  # 頁首前 10 個字詞：會議紀錄等其他章節

_last = 0.0


def fetch(url):
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return get(url, cafile=_CA["nan"])
    finally:
        _last = time.monotonic()


def pdf_url(file_id, page=None):
    return f"{HOST}/upload/news/{file_id}.pdf" + (f"#page={page}" if page else "")


# ---------- 議事錄清單 ----------

def parse_list(page):
    """p03.aspx?kind=23 的一頁 → [{id, title, kind}]（第 20 屆；kind：定期會／臨時會）。"""
    out = []
    for tr in ROW.findall(page):
        cells = CELL.findall(tr)
        f = FILE.search(tr)
        if f and len(cells) >= 3 and cells[0] == f"第{TERM}屆":
            out.append({"id": f.group(1), "title": f"第{TERM}屆{cells[1]}{cells[2]}議事錄", "kind": cells[2]})
    return out


def load_books(refresh=True):
    books = []
    for p in (1, 2, 3):
        path = CACHE / f"list_{p}.html"
        if refresh or not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(fetch(f"{HOST}/tw/news/p03.aspx?page={p}&kind=23"))
        books += [b for b in parse_list(path.read_text(encoding="utf-8")) if b["id"] not in {x["id"] for x in books}]
    if not books:
        raise ValueError("南投議事錄清單找不到第 20 屆議事錄")
    return books


def book_pdf(file_id, fetch_missing=True):
    """議事錄 PDF 的快取路徑（以檔名快取；改版會換檔名）；沒有快取且 fetch_missing=False 時回 None。"""
    pdf = CACHE / "pdf" / f"{file_id}.pdf"
    if not pdf.exists():
        if not fetch_missing:
            return None
        data = fetch(pdf_url(file_id))
        if not data.startswith(b"%PDF"):
            raise ValueError(f"南投議事錄不是 PDF：{file_id}")
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(data)
    return pdf


# ---------- 版面：字詞與框線 ----------

COMPAT = re.compile(r"[\uf900-\ufaff]")


def compat(text):
    """CJK 相容表意字（第 5 次定期會的「年」U+F98E、「類」U+F9D0）換成統一表意字；其他字不動（不用整段 NFKC，會把全形標點改成半形）。"""
    return COMPAT.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text)


def page_words(pdf):
    """pdftotext -bbox → 每頁 [(x0, y0, x1, y1, text)]（pt）。"""
    bbox = subprocess.run(["pdftotext", "-bbox", str(pdf), "-"], capture_output=True, check=True).stdout.decode("utf-8")
    return [[(float(a), float(b), float(c), float(d), compat(html.unescape(t))) for a, b, c, d, t in WORD.findall(chunk)]
            for chunk in bbox.split("<page ")[1:]]


def page_mask(pdf, pno):
    out = subprocess.run(["pdftoppm", "-r", str(DPI), "-gray", "-f", str(pno), "-l", str(pno), "-singlefile", str(pdf)],
                         capture_output=True, check=True).stdout
    w, h, px = read_pgm(out)
    return w, h, px.translate(DARK)


def grid(mask, top_after=None):
    """一頁的表格框線 → {cols: [4 條垂直線 x], bounds: [類別欄, 姓名欄, 題目欄各自的水平線 y]}（pt）或 (None, 原因)。

    top_after：表頭最後一行字的底（pt），表身從它下面第一條水平線開始；None 表示表格從第一條水平線開始（續頁）。"""
    w, h, m = mask
    rules = [(a + b) / 2 for a, b in _merge([y for y in range(h) if max(map(len, m[y * w:(y + 1) * w].split(b"\0"))) >= 0.3 * w])]
    if top_after is not None:
        rules = [y for y in rules if y * S > top_after]
    if len(rules) < 2:
        return None, "找不到表格框線"
    top, bottom = int(rules[0]), int(rules[-1])
    cols = [(a + b) / 2 for a, b in _merge([x for x in range(w) if m[top * w + x:bottom * w:w].count(1) >= 0.9 * (bottom - top)])]
    if len(cols) != 4:
        return None, f"垂直線 {len(cols)} 條（應為 4）"
    bounds = []
    for x0, x1 in zip(cols, cols[1:]):
        a, b = int(x0) + 3, int(x1) - 2
        ys = [y for y in range(top - 2, bottom + 3) if m[y * w + a:y * w + b].count(1) >= 0.9 * (b - a)]
        bounds.append([(p + q) / 2 * S for p, q in _merge(ys)])
    return {"cols": [x * S for x in cols], "bounds": bounds}, None


# ---------- 表格 → 列 ----------

def heading(words):
    """表頭頁 → (會期, 會次, 日期, 表頭底 y) 或 None。"""
    text = re.sub(r"\s", "", "".join(w[4] for w in words))
    m = HEADING.search(text)
    if not m:
        return None
    labels = [w for w in words if w[4] in ("類別", "議員姓名", "建議事項")]
    if not labels:
        return None
    no, kind, meeting, y, mo, d = m.groups()
    date = f"{int(y) + 1911}-{int(mo):02d}-{int(d):02d}"
    return f"第{TERM}屆第{no}次{kind}", f"第{meeting}會次", date, max(w[3] for w in labels)


CJK = "\u3000-\u303f\u4e00-\u9fff\uf900-\ufaff\uff01-\uff0f\uff1a-\uff20\uff3b-\uff40\uff5b-\uff65"
SPACED = re.compile(rf"(?<=[{CJK}])\s+(?=[{CJK}])")


def cell_text(words):
    """格內各行接起來；左右對齊撐開的字距（「導 護 老 師 、 志 工」）只在兩個中文字或全形標點之間才去掉，其他空白照留（「MOU 10 億」）。"""
    lines = [line_text(l) for l in to_lines(words)]
    out = ""
    for ln in lines:
        out = join_wrapped(out, ln) if out else ln
    return SPACED.sub("", out)


def rows(words, g):
    """一頁的表格 → [{cat, name, text}]（由上而下）或 (None, 原因)。字詞依中心點歸格。"""
    cols, (cat_b, name_b, text_b) = g["cols"], g["bounds"]
    for y in cat_b + name_b:  # 類別、姓名欄的每條格線都必須也切過題目欄，否則一格題目跨兩位議員
        if not any(abs(y - t) <= 3 for t in text_b):
            return None, f"姓名或類別欄的格線（y={y:.0f}）沒有切過題目欄"

    def inside(w, x0, x1, y0, y1):
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        return x0 < cx < x1 and y0 < cy < y1

    def owner(bounds, y):
        return next(((a, b) for a, b in zip(bounds, bounds[1:]) if a < y < b), None)

    def placed(w):
        return any(owner(b, (w[1] + w[3]) / 2) and inside(w, cols[i], cols[i + 1], text_b[0], text_b[-1])
                   for i, b in enumerate((cat_b, name_b, text_b)))

    lost = [w[4] for w in words if text_b[0] < (w[1] + w[3]) / 2 < text_b[-1] and not placed(w)]
    if lost:  # 字壓在框線上或在欄外：歸不了格就不猜
        return None, f"有字詞歸不了格：{''.join(lost)[:20]}"
    out = []
    for ya, yb in zip(text_b, text_b[1:]):
        mid = (ya + yb) / 2
        row = {"text": cell_text([w for w in words if inside(w, cols[2], cols[3], ya, yb)])}
        for key, i, bounds in (("cat", 0, cat_b), ("name", 1, name_b)):
            cell = owner(bounds, mid)
            row[key] = "".join(line_text(l) for l in to_lines([w for w in words if cell and inside(w, cols[i], cols[i + 1], *cell)]))
        out.append(row)
    stray = [w[4] for w in words if g["bounds"][2] and (w[1] + w[3]) / 2 > text_b[-1] and not re.fullmatch(r"\d+", w[4])]
    return out, ("表格下方有其他文字：" + "".join(stray)[:20]) if stray else None


def parse_book(pdf, log=print):
    """議事錄 PDF → [{session, meeting, date, page, n, cat, name, text}]：每列一筆（跨頁的列已接回）。"""
    pages = page_words(pdf)
    out, cur, prev_cols = [], None, None
    for pno, words in enumerate(pages, 1):
        if all(re.fullmatch(r"\d+", w[4]) for w in words):  # 空白頁（只有頁碼）：表格可能在下一頁接續
            continue
        head = heading(words)
        if head:
            cur = {"session": head[0], "meeting": head[1], "date": head[2]}
            g, why = grid(page_mask(pdf, pno), top_after=head[3])
        elif cur and words and not OTHER_HEAD.search("".join(w[4] for w in words[:10])):
            g, why = grid(page_mask(pdf, pno))
            widths = lambda cols: [b - a for a, b in zip(cols, cols[1:])]  # 第 5 次定期會各頁整個表格會左右平移幾 pt，只比欄寬
            if g and (not prev_cols or any(abs(a - b) > 3 for a, b in zip(widths(g["cols"]), widths(prev_cols)))):
                g, why = None, "續頁的欄位和上一頁不同"
            if g and any((w[1] + w[3]) / 2 < g["bounds"][2][0] for w in words):
                g, why = None, "表格上方有文字"
            if not g:  # 不是續頁：表格結束（印出來供人工確認沒有漏掉續頁）
                log(f"nan_book：{pdf.stem} PDF 第 {pno} 頁不當續頁（{why}），{cur['session']}{cur['meeting']}的表格到上一頁為止")
                cur = prev_cols = None
                continue
        else:
            cur = prev_cols = None
            continue
        if not g:
            log(f"nan_book：{pdf.stem} PDF 第 {pno} 頁 {cur['session']}{cur['meeting']} {why}，整頁不收（續頁也不收）")
            cur = prev_cols = None
            continue
        got, why = rows(words, g)
        if got is None:
            log(f"nan_book：{pdf.stem} PDF 第 {pno} 頁 {cur['session']}{cur['meeting']} {why}，整頁不收")
            cur = prev_cols = None
            continue
        if why:
            log(f"nan_book：{pdf.stem} PDF 第 {pno} 頁 {why}")
        prev_cols = g["cols"]
        out = add_rows(out, cur, pno, got, continued=not head)
    return out


END = re.compile(r"[。？?！!」）)]$")


def add_rows(out, cur, pno, got, continued):
    """把一頁的列接到 out 後面（回傳新串列）。continued：這頁是續頁。

    續頁第一格接回上一頁最後一列的情形：類別、姓名都空白；或姓名相同、上一列的文字停在句子中間（官方表格跨頁時重印姓名，
    類別有時印成另一個，例：第 5 次定期會第 16 會次「警政」接「工務」，類別就兩個都列）。"""
    out, n = list(out), 0
    for i, r in enumerate(got):
        if not r["text"]:
            continue
        last = out[-1] if out else None
        if continued and i == 0 and last and last["page"] < pno \
                and (last["session"], last["meeting"]) == (cur["session"], cur["meeting"]) \
                and ((not r["cat"] and not r["name"]) or (r["name"] == last["name"] and not END.search(last["text"]))):
            cat = last["cat"] + (r["cat"] if r["cat"] and r["cat"] != last["cat"] else "")
            out[-1] = {**last, "cat": cat, "text": join_wrapped(last["text"], r["text"])}
            continue
        out.append({**cur, "page": pno, "n": n, **r})
        n += 1
    return out


# ---------- 第三人規則：不收的列 ----------

def load_withheld(path=WITHHELD):
    """data/nan_withheld.csv：item（<檔名>:<PDF 頁>:<列>）、reason。"""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {r["item"]: r["reason"] for r in csv.DictReader(f)}


def item_id(file_id, r):
    return f"{file_id}:{r['page']}:{r['n']}"


# ---------- 快取：每冊的解析結果 ----------

def book_rows(book, fetch_missing=True, log=print):
    """每冊的列（快取在 data/cache/nan/rows/<檔名>.json，連同解析 log）；沒有 PDF 且 fetch_missing=False 時回 None。"""
    path = CACHE / "rows" / f"{book['id']}.json"
    if not path.exists():
        pdf = book_pdf(book["id"], fetch_missing)
        if pdf is None:
            return None
        logs = []
        data = {"rows": parse_book(pdf, logs.append), "log": logs}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    for line in data["log"]:
        log(line)
    return data["rows"]


# ---------- 組成紀錄 ----------

def councillors(r, prev):
    """一列的議員姓名詞；姓名格空白時延續上一列（同一張表）的議員。"""
    if r["name"]:
        return [re.sub(r"^(副議長|議長)", "", t) for t in split_names(r["name"])]  # 「議長何勝豐」
    if prev and (prev["session"], prev["meeting"]) == (r["session"], r["meeting"]):
        return prev["names"]
    return []


def question_facts(books, texts, roster, pids, withheld, log=print):
    """同一段文字（去空白）只收最早的會次：後面的會次出現一模一樣的文字（第 6 次定期會第 12 會次有 5 列整段照抄第 5 次定期會
    第 17 會次吳國昌的建議，其中 3 列掛在別的議員名下），疑為官方複製錯誤，後出現的不收（印 log）。"""
    out, held, n = {}, [], 0
    name_of = {ids[0]: k for k, ids in roster.items() if len(ids) == 1}  # 名錄的正規化姓名（漢字部分）
    dated = sorted(((r["date"], b["id"], i) for b in books for i, r in enumerate(texts.get(b["id"]) or [])))
    first = {}
    for _, fid, i in dated:
        first.setdefault(re.sub(r"\s", "", texts[fid][i]["text"]), (fid, i))
    for b in books:
        prev = None
        for i, r in enumerate(texts.get(b["id"]) or []):
            r = {**r, "names": councillors(r, prev)}
            prev = r
            iid = item_id(b["id"], r)
            if iid in withheld:
                held.append((iid, r))
                continue
            key_ = re.sub(r"\s", "", r["text"])
            if len(key_) >= 10 and first[key_] != (b["id"], i):
                fid, j = first[key_]
                o = texts[fid][j]
                log(f"nan_book：{r['session']}{r['meeting']} {r['name']}（{b['id']} PDF 第 {r['page']} 頁）的文字和"
                    f"{o['session']}{o['meeting']} {o['name']} 那一列完全相同，疑為官方複製，不收")
                continue
            if not r["names"]:
                log(f"nan_book：{r['session']}{r['meeting']} PDF 第 {r['page']} 頁第 {r['n'] + 1} 列沒有議員姓名，不收")
                continue
            ids, names = [], []
            for name in r["names"]:
                got, why = resolve_token(name, roster)
                if got:
                    ids += got
                    names += [name_of[p] for p in got] if len(got) > 1 else [name]  # 黏在一起的兩個名字存切開後的姓名
                else:
                    names.append(name)
                    log(f"nan_book：{r['session']}{r['meeting']} 議員 {name}：{why}（{b['id']} PDF 第 {r['page']} 頁）")
            n += 1
            data = {"term": TERM, "session": r["session"], "meeting": r["meeting"], "title": r["text"], "doc_type": DOC_TYPE,
                    "dept": r["cat"] or None, "councillors": names, "page": r["page"]}
            for pid in dict.fromkeys(ids):
                if pid in pids:
                    out.setdefault(pid, []).append((f"ntccq:{iid}:{pid}", data, pdf_url(b["id"], r["page"]), r["date"]))
    return out, held, n


def build(conn, books, texts, withheld, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    pids = set()
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"nan_book：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        pids.add(pid)
    qs, held, n = question_facts(books, texts, roster, pids, withheld, log)
    return ts, qs, held, n


def run(conn):
    books = load_books()
    logs = Counter()
    texts = {b["id"]: book_rows(b, log=lambda s: logs.update([s])) for b in books}
    ts, qs, held, n = build(conn, books, texts, load_withheld(), lambda s: logs.update([s]))
    for line, k in sorted(logs.items()):
        print(f"{line}（{k} 次）" if k > 1 else line)
    nq, dq = write(conn, "ntccq", qs, "interpellation")
    print(f"nan_book：議事錄 {len(books)} 冊、建議事項 {n} 列；對象 {len(ts)} 人；{len(qs)} 人 {nq} 筆（刪除 {dq}，依第三人規則不收 {len(held)} 列）")


# ---------- 自我檢查 ----------

def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    books = load_books(refresh=False)
    logs = []
    texts = {b["id"]: book_rows(b, fetch_missing=False, log=logs.append) for b in books}
    ts, qs, held, n = build(dump_conn(), books, texts, load_withheld(), logs.append)
    for line, k in sorted(Counter(logs).items()):
        print(" ", line, f"（{k} 次）" if k > 1 else "")
    rows_ = [r for t in texts.values() if t for r in t]
    print("會次：", sorted(Counter(f"{r['session']}" for r in rows_).items()))
    print(f"議事錄 {len(books)} 冊（已解析 {sum(t is not None for t in texts.values())}）；建議事項 {n} 列；"
          f"對象 {len(ts)} 人；{len(qs)} 人 {sum(map(len, qs.values()))} 筆；不收 {len(held)} 列")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in sorted(names, key=lambda p: -len(qs.get(p, []))):
        print(f"  {names[pid]}：{len(qs.get(pid, []))}")
    for pid in [p for p in names if any(s in names[p] for s in samples)]:
        print(f"\n{names[pid]}（{pid}）")
        for _, d, url, date in qs.get(pid, []):
            print(f"  {date} {d['session']}{d['meeting']} {d['dept']}：{d['title'][:80]} {url}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        for b in load_books():
            book_pdf(b["id"])
            print(b["title"], flush=True)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
