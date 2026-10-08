"""花蓮縣議會第 20 屆議事錄（www.hlcc.gov.tw meeting_book_search.php）：大會出缺勤、質詢答覆表、質詢（錄音）紀錄索引（V16）。

議事錄 PDF（上冊，與只有第 19、20 次臨時大會的單冊）有文字層，用 pdftotext -raw 讀（-layout 在第 2 次定期大會那冊會把
數字擠到下一行）。下冊是施政報告與議決案執行情形，不讀。第 20 屆的議事錄從第 2 次定期大會（2023-10）開始上架，
成立大會、第 1 次定期大會與第 1–3 次臨時大會沒有刊出；最新一冊約落後 10 個月（2026-10 時到第 6 次定期大會與第 20 次臨時大會）。

- 出缺勤：每次大會的會議紀錄（「一讀會會議紀錄」「第 N 次會議紀錄」）列「出席：」「請假：」名單（列席之前；
  列席之後的請假名單只收帶議員職稱的人）。
  兩份名單都沒有的人原因不明，不另列缺席（比照新北，使用者 2026-10-04 決定）。分母是本站收錄、會議紀錄列有出席名單的大會次數；
  分組審查會議（審查委員會）只有委員出席，不列入。每人每會期（定期大會、臨時大會）一筆 fact；
  同一會期出現在兩冊（第 16 次臨時大會）時以會期與會次去重。
- 質詢答覆表：「口頭質詢」「書面質詢」兩章，一格一題，有質詢人、類別、質詢事項。題目照官方原文（V16 已定案第 6 點），
  連到 PDF 該頁。聯合質詢掛給每位質詢人。第三人規則（HANDOFF §3 第 5 條）：data/hua_withheld.csv 列出的題目不收。
- 質詢（錄音）紀錄：定期大會的「議員質詢索引表」列每位議員發言的頁碼；每人每會期一筆，只連到索引表那一頁，不做摘要。

只寫給有花蓮縣議員任職 fact 且有 2026 candidacy 的人；姓名以 etl.match 的漢字正規化對全部花蓮縣議員名錄，
名錄同名或對不到的不收（印 log）。
自我檢查：python3 -m etl.sources.hua_book [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import csv
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import UA, get, now_utc, pdf_text
from etl.sources.nwt_book import key, resolve, roster_index, targets

HOST = "https://www.hlcc.gov.tw"
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "hua_book"
WITHHELD = ROOT / "data" / "hua_withheld.csv"
OFFICE = "hua_councilor"
TERM = 20
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔（robots.txt 404，V16）

BOOK = re.compile(r'/>\s*(第20屆[^<]*?)\s*<span class="color_brown">\(\s*(\d{4}-\d\d-\d\d)</span>.*?href="upfile/([\w-]+)\.pdf"', re.S)
# 以下都比對「去掉空白、NFKC 後」的行
SESSION_HEAD = re.compile(r"^花蓮縣議會第20屆第([\d、]+)次(定期|臨時)大會會議紀錄$")
MEETING_HEAD = re.compile(r"^(一讀會|第\d+次)會議紀錄$")
LABEL = re.compile(r"^(出席|請假|列席|主席|紀錄|地點)：")
DATE = re.compile(r"中華民國(\d+)年(\d+)月(\d+)日")
CHAPTER = re.compile(r"^花蓮縣議會第20屆第(\d+)次定期大會(口頭|書面)質詢$")
INDEX_HEAD = re.compile(r"^花蓮縣議會第20屆第(\d+)次定期大會議員質詢索引表$")
PAGE_HEADER = re.compile(r"^(\d*(口頭|書面)質詢\d*|\d+會議紀錄|會議紀錄\d+)$")
NAME_SPLIT = re.compile(r"[、，,]")
NOTE = re.compile(r"[（(][^）)]*[）)]")
TITLE = re.compile(r"副議長|議長|議員")
CJK = re.compile(r"[一-鿿]")

_last = 0.0


def _wait():
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)


def fetch(url):
    global _last
    _wait()
    try:
        return get(url)
    finally:
        _last = time.monotonic()


def post(path, form):
    """同主機的 POST（議事錄、影片查詢都是表單），和 fetch 共用間隔。"""
    global _last
    _wait()
    req = urllib.request.Request(HOST + path, data=urllib.parse.urlencode(form).encode(), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8")
    finally:
        _last = time.monotonic()


_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")  # 「113 年７月」；不用 NFKC，會把全形冒號、間隔號一起改掉


def norm(line):
    return re.sub(r"\s", "", line).translate(_DIGITS)


def pdf_url(file_id, page=None):
    return f"{HOST}/upfile/{file_id}.pdf" + (f"#page={page}" if page else "")


# ---------- 解析：議事錄清單 ----------

def parse_books(page):
    """meeting_book_search.php 結果 → [{title, date, id}]（頁面順序：新到舊），下冊不收。"""
    out = []
    for title, date, fid in BOOK.findall(page):
        title = re.sub(r"\s+", "", title)
        if "下冊" not in title and fid not in {b["id"] for b in out}:
            out.append({"title": title, "date": date, "id": fid})
    return out


# ---------- 解析：姓名 ----------

def split_names(text):
    """「張 峻、徐雪玉、…」→ ['張峻', '徐雪玉', …]：去空白、括號註記與職稱尾。"""
    out = []
    for tok in NAME_SPLIT.split(NOTE.sub("", norm(text))):
        tok = re.sub(r"(議員|副議長|議長)$", "", tok)
        if tok:
            out.append(tok)
    return out


def resolve_token(tok, roster):
    """名單上的一個詞 → [person_id]（可能是換行時黏在一起的兩個名字，例「徐子芳吳東昇」）或 (None, 原因)。

    先整詞對名錄；對不到時，只在「恰好有一種」切法能切成名錄上的全名時才收（寧缺勿掛錯）。"""
    pid, why = resolve(tok, roster)
    if pid:
        return [pid], None
    k = key(tok)
    names = {kk: ids[0] for kk, ids in roster.items() if len(ids) == 1}

    def cuts(s):
        if not s:
            return [[]]
        return [[names[s[:i]]] + rest for i in range(2, len(s) + 1) if s[:i] in names for rest in cuts(s[i:])]

    found = cuts(k)
    if len(found) == 1 and len(found[0]) > 1:
        return found[0], None
    return None, why


# ---------- 解析：大會會議紀錄 ----------

def roc(m):
    y, mo, d = m.groups()
    return f"{int(y) + 1911}-{int(mo):02d}-{int(d):02d}"


def parse_meetings(pages):
    """議事錄文字（依頁）→ [{session, meeting, page, date, present: [詞], leave: [詞]}]（大會才收，依出現順序）。

    出席／請假取「列席：」之前的名單；列席之後的「請假：」多是請假的縣府官員，只收帶議員職稱的詞（「魏議員嘉賢」）。"""
    out, session, cur, field, opened = [], None, None, None, False
    for pno, page in enumerate(pages, 1):
        for i, line in enumerate(page.split("\n")):
            s = norm(line)
            if not s or (i == 0 and PAGE_HEADER.match(s)):
                continue
            m = SESSION_HEAD.match(s)
            if m:
                session, cur, opened = f"第{TERM}屆第{m.group(1)}次{m.group(2)}大會", None, False
                continue
            m = MEETING_HEAD.match(s)
            if m:
                cur, field = None, None
                if m.group(1) == "一讀會":  # 一讀會是會期第一次會議：同一個會期標題下出現第二次，表示漏讀了新會期的標題
                    session, opened = (session, True) if session and not opened else (None, False)
                if session:
                    cur = {"session": session, "meeting": m.group(1), "page": pno, "date": None, "present": None, "leave": []}
                    out.append(cur)
                continue
            if "審查委員會" in s and s.endswith("會議紀錄"):  # 分組審查會議
                cur = None
                continue
            if cur is None:
                continue
            if cur["date"] is None and s.startswith("時間："):
                d = DATE.search(s)
                cur["date"] = roc(d) if d else None
                continue
            lab = LABEL.match(s)
            if lab:
                label, rest = lab.group(1), s[lab.end():]
                if label in ("主席", "紀錄") or (label == "出席" and cur["present"] is not None):
                    cur, field = None, None
                    continue
                if label == "出席":
                    cur["present"] = []
                # 列席之後的「請假：」多是縣府官員，偶爾也有議員（「魏議員嘉賢」），只收帶議員職稱的
                field = "late" if label == "請假" and field in ("列席", "late") else label
                s = rest
            if field == "出席":
                cur["present"] += split_names(s)
            elif field == "請假":
                cur["leave"] += split_names(s)
            elif field == "late":
                cur["leave"] += [TITLE.sub("", t) for t in NAME_SPLIT.split(NOTE.sub("", s)) if TITLE.search(t)]
    return [m for m in out if m["present"] is not None or m["leave"]]


# ---------- 解析：質詢答覆表 ----------

def _join(lines):
    out = ""
    for ln in (x.strip() for x in lines):
        if out and ln and out[-1].isascii() and out[-1].isalnum() and ln[0].isascii() and ln[0].isalnum():
            out += " "
        out += ln
    return out


def parse_questions(pages):
    """→ [{session, doc_type, names, dept, title, page, n}]；n 是同頁第幾格（從 0 起），和 page 一起當作穩定的編號。

    質詢人可能換行：第一行「質 詢 人：甲、 類 別：某處」後接「乙、丙」，或「質 詢 人：甲、乙、」換行後才接「丙 類 別：某處」。
    類別之後的續行：前面的姓名以「、」結尾就是姓名，否則是類別的續行。"""
    out, chapter, cur, part = [], None, None, None
    for pno, page in enumerate(pages, 1):
        n = 0
        for i, line in enumerate(page.split("\n")):
            s = norm(line)
            if not s or (i == 0 and PAGE_HEADER.match(s)):
                continue
            m = CHAPTER.match(s)
            if m:
                chapter = (f"第{TERM}屆第{m.group(1)}次定期大會", "口頭質詢答覆" if m.group(2) == "口頭" else "書面質詢")
                cur = part = None
                continue
            if chapter is None:
                continue
            # 頁緣裁掉「質」的格首（「詢 人：林源富 類 別：觀光處」）也要開新格，否則題目會併進上一位質詢人（verifier 2026-10-08）
            head = "質詢人：" if s.startswith("質詢人：") else "詢人：" if s.startswith("詢人：") and "類別：" in s else None
            if head:
                cur = {"session": chapter[0], "doc_type": chapter[1], "names": "", "dept": None, "q": [], "page": pno, "n": n}
                n += 1
                out.append(cur)
                part, s = "head", s[len(head):]
            elif cur is None:
                continue
            elif s.startswith("質詢事項："):
                part = "q"
                line = line.split("：", 1)[1]
            elif s.startswith(("答覆事項：", "答覆人：")):
                part = None
            if part == "head":
                if "類別：" in s:
                    before, after = s.split("類別：", 1)
                    cur["names"] += before
                    cur["dept"] = after
                elif cur["dept"] is not None and not cur["names"].endswith("、"):
                    cur["dept"] += s
                else:
                    cur["names"] += s
            elif part == "q":
                cur["q"].append(line)
    return [{**{k: v for k, v in q.items() if k != "q"}, "title": _join(q["q"]), "names": split_names(q["names"])} for q in out]


# ---------- 解析：議員質詢索引表 ----------

def parse_index(pages):
    """→ [{session, name, pages: [印刷頁碼], pdf_page}]。索引表每頁的第一行是頁首「議員質詢索引表 45」。"""
    out, session, cur = [], None, None
    for pno, page in enumerate(pages, 1):
        lines = [x for x in (norm(y).replace("-", "") for y in page.split("\n")) if x]
        if not lines or "議員質詢索引表" not in lines[0]:
            session = cur = None
            continue
        for s in lines[1:]:
            m = INDEX_HEAD.match(s)
            if m:
                session = f"第{TERM}屆第{m.group(1)}次定期大會"
                continue
            if session is None or s == "姓名頁碼":
                continue
            m = re.match(r"^([^\d、]+?)([\d、]*)$", s)
            if m and CJK.search(m.group(1)):
                if cur and not cur["pages"] and cur["name"].endswith("．"):  # 「哈尼．」換行接「噶照」
                    cur["name"] += m.group(1)
                else:
                    cur = {"session": session, "name": m.group(1), "pages": [], "pdf_page": pno}
                    out.append(cur)
                s = m.group(2)
            if cur and s and re.fullmatch(r"[\d、]+", s):
                cur["pages"] += [int(x) for x in s.split("、") if x]
    return out


# ---------- 第三人規則：不收的題目 ----------

def load_withheld(path=WITHHELD):
    """data/hua_withheld.csv：item（<檔名>:<PDF 頁>:<格>）、reason。"""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {r["item"]: r["reason"] for r in csv.DictReader(f)}


def item_id(file_id, q):
    return f"{file_id}:{q['page']}:{q['n']}"


# ---------- 快取 ----------

def load_index(refresh=True):
    path = CACHE / "books.html"
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(post("/meeting_book_search.php", {"sec_1": TERM, "keyword": "", "search": "y"}), encoding="utf-8")
    books = parse_books(path.read_text(encoding="utf-8"))
    if not books:
        raise ValueError("花蓮議事錄查詢找不到第 20 屆議事錄")
    return books


def book_pages(file_id, fetch_missing=True):
    """議事錄 PDF（以檔名快取；改版會換檔名）→ 依頁切開的文字；沒有快取且 fetch_missing=False 時回 None。"""
    txt = CACHE / "raw" / f"{file_id}.txt"
    if not txt.exists():
        pdf = CACHE / "pdf" / f"{file_id}.pdf"
        if not pdf.exists():
            if not fetch_missing:
                return None
            data = fetch(pdf_url(file_id))
            if not data.startswith(b"%PDF"):
                raise ValueError(f"花蓮議事錄不是 PDF：{file_id}")
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(data)
        txt.parent.mkdir(parents=True, exist_ok=True)
        txt.write_text(pdf_text(pdf.read_bytes(), "-raw"), encoding="utf-8")
    return txt.read_text(encoding="utf-8").split("\f")


# ---------- 組成紀錄 ----------

def collect(books, texts, roster, log=print):
    """→ (meetings, questions, index)：meetings 依 (會期, 會次) 去重，名單已對到 person_id。"""
    meetings, seen = [], {}
    questions, index = [], []
    for b in books:
        pages = texts.get(b["id"])
        if pages is None:
            log(f"hua_book：{b['title']} 未取得，不列入")
            continue
        for m in parse_meetings(pages):
            k = (m["session"], m["meeting"])
            if k in seen:
                if (seen[k]["present"], seen[k]["leave"]) != (m["present"], m["leave"]):
                    log(f"hua_book：{m['session']}{m['meeting']} 在兩冊的名單不同，用先出現的一冊")
                continue
            seen[k] = m
            if not m["present"]:
                log(f"hua_book：{m['session']}{m['meeting']}（{m['date']}）沒有出席名單，不列入")
                continue
            if not m["date"]:
                log(f"hua_book：{m['session']}{m['meeting']} 讀不到日期，不列入")
                continue
            lists = {}
            for label, toks in (("出席", m["present"]), ("請假", m["leave"])):
                ids = set()
                for t in toks:
                    pids, why = resolve_token(t, roster)
                    if pids:
                        ids.update(pids)
                    else:
                        log(f"hua_book：{m['session']} {label}名單 {t}：{why}")
                lists[label] = ids
            if lists["出席"] & lists["請假"]:
                log(f"hua_book：{m['session']}{m['meeting']} 同一人同時在出席與請假名單，不列入")
                continue
            meetings.append({**m, "file": b["id"], "present_ids": lists["出席"], "leave_ids": lists["請假"]})
        for q in parse_questions(pages):
            questions.append({**q, "file": b["id"]})
        for e in parse_index(pages):
            index.append({**e, "file": b["id"]})
    return meetings, questions, index


def session_starts(meetings):
    out = {}
    for m in meetings:
        out[m["session"]] = min(out.get(m["session"], m["date"]), m["date"])
    return out


def short(session):
    return session.replace(f"第{TERM}屆", "")


def attendance_facts(meetings, pids):
    """{person_id: [(fact_key, data, url, date)]}：每人每會期一筆。"""
    by_session = {}
    for m in meetings:
        by_session.setdefault(m["session"], []).append(m)
    out = {}
    for session, ms in by_session.items():
        slug = re.sub(r"\D+", "-", session.replace(f"第{TERM}屆", "")).strip("-") + ("r" if "定期" in session else "t")
        first = min(ms, key=lambda m: (m["date"], m["page"]))
        for pid in pids:
            data = {"term": TERM, "session": session, "title": f"{session}會議紀錄", "meetings": len(ms),
                    "present": sum(pid in m["present_ids"] for m in ms), "leave": sum(pid in m["leave_ids"] for m in ms),
                    "duty": 0, "from_lists": True}
            out.setdefault(pid, []).append((f"hlccattend:{slug}:{pid}", data, pdf_url(first["file"], first["page"]), first["date"]))
    return out


def question_facts(questions, roster, pids, starts, withheld, log=print):
    out, held = {}, []
    for q in questions:
        iid = item_id(q["file"], q)
        if iid in withheld:
            held.append((iid, q))
            continue
        if not q["title"] or not q["names"]:
            log(f"hua_book：{q['session']} {q['doc_type']} PDF 第 {q['page']} 頁第 {q['n'] + 1} 格讀不到質詢人或質詢事項，不收")
            continue
        ids = []
        for name in q["names"]:
            got, why = resolve_token(name, roster)
            if got:
                ids += got
            else:
                log(f"hua_book：{q['session']} {q['doc_type']} 質詢人 {name}：{why}（PDF 第 {q['page']} 頁）")
        data = {"term": TERM, "session": q["session"], "title": q["title"], "doc_type": q["doc_type"], "dept": q["dept"] or None,
                "councillors": q["names"], "page": q["page"], "no_date": True}
        for pid in dict.fromkeys(ids):
            if pid in pids:
                out.setdefault(pid, []).append((f"hlccq:{iid}:{pid}", data, pdf_url(q["file"], q["page"]), starts.get(q["session"])))
    return out, held


def transcript_facts(index, roster, pids, starts, log=print):
    out = {}
    for e in index:
        got, why = resolve_token(e["name"], roster)
        if not got or len(got) != 1:
            log(f"hua_book：{e['session']} 議員質詢索引表 {e['name']}：{why or '不是一個人'}")
            continue
        pid = got[0]
        if pid not in pids or not e["pages"]:
            continue
        ps = e["pages"]
        data = {"term": TERM, "session": e["session"], "doc_type": "質詢錄音紀錄", "no_date": True,
                "title": f"{short(e['session'])}質詢（錄音）紀錄：議員質詢索引表列 {len(ps)} 頁（議事錄第 {min(ps)}–{max(ps)} 頁）",
                "pages": ps, "index_page": e["pdf_page"]}
        out.setdefault(pid, []).append((f"hlcctr:{e['file']}:{pid}", data, pdf_url(e["file"], e["pdf_page"]), starts.get(e["session"])))
    return out


def write(conn, prefix, facts_by_pid, kind):
    """寫入並刪除同前綴、這次不在結果裡的舊 fact。回傳 (筆數, 刪除筆數)。"""
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE ?", (prefix + ":%",))}
    fetched_at = now_utc()
    current = set()
    for pid, facts in facts_by_pid.items():
        for k, data, url, date in facts:
            upsert_fact(conn, k, pid, kind, data, url, fetched_at, date=date)
            current.add(k)
    stale = known - current
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    return len(current), len(stale)


def build(conn, books, texts, withheld, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    pids = set()
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"hua_book：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        pids.add(pid)
    meetings, questions, index = collect(books, texts, roster, log)
    starts = session_starts(meetings)
    att = attendance_facts(meetings, pids)
    qs, held = question_facts(questions, roster, pids, starts, withheld, log)
    tr = transcript_facts(index, roster, pids, starts, log)
    return ts, meetings, att, qs, tr, held


def run(conn):
    books = load_index()
    texts = {b["id"]: book_pages(b["id"]) for b in books}
    logs = Counter()
    ts, meetings, att, qs, tr, held = build(conn, books, texts, load_withheld(), lambda s: logs.update([s]))
    for line, n in sorted(logs.items()):
        print(f"{line}（{n} 次）" if n > 1 else line)
    na, da = write(conn, "hlccattend", att, "attendance")
    nq, dq = write(conn, "hlccq", qs, "interpellation")
    nt, dt = write(conn, "hlcctr", tr, "interpellation")
    print(f"hua_book：議事錄 {len(books)} 冊、大會 {len(meetings)} 次；對象 {len(ts)} 人；出席 {len(att)} 人 {na} 筆（刪除 {da}）；"
          f"質詢答覆 {len(qs)} 人 {nq} 筆（刪除 {dq}，依第三人規則不收 {len(held)} 題）；錄音紀錄索引 {len(tr)} 人 {nt} 筆（刪除 {dt}）")


# ---------- 自我檢查 ----------

def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    books = load_index(refresh=False)
    texts = {b["id"]: book_pages(b["id"], fetch_missing=False) for b in books}
    logs = []
    ts, meetings, att, qs, tr, held = build(dump_conn(), books, texts, load_withheld(), logs.append)
    for line, n in sorted(Counter(logs).items()):
        print(" ", line, f"（{n} 次）" if n > 1 else "")
    sessions = Counter(m["session"] for m in meetings)
    print("會期：", sorted(sessions.items(), key=lambda x: min(m["date"] for m in meetings if m["session"] == x[0])))
    print(f"議事錄 {len(books)} 冊；大會 {len(meetings)} 次（{min(m['date'] for m in meetings)}～{max(m['date'] for m in meetings)}）")
    print(f"對象 {len(ts)} 人；出席 {len(att)} 人；質詢答覆 {len(qs)} 人 {sum(map(len, qs.values()))} 筆；"
          f"錄音紀錄 {len(tr)} 人 {sum(map(len, tr.values()))} 筆；不收 {len(held)} 題")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in [p for p in names if names[p] in samples]:
        print(f"\n{names[pid]}（{pid}）")
        for _, d, url, _ in att.get(pid, []):
            print(f"  出席 {d['session']:<16} {d['present']:>2}／{d['meetings']:<2}（請假 {d['leave']}） {url}")
        for _, d, url, date in qs.get(pid, [])[-6:]:
            print(f"  {d['doc_type']} {d['session']} {d['dept']}：{d['title'][:60]} {url}")
        for _, d, url, _ in tr.get(pid, []):
            print(f"  {d['title']} {url}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        for b in load_index():
            book_pages(b["id"])
            print(b["title"], flush=True)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
