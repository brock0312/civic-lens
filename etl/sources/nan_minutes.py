"""南投縣議會第 20 屆議事錄「各次會議紀錄」：縣政總質詢「聯合質詢」列名（V16 補洞）。

議事錄 PDF（和 nan_book 同一批，有文字層）的「各次會議紀錄」每次會議一頁：
「二、縣政總質詢　甲議員、乙議員…等 N 位議員聯合質詢」。nan_book 只收「議員建議事項」表，沒有提出建議的議員
（例如洪明科、戴世詮）在那邊是 0 筆，但官方會議紀錄明列他們參與該日的縣政總質詢。這裡補收「列名」：
每人每個開會日一筆，標「聯合質詢」並列出同場全部議員；質詢內容在議事錄的「質詢及答覆」，這裡只連到會議紀錄那一頁。

- 只收會議紀錄頁（頁面同時有「時間：中華民國 N 年 M 月 D 日」「出席：」與「縣政總質詢」）；「質詢及答覆」逐字稿頁不收。
- 名單到「等 N 位議員聯合質詢」為止；切出的姓名數必須等於 N，不符整頁不收（印 log）。
- 姓名以 etl.match 的漢字正規化整名對全部南投縣議員名錄，同名或對不到的不收；不做子字串比對。
- 會期取各冊目錄頁的「第二十屆第N次定期會議事錄」（頁面本身有時沒印會期）。
- 第 1–4 次定期會議事錄的版面另評估（nan_book 說明該幾冊的建議事項表是圖片）；這裡只處理有文字層的冊，沒文字層的頁印 log。
自我檢查：python3 -m etl.sources.nan_minutes [姓名…]（只讀快取與 data/civic.sql；PDF 不在快取時用 --fetch，只抓議事錄 PDF）
"""
import re
import subprocess
import sys
import unicodedata
from collections import Counter

from etl.sources import nan_book
from etl.sources.hua_book import resolve_token, write
from etl.sources.nwt_book import resolve, roster_index, targets

OFFICE = nan_book.OFFICE
TERM = nan_book.TERM
DOC_TYPE = "縣政總質詢會議紀錄列名"
CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

TOC = re.compile(r"南投縣議會第(?:二十|20)屆第([一二三四五六七八九十\d]+)次(定期|臨時)會議事錄")
WHEN = re.compile(r"時間:中華民國(\d+)年(\d+)月(\d+)日")
MEETING = re.compile(r"第(\d+)次會議")
NAME = re.compile(r"([一-鿿]{2,4})[A-Za-z‧·.\-]*")  # 原住民姓名後面接羅馬拼音（空白已去掉）
ASKERS = re.compile(r"縣政總質詢[:：]?(?:\([一二三四五六七八九十\d]+\))?(.*?)等(\d+)位議員聯合質詢", re.S)


def flat(s):
    """NFKC 並去掉空白（全形標點變半形）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", nan_book.compat(s)))


def session_number(s):
    return CN[s] if s in CN else int(s)


def book_session(first_page):
    m = TOC.search(flat(first_page))
    if not m:
        return None
    return f"第{TERM}屆第{session_number(m.group(1))}次{m.group(2)}會"


def pdf_pages(pdf):
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, check=True).stdout.decode("utf-8", "ignore")
    return out.split("\f")


def parse_pages(pages, log=print):
    """→ [{page, date, meeting, names}]（會議紀錄頁的縣政總質詢列名）。"""
    out = []
    for pno, text in enumerate(pages, 1):
        f = flat(text)
        w = WHEN.search(f)
        if not (w and "縣政總質詢" in f and "出席:" in f and MEETING.search(f)):
            continue
        m = ASKERS.search(f[f.index("縣政總質詢"):])
        # 同日分兩段時（「(一)甲、乙…等 7 位議員聯合質詢。(二)丙議員質詢。」）只取聯合質詢那段；ASKERS 非貪婪，取到第一個「聯合質詢」
        date = f"{int(w.group(1)) + 1911}-{int(w.group(2)):02d}-{int(w.group(3)):02d}"
        if not m:
            log(f"nan_minutes：{date}（PDF 第 {pno} 頁）縣政總質詢沒有「等 N 位議員聯合質詢」格式，不收")
            continue
        # 換行處官方沒有頓號（「石慶龍議員全文才議員」），有的頁沒寫「議員」，所以頓號與「議員」都當分隔
        toks = [t for t in re.split(r"議員|[、,，;；]", m.group(1)) if t]
        names = [m_.group(1) for t in toks if (m_ := NAME.fullmatch(t))]
        if len(names) != len(toks) or len(names) != int(m.group(2)):
            log(f"nan_minutes：{date}（PDF 第 {pno} 頁）姓名 {len(names)}／{len(toks)} 個與宣告 {m.group(2)} 位對不上，整頁不收")
            continue
        out.append({"page": pno, "date": date, "meeting": int(MEETING.search(f).group(1)), "names": names})
    return out


def book_days(book, fetch_missing=True, log=print):
    pdf = nan_book.book_pdf(book["id"], fetch_missing)
    if pdf is None:
        return None, None
    pages = pdf_pages(pdf)
    session = book_session(pages[0])
    if not session:
        log(f"nan_minutes：{book['id']} 目錄頁讀不到會期，整冊不收")
        return None, None
    days = parse_pages(pages, log)
    if not days:
        log(f"nan_minutes：{session}（{book['id']}）沒有讀到任何會議紀錄頁（可能是掃描影像）")
    return session, days


def facts(books, roster, pids, fetch_missing=True, log=print):
    out, ndays = {}, 0
    name_of = {ids[0]: k for k, ids in roster.items() if len(ids) == 1}
    for b in books:
        session, days = book_days(b, fetch_missing, log)
        for d in days or []:
            ndays += 1
            ids, listed = [], []
            for n in d["names"]:
                got, why = resolve_token(n, roster)
                if not got:
                    log(f"nan_minutes：{session} {d['date']} 議員 {n}：{why}，不收")
                    listed.append(n)
                    continue
                ids += got
                listed += [name_of[p] for p in got] if len(got) > 1 else [n]
            title = "縣政總質詢（會議紀錄列為聯合質詢議員）；同場列名：" + "、".join(listed)
            data = {"term": TERM, "session": session, "meeting": f"第{d['meeting']}次會議", "doc_type": DOC_TYPE,
                    "dept": None, "title": title, "councillors": listed, "group_size": len(listed), "page": d["page"]}
            for pid in dict.fromkeys(ids):
                if pid in pids:
                    out.setdefault(pid, []).append((f"ntccmin:{b['id']}:{d['page']}:{pid}", data,
                                                   nan_book.pdf_url(b["id"], d["page"]), d["date"]))
    return out, ndays


def books_from_dump(conn):
    """議事錄清單頁壞掉時的備援：用已上線的建議事項 fact 的 PDF 檔名（ntccq:<檔名>:…）。"""
    ids = {r[0].split(":")[1] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'ntccq:%'")}
    return [{"id": i, "title": i, "kind": ""} for i in sorted(ids)]


def load(conn, refresh):
    try:
        return nan_book.load_books(refresh=refresh)
    except Exception as e:  # 清單頁壞掉或沒快取
        print(f"nan_minutes：議事錄清單讀不到（{e}），改用已收錄建議事項的 PDF 清單")
        return books_from_dump(conn)


def build(conn, books, fetch_missing, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    pids = set()
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"nan_minutes：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        pids.add(pid)
    by_pid, ndays = facts(books, roster, pids, fetch_missing, log)
    return ts, by_pid, ndays


def run(conn):
    logs = Counter()
    books = load(conn, refresh=True)
    ts, by_pid, ndays = build(conn, books, True, lambda s: logs.update([s]))
    for line, k in sorted(logs.items()):
        print(f"{line}（{k} 次）" if k > 1 else line)
    n, stale = write(conn, "ntccmin", by_pid, "interpellation")
    print(f"nan_minutes：議事錄 {len(books)} 冊，{ndays} 個列名開會日；對象 {len(ts)} 人，有紀錄 {len(by_pid)} 人 {n} 筆（刪除 {stale}）")


def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    conn = dump_conn()
    books = load(conn, refresh=False)
    logs = []
    ts, by_pid, ndays = build(conn, books, False, logs.append)
    for line, k in sorted(Counter(logs).items()):
        print(" ", line, f"（{k} 次）" if k > 1 else "")
    print(f"議事錄 {len(books)} 冊，{ndays} 個列名開會日；對象 {len(ts)} 人，有紀錄 {len(by_pid)} 人 {sum(map(len, by_pid.values()))} 筆")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in sorted(names, key=lambda p: -len(by_pid.get(p, []))):
        print(f"  {names[pid]}：{len(by_pid.get(pid, []))}")
    for pid in [p for p in names if any(s in names[p] for s in samples)]:
        print(f"\n{names[pid]}（{pid}）")
        for _, d, url, date in by_pid.get(pid, []):
            print(f"  {date} {d['session']}{d['meeting']} 同場 {d['group_size']} 人 {url}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        from etl.sources.nwt_book import dump_conn
        for b in load(dump_conn(), refresh=False):
            nan_book.book_pdf(b["id"])
            print(b["id"], flush=True)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
