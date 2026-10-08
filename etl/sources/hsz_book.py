"""新竹市議會第 11 屆：議事錄附錄「議員出缺席表」（出缺勤）與逐人「質詢紀錄」PDF 清單（V16）。

- 出缺勤：議事錄清單（file.aspx?mid=79，網址參數分頁）列出每冊議事錄 PDF（定期會分上下冊，每冊 7–700 MB，有文字層）。
  附錄「新竹市議會第 11 屆第 N 次定期會／臨時會議員出缺席表」逐日標記每位議員出席（Ο）或請假（—），另有出席、請假合計。
  pdftotext -layout 讀表；每列的標記數要等於表上的日數，且 Ο、— 的個數要等於該列的出席、請假合計，否則該人該會期不收（印 log）。
  表內出現無法辨識的行時整張表不收（花蓮的教訓：頁緣裁掉表頭會讓資料併錯人）。每人每會期一筆 fact，分母是表上的日數。
  官方表只有出席、請假兩欄，不另列缺席。
- 質詢紀錄：question.aspx?mid=41（網址參數 cc=11、c=24 市政總質詢／23 單位業務質詢，分頁）每列一位議員、一份 PDF
  （議事錄抽印的逐字紀錄；聯合質詢每位議員各一列、各一份檔案）。清單沒有題目，只有屆次、會期、日期、議員與檔名，
  所以只連 PDF、不摘要、不顯示題目（V16 已定案第 6 點），不需要第三人規則的不收清單。

網站資料開放宣告（/TC/page.aspx?mid=21）允許註明出處後利用；頁面標示資料來源為新竹市議會。
只寫給有新竹市議員任職 fact 且有 2026 candidacy 的人；姓名以 etl.match 的漢字正規化對全部新竹市議員名錄，
同名或對不到的不收（印 log）。
自我檢查：python3 -m etl.sources.hsz_book [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import html
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from etl.fetch import _V4_OPENER, UA, get
from etl.sources.hua_book import write
from etl.sources.national_councilors import TERM_START
from etl.sources.nwt_book import resolve, roster_index, targets

HOST = "https://www.hsinchu-cc.gov.tw"
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "hsz_book"
OFFICE = "hsz_councilor"
TERM = 11
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔（robots.txt 只禁 /admin/，V16）
BOOKS_URL = HOST + "/tc/file.aspx?pn={}&mid=79&key=&cchk="
QUESTION_URL = HOST + "/tc/question.aspx?pn={}&mid=41&cc=" + str(TERM) + "&c={}&m=&member=&cchk="
QUESTION_TYPES = {"24": "市政總質詢", "23": "單位業務質詢"}

BOOK = re.compile(r'<li class="download-detail download-li02[^"]*">\s*([^<]*?)\s*</li>\s*<li[^>]*>\s*<a href="(/upload/79/[^"]+\.pdf)"')
PAGES = re.compile(r"\?pn=(\d+)&(?:amp;)?mid=")
Q_ROW = re.compile(r'<ul class="proposal-information-content__box01 flex">(.*?)</ul>', re.S)
CELL = re.compile(r"<li[^>]*>(.*?)</li>", re.S)
HREF = re.compile(r'href="(/upload/41/[^"]+)"')
TABLE_HEAD = re.compile(r"新竹市議會第(\d+)屆第(\d+)次(定期會|臨時會)議員出缺席表")
PRESENT, LEAVE = set("Ο○〇O"), set("—-－─–")
CJK = re.compile(r"^[一-鿿．·]+$")

_last = 0.0


def fetch(url):
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return get(url)
    finally:
        _last = time.monotonic()


def quote(path):
    return HOST + urllib.parse.quote(path)


def download(url, dest, attempts=20, ipv4=False):
    """大檔（議事錄每冊可達 700 MB）串流寫入 dest.part，中途逾時就以 Range 續傳，完成才改名。ipv4=True 只連 IPv4（臺東）。"""
    global _last
    part = dest.with_suffix(".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    for i in range(attempts):
        done = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": UA, **({"Range": f"bytes={done}-"} if done else {})}
        wait = _last + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            with (_V4_OPENER.open if ipv4 else urllib.request.urlopen)(urllib.request.Request(url, headers=headers), timeout=60) as resp:
                if done and resp.status != 206:
                    raise ValueError(f"伺服器不支援續傳：{url}")
                # 臺東主機有一行格式錯誤的標頭，Python 會丟掉它之後的所有標頭（含 Content-Length）：沒有長度就讀到結束，由呼叫端檢查檔尾
                length = resp.headers["Content-Length"]
                total = done + int(length) if length else None
                with open(part, "ab") as f:
                    while chunk := resp.read(1 << 20):
                        f.write(chunk)
            if total is None or part.stat().st_size == total:
                part.rename(dest)
                return
        except (TimeoutError, OSError) as e:
            print(f"hsz_book：下載中斷（{e}），續傳第 {i + 1} 次", flush=True)
        finally:
            _last = time.monotonic()
    raise ValueError(f"新竹市議事錄下載失敗：{url}")


def roc_date(s):
    """「115.06.09」→「2026-06-09」；格式不對回 None。"""
    m = re.fullmatch(r"(\d{2,3})\.(\d{1,2})\.(\d{1,2})", s)
    return f"{int(m[1]) + 1911}-{int(m[2]):02d}-{int(m[3]):02d}" if m else None


def last_page(page):
    return max((int(x) for x in PAGES.findall(page)), default=1)


# ---------- 議事錄清單 ----------

def parse_books(page):
    """議事錄清單一頁 → [{title, path, name}]，只收第 11 屆。"""
    out = []
    for title, path in BOOK.findall(page):
        title = re.sub(r"\s+", "", html.unescape(title))
        path = html.unescape(path)
        if title.startswith(f"第{TERM}屆"):
            out.append({"title": title, "path": path, "name": path.rsplit("/", 1)[1][:-4]})
    return out


def load_books(refresh=True):
    CACHE.mkdir(parents=True, exist_ok=True)
    books, n, last = [], 1, 1
    while n <= last:
        path = CACHE / f"list{n}.html"
        if refresh or not path.exists():
            path.write_bytes(fetch(BOOKS_URL.format(n)))
        page = path.read_text(encoding="utf-8")
        books += parse_books(page)
        last = last_page(page) if refresh else max(last, last_page(page))
        n += 1
    if not books:
        raise ValueError("新竹市議事錄清單找不到第 11 屆議事錄")
    return books


def book_pages(book, fetch_missing=True):
    """議事錄 PDF → 依頁切開的文字（pdftotext -layout，以檔名快取；只留文字，PDF 讀完即刪，每冊可達 700 MB）。"""
    txt = CACHE / "raw" / f"{book['name']}.txt"
    if not txt.exists():
        pdf = CACHE / "pdf" / f"{book['name']}.pdf"
        if not pdf.exists():
            if not fetch_missing:
                return None
            download(quote(book["path"]), pdf)
            if not pdf.read_bytes()[:4] == b"%PDF":
                raise ValueError(f"新竹市議事錄不是 PDF：{book['title']}")
        out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, check=True).stdout.decode("utf-8")
        txt.parent.mkdir(parents=True, exist_ok=True)
        txt.write_text(out, encoding="utf-8")
        pdf.unlink()
    return txt.read_text(encoding="utf-8").split("\f")


# ---------- 出缺席表 ----------

def _year(texts, month, day, today=None):
    """出缺席表沒有年份：在同一會期的各冊找「NNN 年 M 月 D 日」，只取落在第 11 屆任期內（2022-12-25 至今）的年份，
    取出現最多次的；找不到或並列第一時回 None（不猜）。"""
    today = today or time.strftime("%Y-%m-%d")
    pat = re.compile(rf"(\d{{3}})年{month}月{day}日")
    hits = Counter(int(y) + 1911 for p in texts for y in pat.findall(re.sub(r"\s", "", p)))
    ok = [(n, y) for y, n in hits.items() if TERM_START <= f"{y}-{month:02d}-{day:02d}" <= today]
    ok.sort(reverse=True)
    if not ok or (len(ok) > 1 and ok[0][0] == ok[1][0]):
        return None
    return ok[0][1]


def parse_attendance(pages):
    """→ [{session, page, days, first, rows: [{name, marks, present, leave}], bad: [行]}]。

    表頭：月份一行、日期一行（「姓名 29 30 31 3 …」），日數以「合計 出席」那一行的數字個數為準；
    表身每行「序號 姓名 Ο Ο — … 出席 [請假]」；表內任何無法辨識的行記在 bad（整張表不收）。"""
    out, cur = [], None
    for pno, page in enumerate(pages, 1):
        for line in page.split("\n"):
            s = re.sub(r"\s", "", line)
            if not s:
                continue
            m = TABLE_HEAD.search(s)
            if m:
                cur = {"session": f"第{int(m[1])}屆第{int(m[2])}次{m[3]}", "term": int(m[1]), "page": pno, "days": None,
                       "header": [], "rows": [], "bad": []}
                out.append(cur)
                continue
            if cur is None:
                continue
            if s.startswith("附註") or "係指出席" in s:
                cur = None
                continue
            row = parse_row(line) if not cur["days"] else None
            if row:
                cur["rows"].append(row)
                continue
            if s.startswith("合") and "出席" in s:
                cur["days"] = len(line.split("席", 1)[1].split())
                continue
            if cur["days"]:  # 合計請假那一行
                if "請假" in s or s.startswith("計"):
                    continue
                cur["bad"].append(line.strip())
                continue
            if not cur["rows"]:  # 表頭
                cur["header"].append(line)
                continue
            if re.fullmatch(r"\d+附錄|附錄\d+", s):  # 跨頁的頁首頁尾
                continue
            cur["bad"].append(line.strip())
    for t in out:
        t["dates"] = _header_dates(t["header"], t["days"])
    return out


def parse_row(line):
    """「 1 許修睿 Ο Ο - Ο … 20 5」→ {no, name, marks, present, leave}；不是表身的行回 None。

    以空白切詞：序號、姓名（可能被空白切開）、一串只含 Ο／— 的詞、最後是出席與（可省略的）請假合計。"""
    toks = line.split()
    if len(toks) < 3 or not toks[0].isdigit():
        return None
    i, name = 1, ""
    while i < len(toks) and CJK.match(toks[i]):
        name += toks[i]
        i += 1
    marks = ""
    while i < len(toks) and set(toks[i]) <= PRESENT | LEAVE:
        marks += toks[i]
        i += 1
    nums = toks[i:]
    if not name or not marks or not 1 <= len(nums) <= 2 or not all(x.isdigit() for x in nums):
        return None
    return {"no": int(toks[0]), "name": name, "marks": marks, "present": int(nums[0]), "leave": int(nums[1]) if len(nums) > 1 else 0}


def _header_dates(header, days):
    """表頭 → [(月, 日)]：前兩行至少有 days 個數字（且個數相同）的分別是月份、日期。
    表頭日數可以多於合計列：停止上班上課的日子表頭有、合計列沒有（第 6 次臨時會 10/5），分母照合計列。"""
    rows = [nums for nums in ([int(x) for x in re.findall(r"\d+", ln)] for ln in header) if days and len(nums) >= days]
    if len(rows) < 2 or len(rows[0]) != len(rows[1]) or not all(1 <= m <= 12 for m in rows[0]) or not all(1 <= d <= 31 for d in rows[1]):
        return None
    return list(zip(rows[0], rows[1]))


def check_row(row, days):
    """→ None（可收）或不收的原因。"""
    marks = row["marks"]
    p = sum(c in PRESENT for c in marks)
    lv = sum(c in LEAVE for c in marks)
    if len(marks) != days:
        return f"標記 {len(marks)} 個，表上 {days} 天"
    if (p, lv) != (row["present"], row["leave"]):
        return f"標記（出席 {p}、請假 {lv}）與合計（出席 {row['present']}、請假 {row['leave']}）不一致"
    return None


def collect_attendance(books, texts, roster, log=print):
    """→ [{session, file, path, page, date, days, present_ids, leave_ids, ok_ids}]，依會期去重（後列的冊次是更正版不會重複）。"""
    out, seen = [], set()
    for b in books:
        pages = texts.get(b["name"])
        if pages is None:
            log(f"hsz_book：{b['title']} 未取得，不列入")
            continue
        for t in parse_attendance(pages):
            if t["term"] != TERM:
                continue
            if t["session"] in seen:
                log(f"hsz_book：{t['session']} 出缺席表重複出現（{b['title']}），用先出現的一份")
                continue
            if t["bad"] or not t["days"] or not t["rows"]:
                log(f"hsz_book：{t['session']} 出缺席表有無法辨識的行或缺合計（{b['title']} PDF 第 {t['page']} 頁），整表不收："
                    f"{t['bad'][:2]}")
                continue
            if not t["dates"]:
                log(f"hsz_book：{t['session']} 出缺席表讀不到日期列，不收")
                continue
            same = [p for bb in books if re.sub(r"\(.冊\)", "", bb["title"]) == re.sub(r"\(.冊\)", "", b["title"])
                    for p in (texts.get(bb["name"]) or [])]  # 定期會上下冊：出缺席表在下冊，會議紀錄的日期在上冊
            y = _year(same, *t["dates"][0])
            if not y:
                log(f"hsz_book：{t['session']} 找不到年份，不收")
                continue
            seen.add(t["session"])
            rec = {"session": t["session"], "file": b["name"], "path": b["path"], "page": t["page"], "days": t["days"],
                   "date": f"{y}-{t['dates'][0][0]:02d}-{t['dates'][0][1]:02d}", "people": {}}
            for row in t["rows"]:
                pid, why = resolve(row["name"], roster)
                if not pid:
                    log(f"hsz_book：{t['session']} 出缺席表 {row['name']}：{why}")
                    continue
                bad = check_row(row, t["days"])
                if bad:
                    log(f"hsz_book：{t['session']} 出缺席表 {row['name']}：{bad}，該會期不收")
                    continue
                if pid in rec["people"]:
                    log(f"hsz_book：{t['session']} 出缺席表 {row['name']} 出現兩次，該會期不收")
                    rec["people"][pid] = None
                    continue
                rec["people"][pid] = row
            out.append(rec)
    return out


def attendance_facts(tables, pids):
    out = {}
    for t in tables:
        slug = re.sub(r"\D+", "-", t["session"].replace(f"第{TERM}屆", "")).strip("-") + ("r" if "定期" in t["session"] else "t")
        for pid, row in t["people"].items():
            if pid not in pids or row is None:
                continue
            data = {"term": TERM, "session": t["session"], "title": f"{t['session']}議員出缺席表", "meetings": t["days"],
                    "present": row["present"], "leave": row["leave"], "duty": 0, "from_lists": True}
            out.setdefault(pid, []).append((f"hszattend:{slug}:{pid}", data, f"{quote(t['path'])}#page={t['page']}", t["date"]))
    return out


# ---------- 質詢紀錄清單 ----------

def parse_questions(page):
    """質詢紀錄清單一頁 → [{term, session, date, name, path}]。每一列都要有 5 格與一個 PDF 連結，否則 raise（不猜）。"""
    out = []
    for row in Q_ROW.findall(page):
        cells = [re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", "", c))) for c in CELL.findall(row)]
        href = HREF.findall(row)
        if len(cells) != 5 or len(href) != 1 or not roc_date(cells[2]):
            raise ValueError(f"新竹市質詢紀錄清單格式未知：{cells} {href}")
        out.append({"term": cells[0], "session": cells[0] + cells[1], "date": roc_date(cells[2]), "name": cells[3],
                    "path": html.unescape(href[0])})
    return out


def load_questions(refresh=True):
    """→ [{…, doc_type}]：市政總質詢、單位業務質詢各查一次（全部頁）。"""
    out = []
    for code, doc_type in QUESTION_TYPES.items():
        n, last = 1, 1
        while n <= last:
            path = CACHE / "question" / f"c{code}-p{n}.html"
            if refresh or not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(fetch(QUESTION_URL.format(n, code)))
            page = path.read_text(encoding="utf-8")
            out += [{**q, "doc_type": doc_type} for q in parse_questions(page)]
            last = last_page(page)
            n += 1
    return out


def upload_id(path):
    name = path.rsplit("/", 1)[1]
    m = re.match(r"\d{10,}", name)
    return m.group() if m else re.sub(r"\W", "", name)


def question_facts(questions, roster, pids, log=print):
    out = {}
    for q in questions:
        if q["term"] != f"第{TERM}屆":
            continue
        pid, why = resolve(q["name"], roster)
        if not pid:
            log(f"hsz_book：質詢紀錄 {q['name']}：{why}")
            continue
        if pid not in pids:
            continue
        data = {"term": TERM, "session": q["session"], "doc_type": "質詢紀錄", "dept": q["doc_type"],
                "title": f"{q['doc_type']}紀錄（PDF）"}
        out.setdefault(pid, []).append((f"hszq:{upload_id(q['path'])}:{pid}", data, quote(q["path"]), q["date"]))
    return out


# ---------- 組成 ----------

def build(conn, books, texts, questions, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    pids = set()
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"hsz_book：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        pids.add(pid)
    tables = collect_attendance(books, texts, roster, log)
    return ts, tables, attendance_facts(tables, pids), question_facts(questions, roster, pids, log)


def run(conn):
    books = load_books()
    texts = {b["name"]: book_pages(b) for b in books}
    questions = load_questions()
    logs = Counter()
    ts, tables, att, qs = build(conn, books, texts, questions, lambda s: logs.update([s]))
    for line, n in sorted(logs.items()):
        print(f"{line}（{n} 次）" if n > 1 else line)
    na, da = write(conn, "hszattend", att, "attendance")
    nq, dq = write(conn, "hszq", qs, "interpellation")
    print(f"hsz_book：議事錄 {len(books)} 冊、出缺席表 {len(tables)} 份；對象 {len(ts)} 人；出缺勤 {len(att)} 人 {na} 筆（刪除 {da}）；"
          f"質詢紀錄 {len(questions)} 列，{len(qs)} 人 {nq} 筆（刪除 {dq}）")


def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    books = load_books(refresh=False)
    texts = {b["name"]: book_pages(b, fetch_missing=False) for b in books}
    questions = load_questions(refresh=False)
    logs = []
    ts, tables, att, qs = build(dump_conn(), books, texts, questions, logs.append)
    for line, n in sorted(Counter(logs).items()):
        print(" ", line, f"（{n} 次）" if n > 1 else "")
    print("出缺席表：", [(t["session"], t["date"], t["days"]) for t in sorted(tables, key=lambda t: t["date"])])
    print(f"議事錄 {len(books)} 冊；對象 {len(ts)} 人；出缺勤 {len(att)} 人 {sum(map(len, att.values()))} 筆；"
          f"質詢紀錄 {len(questions)} 列，{len(qs)} 人 {sum(map(len, qs.values()))} 筆")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in [p for p in names if names[p] in samples]:
        print(f"\n{names[pid]}（{pid}）")
        for _, d, url, date in sorted(att.get(pid, []), key=lambda x: x[3]):
            print(f"  出席 {d['session']:<14} {date} {d['present']:>2}／{d['meetings']:<2}（請假 {d['leave']}） {url}")
        for _, d, url, date in sorted(qs.get(pid, []), key=lambda x: x[3]):
            print(f"  {date} {d['session']} {d['title']} {urllib.parse.unquote(url)}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        for b in load_books():
            book_pages(b)
            print(b["title"], flush=True)
        load_questions()
    check([a for a in sys.argv[1:] if not a.startswith("--")])
