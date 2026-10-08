"""臺東縣議會第 20 屆議事錄（www.taitungcc.gov.tw/1/meeting）：大會出缺勤與書面質詢（V16）。

議事錄每個定期會 4 冊 PDF（有文字層，每冊 30–40 MB，主機只能用 IPv4 連）：第一冊臨時會、第二冊定期會、第三冊單位工作檢討、
第四冊縣政總質詢。冊別依議事錄頁的連結文字判斷（第 1 次定期會的 01.pdf、02.pdf 對調）。第三冊不讀。

- 出缺勤：第一、二冊每次會議紀錄（「預備會會議紀錄」「第 N 會次會議紀錄」）列「出席：」「請假：」名單（「列席：」之前）。
  兩份名單都沒有的人原因不明，不另列缺席（比照新北、花蓮）。分母是本站收錄、會議紀錄列有出席名單的會議次數。
  每人每會期（定期會、臨時會）一筆 fact。同一次會議同一人同時在出席與請假名單、或名單上有對不到名錄的詞時，該次會議不收（印 log）。
- 書面質詢：第四冊議員改以書面質詢時，每題標「<議員>書面質詢事項X：題目」，後附主辦單位答復。題目照官方原文全文
  （V16 已定案第 6 點、使用者 2026-10-08 決定不截斷），連到 PDF 該頁。第三人規則（HANDOFF §3 第 5 條）：
  data/ttt_withheld.csv 列出的題目不收。
- 口頭質詢逐字紀錄：第四冊沒有逐人索引表，不做；YouTube 頻道官網未連結，不採用（V16 已定案第 3 點）。

只寫給有臺東縣議員任職 fact 且有 2026 candidacy 的人；姓名以 etl.match 的漢字正規化對全部臺東縣議員名錄，
名錄同名或對不到的不收（印 log）。
自我檢查：python3 -m etl.sources.ttt_book [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import csv
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from etl.fetch import get
from etl.sources.hsz_book import download
from etl.sources.hua_book import _join, write
from etl.sources.nwt_book import TITLE_AFTER, TITLE_INSIDE, resolve, roster_index, targets

HOST = "https://www.taitungcc.gov.tw"
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "ttt_book"
WITHHELD = ROOT / "data" / "ttt_withheld.csv"
OFFICE = "ttt_councilor"
TERM = 20
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔（robots.txt 全部允許，V16）
SEATS = 30  # 第 20 屆議員席次：每次會議出席＋請假名單合計不應超過

LINK = re.compile(r'<a href="(/img/download/meeting/meeting20_(\d\d)/(\d\d)\.pdf)"[^>]*>\s*([^<]*?)\s*</a>')
# 以下都比對「去掉空白」後的行
SESSION_HEAD = re.compile(r"^第20屆第(\d+)次(定期會|臨時會)會議紀錄$")
MEETING_HEAD = re.compile(r"^(預備會|第\d+會次)會議紀錄([（(].*)?$")  # 會勘的會次在標題後括號註記地點
LABEL = re.compile(r"^(出席|請假|列席|縣府|地點|本會|來賓|主席|記錄|紀錄|時間)：")
DATE = re.compile(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日")
# 頁首頁尾：頁碼「-5-」、欄目名稱、會期名稱、「質詢」；名單跨頁時要跳過，否則會黏進姓名
FURNITURE = re.compile(r"^(-?\d+-?|議事日程表、.*|(臺東縣議會)?第20屆第[\d、]+次(定期會|臨時會).*|質詢)$")
NOTE = re.compile(r"[（(][^）)]*[）)]")
NAME = re.compile(r"^[一-鿿]{2,5}$")
Q_HEAD = re.compile(r"^(?:臺東縣議會第20屆第\d+次定期會)?([一-鿿]{2,8}?)書面質詢事項([一二三四五六七八九十]+)[：:]?(.*)$")
ANSWER = re.compile(r"^依(.+?)\d{2,3}年\d{1,2}月\d{1,2}日.*字第")

_last = 0.0


def _wait():
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()


# ---------- 議事錄清單 ----------

def parse_books(page):
    """議事錄頁 → [{id, path, kind, title}]，kind：temp（臨時會）、regular（定期會）、questions（縣政總質詢）；工作檢討不收。
    第 20 屆有不認得的連結文字時 raise（不猜冊別）。"""
    out = []
    for path, n, vol, title in LINK.findall(page):
        title = re.sub(r"\s+", "", title)
        if "檢討" in title:
            continue
        kind = "questions" if "總質詢" in title else "temp" if "臨時會" in title else "regular" if "定期會" in title else None
        if kind is None:
            raise ValueError(f"臺東議事錄連結文字未知：{title} {path}")
        out.append({"id": f"{n}-{vol}", "path": path, "kind": kind, "title": title})
    return out


def load_books(refresh=True):
    path = CACHE / "meeting.html"
    if refresh or not path.exists():
        _wait()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(HOST + "/1/meeting", ipv4=True))
    books = parse_books(path.read_text(encoding="utf-8"))
    if not books:
        raise ValueError("臺東議事錄頁找不到第 20 屆議事錄")
    return books


def pdf_url(book, page=None):
    return HOST + book["path"] + (f"#page={page}" if page else "")


def book_pages(book, fetch_missing=True):
    """議事錄 PDF（以會期與冊號快取）→ 依頁切開的文字（pdftotext -layout）；沒有快取且 fetch_missing=False 時回 None。"""
    txt = CACHE / "raw" / f"{book['id']}.txt"
    if not txt.exists():
        pdf = CACHE / "pdf" / f"{book['id']}.pdf"
        if not pdf.exists():
            if not fetch_missing:
                return None
            _wait()
            download(pdf_url(book), pdf, ipv4=True)
            data = pdf.read_bytes()
            if data[:4] != b"%PDF" or b"%%EOF" not in data[-1024:]:  # 回應沒有 Content-Length，只能看檔頭檔尾判斷是否完整
                pdf.unlink()
                raise ValueError(f"臺東議事錄不是完整的 PDF：{book['title']}")
        out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, check=True).stdout.decode("utf-8")
        txt.parent.mkdir(parents=True, exist_ok=True)
        txt.write_text(out, encoding="utf-8")
    return txt.read_text(encoding="utf-8").split("\f")


def norm(line):
    return re.sub(r"\s", "", line)


def clean(line):
    """保留英數詞之間的一個空白（「Slow for Life」），其餘空白都去掉（中文排版的空白）。"""
    return re.sub(r"(?<![A-Za-z0-9]) | (?![A-Za-z0-9])", "", re.sub(r"\s+", " ", line.strip()))


def roc(m):
    y, mo, d = m.groups()
    return f"{int(y) + 1911}-{int(mo):02d}-{int(d):02d}"


# ---------- 會議紀錄：出席、請假名單 ----------

def split_names(text):
    """「吳秀華、林琮翰(出差)、楊秋珍」→ ['吳秀華', '林琮翰', '楊秋珍']；「無」不算。"""
    return [t for t in NOTE.sub("", text).split("、") if t and t != "無"]


def parse_meetings(pages):
    """議事錄文字（依頁）→ [{session, meeting, page, date, present: [詞] 或 None, leave: [詞]}]（依出現順序）。

    名單換行時姓名可能被切開（「楊秋」接「珍」），所以續行直接接上再以「、」切開；名單只到下一個標籤（列席、地點…）。"""
    out, session, cur, field = [], None, None, None
    for pno, page in enumerate(pages, 1):
        for line in page.split("\n"):
            s = norm(line)
            if not s:
                continue
            m = SESSION_HEAD.match(s)
            if m:
                session, cur, field = f"第{TERM}屆第{m.group(1)}次{m.group(2)}", None, None
                continue
            m = MEETING_HEAD.match(s)
            if m:
                field = None
                cur = {"session": session, "meeting": m.group(1), "page": pno, "date": None, "present": None, "leave": "",
                       "leave_listed": False}
                if session:
                    out.append(cur)
                continue
            if cur is None or FURNITURE.match(s):
                continue
            lab = LABEL.match(s)
            if lab:
                field, s = lab.group(1), s[lab.end():]
                if field == "時間" and cur["date"] is None:
                    d = DATE.search(s)
                    cur["date"] = roc(d) if d else None
                if field == "請假":
                    cur["leave_listed"] = True
                if field == "出席":
                    if cur["present"] is not None:  # 同一次會議出現第二份出席名單：格式不明，整次不收
                        cur["bad"] = True
                    cur["present"] = ""
            if field == "出席":
                cur["present"] += s
            elif field == "請假":
                cur["leave"] += s
            elif field in ("主席", "記錄", "紀錄"):
                cur = None
    return [{**m, "present": split_names(m["present"]) if m["present"] is not None else None, "leave": split_names(m["leave"])}
            for m in out]


# ---------- 第四冊：書面質詢 ----------

def cn(s):
    """一～九十九 → int。"""
    d = {c: i for i, c in enumerate("一二三四五六七八九", 1)}
    if "十" not in s:
        return d[s]
    a, b = s.split("十")
    return (d[a] if a else 1) * 10 + (d[b] if b else 0)


def asker(name):
    """「林副議長琮翰」「張全議員馨嵐」「林琮翰議員」→ 全名；認不出職稱回原字串（對名錄時會對不到而不收）。"""
    m = TITLE_INSIDE.match(name)
    if m:
        return m.group(1) + m.group(2)
    return TITLE_AFTER.sub("", name)


def parse_questions(pages):
    """→ [{name, no, title, dept, page, bad}]：每題從「<議員>書面質詢事項X」到答復的第一行（「依<單位><日期>…字第…號函」）。

    質詢文字原文照收（去掉換行與頁首頁尾）；dept 是答復的縣府單位。bad 是不收的原因：
    沒有讀到答復行、或同一位議員的編號不連續（頁緣裁掉題首時，上一題會吞掉下一題，花蓮的教訓）。"""
    out, cur = [], None
    for pno, page in enumerate(pages, 1):
        for line in page.split("\n"):
            s = clean(line)
            if not s:
                continue
            m = Q_HEAD.match(s)
            if m:
                cur = {"name": asker(m.group(1)), "no": cn(m.group(2)), "q": [m.group(3)], "dept": None, "page": pno, "bad": None}
                out.append(cur)
                continue
            if cur is None or cur["dept"] is not None or FURNITURE.match(norm(s)):
                continue
            a = ANSWER.match(s)
            if a:
                cur["dept"] = a.group(1)
            else:
                cur["q"].append(s)
    prev = {}
    for i, q in enumerate(out):
        q["title"] = _join(q.pop("q"))
        if q["dept"] is None:
            q["bad"] = "讀不到答復"
        if q["no"] != prev.get(q["name"], 0) + 1:
            q["bad"] = q["bad"] or f"編號不連續（前一題 {prev.get(q['name'], 0)}）"
            if i and out[i - 1]["name"] == q["name"]:
                out[i - 1]["bad"] = out[i - 1]["bad"] or f"下一題編號不連續（{q['no']}）"
        prev[q["name"]] = q["no"]
    return out


# ---------- 第三人規則：不收的題目 ----------

def load_withheld(path=WITHHELD):
    """data/ttt_withheld.csv：item（<冊>:<PDF 頁>:<題號>）、reason。"""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {r["item"]: r["reason"] for r in csv.DictReader(f)}


def item_id(book_id, q):
    return f"{book_id}:{q['page']}:{q['no']}"


# ---------- 組成紀錄 ----------

def check_meeting(m, roster):
    """→ (出席 ids, 請假 ids, 對不到名錄的詞) 或 None 與不收的原因。"""
    if m["present"] is None:
        return None, "沒有出席名單"
    if m.get("bad"):
        return None, "出現兩份出席名單"
    if not m["date"]:
        return None, "讀不到日期"
    odd = [t for t in m["present"] + m["leave"] if not NAME.match(t)]
    if odd:  # 頁首頁尾或其他文字黏進名單：整次不收，不猜
        return None, f"名單有不是姓名的詞 {odd[:3]}"
    if len(m["present"]) + len(m["leave"]) > SEATS:
        return None, f"名單 {len(m['present']) + len(m['leave'])} 人，超過 {SEATS} 席"
    lists, unknown = {}, []
    for label in ("present", "leave"):
        ids = []
        for t in m[label]:
            pid, why = resolve(t, roster)
            if pid:
                ids.append(pid)
            else:
                unknown.append(f"{t}（{why}）")
        if len(set(ids)) != len(ids):
            return None, "同一人在名單上出現兩次"
        lists[label] = set(ids)
    if lists["present"] & lists["leave"]:
        return None, "同一人同時在出席與請假名單"
    return (lists["present"], lists["leave"], unknown), None


def collect(books, texts, roster, log=print):
    """→ (meetings, questions)：meetings 依 (會期, 會次) 去重，名單已對到 person_id；questions 附冊別與會期。"""
    meetings, seen, questions = [], {}, []
    for b in sorted(books, key=lambda b: (b["id"][:2], b["kind"] != "regular")):  # 同一會期刊在兩冊時連到第二冊（定期會）
        pages = texts.get(b["id"])
        if pages is None:
            log(f"ttt_book：{b['title']} 未取得，不列入")
            continue
        if b["kind"] == "questions":
            session = f"第{TERM}屆第{int(b['id'][:2])}次定期會"
            heads = Counter(re.findall(rf"第{TERM}屆第\d+次定期會", norm("".join(pages))))
            if not heads or heads.most_common(1)[0][0] != session:  # 第 2 次定期會的第四冊其實是第 1 次的內容（2026-10 實測）
                log(f"ttt_book：{b['title']} 頁首是 {heads.most_common(1)[0][0] if heads else '（無）'}，和冊名不符，不收")
                continue
            questions += [{**q, "session": session, "book": b} for q in parse_questions(pages)]
            continue
        for m in parse_meetings(pages):
            k = (m["session"], m["meeting"])
            if k in seen:  # 第 2 次定期會的會議紀錄同時刊在第一、二冊
                if (seen[k]["present"], seen[k]["leave"]) != (m["present"], m["leave"]):
                    log(f"ttt_book：{m['session']}{m['meeting']} 在兩冊的名單不同（{b['title']}），用先出現的一份")
                continue
            seen[k] = m
            got, why = check_meeting(m, roster)
            if not got:
                log(f"ttt_book：{m['session']}{m['meeting']}（{b['title']} PDF 第 {m['page']} 頁）{why}，不列入")
                continue
            present, leave, unknown = got
            for u in unknown:
                log(f"ttt_book：{m['session']} 名單 {u}")
            if len(m["present"]) + len(m["leave"]) != SEATS:
                log(f"ttt_book：{m['session']}{m['meeting']} 出席 {len(m['present'])}＋請假 {len(m['leave'])} 人，不是 {SEATS} 席（照收）")
            meetings.append({**m, "book": b, "present_ids": present, "leave_ids": leave})
    return meetings, questions


def session_starts(meetings):
    """會期 → 文件中第一次會議的日期（不取最早日期：會議紀錄偶有年份誤植，例：第 7 次定期會第 8 會次寫 114 年）。"""
    out = {}
    for m in meetings:
        out.setdefault(m["session"], m)
    return out


def attendance_facts(meetings, pids):
    """{person_id: [(fact_key, data, url, date)]}：每人每會期一筆。"""
    by_session = {}
    for m in meetings:
        by_session.setdefault(m["session"], []).append(m)
    first = session_starts(meetings)
    out = {}
    for session, ms in by_session.items():
        # 第 1、2 次定期會與第 1–6 次臨時會的會議紀錄都沒有請假名單：請假次數不明，寫 None（不是 0）
        listed = any(m["leave_listed"] for m in ms)
        slug = re.sub(r"\D+", "-", session.replace(f"第{TERM}屆", "")).strip("-") + ("r" if "定期" in session else "t")
        f = first[session]
        for pid in pids:
            data = {"term": TERM, "session": session, "title": f"{session}會議紀錄", "meetings": len(ms),
                    "present": sum(pid in m["present_ids"] for m in ms),
                    "leave": sum(pid in m["leave_ids"] for m in ms) if listed else None,
                    "duty": 0, "from_lists": True}
            out.setdefault(pid, []).append((f"tttattend:{slug}:{pid}", data, pdf_url(f["book"], f["page"]), f["date"]))
    return out


def question_facts(questions, roster, pids, starts, withheld, log=print):
    out, held = {}, []
    for q in questions:
        iid = item_id(q["book"]["id"], q)
        if iid in withheld:
            held.append((iid, q))
            continue
        if q["bad"] or not q["title"]:
            log(f"ttt_book：{q['session']} {q['name']}書面質詢事項{q['no']}（PDF 第 {q['page']} 頁）{q['bad'] or '沒有題目'}，不收")
            continue
        pid, why = resolve(q["name"], roster)
        if not pid:
            log(f"ttt_book：{q['session']} 書面質詢 {q['name']}：{why}（PDF 第 {q['page']} 頁）")
            continue
        if pid not in pids:
            continue
        data = {"term": TERM, "session": q["session"], "title": q["title"], "doc_type": "書面質詢",
                "dept": q["dept"].rstrip("，、,及") or None, "councillors": [q["name"]], "page": q["page"], "no_date": True}
        start = starts.get(q["session"])
        out.setdefault(pid, []).append((f"tttq:{iid}:{pid}", data, pdf_url(q["book"], q["page"]), start and start["date"]))
    return out, held


def build(conn, books, texts, withheld, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    pids = set()
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"ttt_book：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        pids.add(pid)
    meetings, questions = collect(books, texts, roster, log)
    full = {}
    for m in meetings:
        full[m["session"]] = max(full.get(m["session"], 0), len(m["present"]) + len(m["leave"]))
    for m in meetings:
        if not m["leave_listed"] and any(x["leave_listed"] for x in meetings if x["session"] == m["session"]) \
                and len(m["present"]) != full[m["session"]]:
            log(f"ttt_book：{m['session']}{m['meeting']} 沒有請假名單，出席 {len(m['present'])} 人少於該會期的 {full[m['session']]} 人（照收）")
    att = attendance_facts(meetings, pids)
    qs, held = question_facts(questions, roster, pids, session_starts(meetings), withheld, log)
    return ts, meetings, questions, att, qs, held


def run(conn):
    books = load_books()
    texts = {b["id"]: book_pages(b) for b in books}
    logs = Counter()
    ts, meetings, questions, att, qs, held = build(conn, books, texts, load_withheld(), lambda s: logs.update([s]))
    for line, n in sorted(logs.items()):
        print(f"{line}（{n} 次）" if n > 1 else line)
    na, da = write(conn, "tttattend", att, "attendance")
    nq, dq = write(conn, "tttq", qs, "interpellation")
    print(f"ttt_book：議事錄 {len(books)} 冊、會議 {len(meetings)} 次；對象 {len(ts)} 人；出缺勤 {len(att)} 人 {na} 筆（刪除 {da}）；"
          f"書面質詢 {len(questions)} 題，{len(qs)} 人 {nq} 筆（刪除 {dq}，依第三人規則不收 {len(held)} 題）")


# ---------- 自我檢查 ----------

def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    books = load_books(refresh=False)
    texts = {b["id"]: book_pages(b, fetch_missing=False) for b in books}
    logs = []
    ts, meetings, questions, att, qs, held = build(dump_conn(), books, texts, load_withheld(), logs.append)
    for line, n in sorted(Counter(logs).items()):
        print(" ", line, f"（{n} 次）" if n > 1 else "")
    sessions = Counter(m["session"] for m in meetings)
    print("會期：", sorted(sessions.items(), key=lambda x: session_starts(meetings)[x[0]]["date"]))
    print(f"議事錄 {len(books)} 冊；會議 {len(meetings)} 次（{min(m['date'] for m in meetings)}～{max(m['date'] for m in meetings)}）")
    print(f"對象 {len(ts)} 人；出缺勤 {len(att)} 人；書面質詢 {len(questions)} 題，{len(qs)} 人 {sum(map(len, qs.values()))} 筆；"
          f"不收 {len(held)} 題")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in [p for p in names if any(s in names[p] for s in samples)]:
        print(f"\n{names[pid]}（{pid}）")
        for _, d, url, date in sorted(att.get(pid, []), key=lambda x: x[3]):
            print(f"  出席 {d['session']:<14} {date} {d['present']:>2}／{d['meetings']:<2}（請假 {d['leave']}） {url}")
        for _, d, url, _ in qs.get(pid, []):
            print(f"  書面質詢 {d['session']} {d['dept']}：{d['title'][:60]} {url}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        for b in load_books():
            book_pages(b)
            print(b["title"], flush=True)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
