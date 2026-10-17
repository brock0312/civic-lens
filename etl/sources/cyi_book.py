"""嘉義市議會第 11 屆（www.cycc.gov.tw「本屆議事錄」listAnnounce.aspx?c0=4769）：逐人市政總質詢頁碼連結與出缺席合計（V16）。

V16 已定案第 12 點：2026-10-17 使用者放寬 `www.cycc.gov.tw/_admin/` 下的議事錄附件（含為取得清單所需的頁面）；影片仍跳過。
議事錄每個定期會一冊或上下兩冊（第 3 次定期會詳細頁「無相關資料」，第 7 次只有下冊），PDF 有文字層（pdftotext -layout，每頁 \\f）。

- 市政總質詢：「口頭質詢及答覆」章（頁首「口頭質詢及答覆 1107」或「1108 口頭質詢及答覆」，數字是印刷頁），每場以
  「第 N 次會議市政總質詢及答覆」＋「115.04.30」開頭，發言標籤「議員黃盈智質詢：」（議長、副議長寫「副議長張榮藏質詢：」）。
  每場的標題要和該章目錄「（6）第 14 次會議市政總質詢及答覆（115 年 5 月 8 日）……1338」的次數、日期、印刷頁都相符，
  否則整場不收（印 log）。一位議員在一場裡可能有好幾段（在別人時間插話、共用時間），取本人連續發言（中間只有官員答覆）
  字數最多的一段當本人質詢，連到該段第一個標籤所在的 PDF 頁（#page=N，N 是 PDF 頁序；印刷頁與 PDF 頁差距不固定，所以標題寫頁首的印刷頁）。
  該段不到 MIN_CHARS 字的（共用時間只說一句、插話）不收。只放標題與 PDF 頁連結，不擷取內文（V16 已定案第 6 點）。
- 出缺席：附錄「議員出、缺席一覽表」每個會期一張「嘉義市議會第11屆第7次定期會議員出席表」：姓名直排、每人一欄。只用最下面
  「合計 出席／請假」兩列（逐日的列和合計對不上，不用）。用 pdftotext -bbox 依 x 座標把直排的字組成姓名、把合計數字對到欄；
  欄數、數字個數不符、各欄「出席＋請假」不相同（合計列有誤），或任何一欄姓名對不到名錄，
  整張表不收（印 log）；早期的表請假 0 次留白，當作 0（之後仍要通過前一項檢查）。每人每會期一筆：
  出席 N、請假 M（meetings＝N＋M），日期取表上第一個日期（只作排序）。
- 姓名以 etl.match 的漢字正規化對全部嘉義市議員任職（中選會 2022 當選人，basis=cec_2022）；同名或對不到的不收。
  官方錯字只照 NAME_FIX、改名只照 LABEL_ALIAS（逐鍵、附證據）更正。只寫給有嘉義市議員任職 fact 且有 2026 candidacy 的人。

UA civic-lens-etl/0.1、同主機間隔 ≥ 1.1 秒、循序。PDF 共約 2.6 GB，抓取與建檔分開：
  python3 -m etl.sources.cyi_book --fetch   更新清單與詳細頁，下載快取裡還沒有的 PDF（data/cache/cyi/pdf/<p0>/<檔名>）
  run(conn)（etl.run）只讀快取，不連網；清單上有附件但快取沒有 PDF 的就整批不寫（避免把舊 fact 當成過期刪掉）。
自我檢查：python3 -m etl.sources.cyi_book [姓名…]（只讀快取與 data/civic.sql，不寫 DB）
"""
import html
import re
import subprocess
import sys
import time
import urllib.parse
from collections import Counter
from pathlib import Path

from etl.fetch import UA, get
from etl.sources.hua_book import write
from etl.sources.kin_book import GOV_DOC
from etl.sources.nwt_book import resolve, roster_index, targets

HOST = "https://www.cycc.gov.tw/"
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "cyi"
LIST_URL = HOST + "web/AnnF/listAnnounce.aspx?c0=4769"
DETAIL_URL = HOST + "web/AnnF/uptAnnounce.aspx?c0=4769&p0={}"
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔，所有請求（含 PDF）循序
OFFICE = "cyi_councilor"
TERM = 11
MIN_CHARS = 200  # 本人質詢段落字數下限：共用時間只說一句、在別人時間插話的不算一場質詢

LIST_ITEM = re.compile(r"href='uptAnnounce\.aspx\?c0=4769&p0=(\d+)'>([^<]*)")
ATTACH = re.compile(r"href='/(_admin/_upload/Announce/(\d+)/file/([^']+\.pdf))'")

_last = 0.0


def _wait():
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)


def _done():
    global _last
    _last = time.monotonic()


def fetch(url):
    _wait()
    try:
        return get(url)
    finally:
        _done()


def parse_list(page):
    """本屆議事錄清單 → [(p0, 標題)]。"""
    return [(int(p0), html.unescape(t).strip()) for p0, t in LIST_ITEM.findall(page)]


def parse_detail(page):
    """詳細頁 → [(附件路徑, 檔名)]（去重、依頁面順序）；「無相關資料」回 []。"""
    out = []
    for rel, _, name in ATTACH.findall(page):
        if (rel, name) not in out:
            out.append((rel, html.unescape(name)))
    return out


def pdf_path(p0, name):
    return CACHE / "pdf" / str(p0) / name


def file_url(rel):
    return HOST + urllib.parse.quote(rel)


def fetch_all():
    """更新清單與詳細頁，循序下載快取裡還沒有的 PDF（curl 直接寫檔，不佔記憶體；可續跑）。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "list.html").write_bytes(fetch(LIST_URL))
    items = parse_list((CACHE / "list.html").read_text(encoding="utf-8"))
    print(f"cyi_book：清單 {len(items)} 筆", flush=True)
    for p0, title in items:
        (CACHE / f"annf_{p0}.html").write_bytes(fetch(DETAIL_URL.format(p0)))
    for p0, title in items:
        files = parse_detail((CACHE / f"annf_{p0}.html").read_text(encoding="utf-8"))
        if not files:
            print(f"cyi_book：{p0} {title} 沒有附件", flush=True)
        for rel, name in files:
            out = pdf_path(p0, name)
            if out.exists():
                print(f"cyi_book：已有 {p0}/{name}", flush=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            part = out.with_name(out.name + ".part")
            _wait()
            t0 = time.monotonic()
            try:
                subprocess.run(["curl", "-sS", "-f", "--max-time", "3600", "-A", UA, "-o", str(part), file_url(rel)], check=True)
            finally:
                _done()
            with part.open("rb") as f:
                magic = f.read(4)
            if magic != b"%PDF":
                raise ValueError(f"嘉義市議事錄不是 PDF：{rel}")
            part.rename(out)
            print(f"cyi_book：下載 {p0}/{name} {out.stat().st_size:,} B，{time.monotonic() - t0:.0f} 秒", flush=True)


# ---------- 議事錄文字 ----------

def book_text(p0, name):
    """PDF → pdftotext -layout 文字（快取 .txt）；沒有 PDF 回 None。"""
    pdf = pdf_path(p0, name)
    txt = pdf.with_suffix(".txt")
    if not txt.exists():
        if not pdf.exists():
            return None
        out = subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)], capture_output=True)
        if out.returncode:
            raise ValueError(f"嘉義市議事錄 pdftotext 失敗：{pdf}：{out.stderr.decode(errors='replace')[-200:]}")
    return txt.read_text(encoding="utf-8")


def page_words(p0, name, page):
    """PDF 一頁 → [(x 中心, y 中心, 字)]（pdftotext -bbox）。"""
    out = subprocess.run(["pdftotext", "-bbox", "-f", str(page), "-l", str(page), str(pdf_path(p0, name)), "-"],
                         capture_output=True, check=True).stdout.decode("utf-8")
    return [((float(a) + float(c)) / 2, (float(b) + float(d)) / 2, html.unescape(w)) for a, b, c, d, w in WORD.findall(out)]


def lines_of(page):
    return [l.strip() for l in page.split("\n") if l.strip()]


def printed_page(page, chapter):
    """頁首「口頭質詢及答覆 1107」或「1108 口頭質詢及答覆」→ 1107；不是這一章的頁回 None。"""
    ls = lines_of(page)
    if not ls:
        return None
    m = re.fullmatch(rf"{chapter}\s+(\d+)|(\d+)\s+{chapter}", ls[0])
    return int(m[1] or m[2]) if m else None


# ---------- 市政總質詢 ----------

ORAL = "口頭質詢及答覆"
WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')
TOC_SESSION = re.compile(rf"嘉義市議會第\s*{TERM}\s*屆第\s*(\d+)\s*次定期會")
TOC_ITEM = re.compile(r"（\d+）第\s*(\d+)\s*次會議市政總質詢及答覆（(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日）[….\s]*(\d+)$")
MEETING = re.compile(r"第\s*(\d+)\s*次會議市政總質詢及答覆")
MEETING_DATE = re.compile(r"(\d{3})\.(\d\d)\.(\d\d)")
ASK = re.compile(r"(?:議員|副議長|議長)([一-鿿]{2,16})質詢\s*[:：]")  # 名錄有 16 字的姓名
OTHER_LABEL = re.compile(r"\S{2,24}[:：]")  # 獨占一行的其他發言標籤（「建設處長羅資政答覆：」）
# 官方錯字（人工審閱，逐鍵）：(p0, PDF 頁, 原文標籤行) → 姓名
NAME_FIX = {
    # 第 5 次定期會下冊 PDF 第 458 頁（印刷頁 1257–1258，第 13 次會議 114.05.14）「議黃敏修質詢：」漏「員」：前兩段是
    # 「議員黃敏修質詢：」與交通處長許啟明答覆（鐵路高架化配合款 47.23 億），此段接續追問同一題，之後仍由交通處長答覆
    (3366, 458, "議黃敏修質詢："): "黃敏修",
}
# 改名（人工確認，逐鍵）：(p0, 標籤裡的姓名) → 現名。顏翎熹 2022 當選時登記名「顏色不分藍綠支持性專區顏色田慎節」
# （data/identity_national.csv 2026-10-17，Claude 初審；verifier 複核）；議事錄 2023 的標籤用舊名，第 4 次定期會（2024）起同一人標籤寫顏翎熹。
# 第 1 次定期會同一場內「顏／顔」混用（第 18 次會議 PDF 第 1556、1558 頁，第 19 次會議第 1629、1635 頁），都是同一段質詢的接續。
LABEL_ALIAS = {
    (3221, "顏色不分藍綠支持性專區顏色田慎節"): "顏翎熹",  # 第 1 次定期會第 18 次會議（112.05.18）PDF 第 1556 頁
    (3221, "顔色不分藍綠支持性專區顔色田慎節"): "顏翎熹",  # 同上第 1558 頁起；第 19 次會議（112.05.19）第 1629 頁起
    (3221, "顏色不分藍綠支持性專區顔色田慎節"): "顏翎熹",  # 第 19 次會議第 1635 頁起
    (3222, "顏色不分藍綠支持性專區顏色田慎節"): "顏翎熹",  # 第 2 次定期會第 14 次會議（112.11.20）PDF 第 1534 頁起
}


def roc_iso(y, m, d):
    return f"{int(y) + 1911}-{int(m):02d}-{int(d):02d}"


def parse_oral(p0, text, log=print):
    """一冊議事錄 → [{session, no, date, printed, page, askers: {姓名: (PDF 頁, 印刷頁, 字數)}}]（沒有口頭質詢章回 []）。
    每場標題要和章目錄的次數、日期、印刷頁相符，否則整場不收。"""
    pages = text.split("\f")
    session, toc = None, {}
    for p in pages:
        ls = lines_of(p)
        if ORAL in ls[:4] and any(TOC_ITEM.search(l) for l in ls):
            sm = next((TOC_SESSION.search(l) for l in ls[:3] if TOC_SESSION.search(l)), None)
            if sm:
                session = f"第{TERM}屆第{sm[1]}次定期會"
            for l in ls:
                m = TOC_ITEM.search(l)
                if m:
                    toc[int(m[1])] = (roc_iso(m[2], m[3], m[4]), int(m[5]))
    if not toc:
        return []
    if session is None:
        log(f"cyi_book：{p0} 口頭質詢章目錄沒有會期名稱，整冊不收")
        return []
    meetings, cur, block, speaking = [], None, None, False
    for i, p in enumerate(pages):
        printed = printed_page(p, ORAL)
        if printed is None:
            continue
        ls = lines_of(p)[1:]
        for k, l in enumerate(ls):
            m = MEETING.fullmatch(l)
            if m:
                dm = next((MEETING_DATE.fullmatch(x) for x in ls[k + 1:k + 3] if MEETING_DATE.fullmatch(x)), None)
                no, d = int(m[1]), roc_iso(*dm.groups()) if dm else None
                ok = toc.get(no) == (d, printed)
                if not ok:
                    log(f"cyi_book：{session} 第 {no} 次會議標題（PDF 第 {i + 1} 頁、印刷頁 {printed}、日期 {d}）與章目錄 {toc.get(no)} 不符，整場不收")
                cur = {"session": session, "no": no, "date": d, "printed": printed, "page": i + 1, "blocks": [], "ok": ok}
                meetings.append(cur)
                block, speaking = None, False
                continue
            if cur is None:
                continue
            a = ASK.match(l)
            fix = NAME_FIX.get((p0, i + 1, l))
            if a or fix:
                name = fix or LABEL_ALIAS.get((p0, a[1]), a[1])
                if block is None or block["name"] != name:
                    block = {"name": name, "page": i + 1, "printed": printed, "chars": 0}
                    cur["blocks"].append(block)
                speaking = True
                block["chars"] += len(re.sub(r"\s+", "", l[a.end():])) if a else 0
            elif OTHER_LABEL.fullmatch(l):
                if "質詢" in l:
                    log(f"cyi_book：{session} 第 {cur['no']} 次會議 PDF 第 {i + 1} 頁標籤「{l}」不是「議員○○○質詢：」格式，不歸屬")
                speaking = False  # 官員答覆等：本人段落不中斷（下一個本人標籤接續），答覆字數不計
            elif speaking:
                block["chars"] += len(re.sub(r"\s+", "", l))
    for no in sorted(set(toc) - {m["no"] for m in meetings}):
        log(f"cyi_book：{session} 章目錄的第 {no} 次會議在內文找不到標題，不收")
    out = []
    for m in meetings:
        if not m["ok"]:
            continue
        best = {}
        for b in m["blocks"]:
            if b["chars"] > best.get(b["name"], {"chars": -1})["chars"]:
                best[b["name"]] = b
        askers = {}
        for n, b in best.items():
            if b["chars"] < MIN_CHARS:
                log(f"cyi_book：{m['session']} 第 {m['no']} 次會議 {n} 最長的一段只有 {b['chars']} 字（共用時間或插話），不收")
                continue
            askers[n] = (b["page"], b["printed"], b["chars"])
        out.append({k: m[k] for k in ("session", "no", "date", "printed", "page")} | {"askers": askers})
    return out


# ---------- 出缺席一覽表 ----------

ATT_TITLE = re.compile(rf"嘉義市議會第\s*{TERM}\s*屆\s*(?:第\s*(\d+)\s*次定期會|(\d+)\s*年\s*第\s*(\d+)\s*次臨時會)\s*議員出(?:缺)?席(?:表|一覽表)")
ROW_DATE = re.compile(r"(\d{3})\.(\d\d)\.(\d\d)|(\d{1,2})月(\d{1,2})日")  # 臨時會的表只寫「6月20日」，年份取表名
COL_TOL = 6.0  # pt；姓名字與合計數字的 x 中心距離上限（欄距約 17 pt）


def attendance_pages(text):
    """一冊議事錄 → [(PDF 頁, 會期, 臨時會的民國年)]：出席表標題所在的頁；一頁不只一張表的回 None 會期。"""
    out = []
    for i, p in enumerate(text.split("\f")):
        ms = [m for m in (ATT_TITLE.search(l) for l in lines_of(p)) if m]
        if not ms:
            continue
        m = ms[0]
        session = f"第{TERM}屆第{m[1]}次定期會" if m[1] else f"第{TERM}屆{m[2]}年第{m[3]}次臨時會"
        out.append((i + 1, session if len(ms) == 1 else None, m[2]))
    return out


def parse_attendance(words, year=None):
    """出席表一頁的 bbox 字 → ({姓名: (出席, 請假)}, 第一個日期)；year 是表名的民國年（臨時會）。
    任何一處對不上 raise ValueError（整張不收）。"""
    def row(label):
        ys = [y for x, y, w in words if w == label]
        if len(ys) != 1:
            raise ValueError(f"「{label}」出現 {len(ys)} 次")
        lx = next(x for x, y, w in words if w == label)
        return sorted((x, int(w)) for x, y, w in words if w.isdigit() and abs(y - ys[0]) < 3 and x > lx), ys[0]

    present, py = row("出席")
    leave_nums, ly = row("請假")
    if not present:
        raise ValueError("合計出席列沒有數字")
    leave = [None] * len(present)
    for x, n in leave_nums:
        near = [i for i, (cx, _) in enumerate(present) if abs(cx - x) <= COL_TOL]
        if len(near) != 1 or leave[near[0]] is not None:
            raise ValueError(f"合計請假的數字 {n}（x={x:.1f}）對不到唯一一欄")
        leave[near[0]] = n
    leave = [0 if v is None else v for v in leave]  # 早期的表請假 0 次留白
    # 同一張表每欄出席＋請假應相同（該會期的會議次數）；不同就是合計列有誤（第 6 次定期會出席列全印 35），整張不收
    if len({p + v for (_, p), v in zip(present, leave)}) != 1:
        raise ValueError(f"各欄合計出席＋請假不一致（{sorted({p + v for (_, p), v in zip(present, leave)})}）")
    dates = sorted((y, w) for x, y, w in words if ROW_DATE.fullmatch(w))
    if not dates or dates[0][0] > py:
        raise ValueError("讀不到逐日列的日期")
    title_ys = [y for x, y, w in words if "議員出" in w and "席" in w]
    if not title_ys:
        raise ValueError("bbox 讀不到表名")
    title_y = max(title_ys)
    left = present[0][0] - 2 * COL_TOL
    chars = [(x, y, w) for x, y, w in words if title_y < y < dates[0][0] and x > left and re.fullmatch(r"[一-鿿]", w)]
    cols = {i: [] for i in range(len(present))}
    for x, y, w in chars:
        near = [i for i, (cx, _) in enumerate(present) if abs(cx - x) <= COL_TOL]
        if len(near) != 1:
            raise ValueError(f"姓名字「{w}」（x={x:.1f}）對不到唯一一欄")
        cols[near[0]].append((y, w))
    out = {}
    for i, cs in cols.items():
        name = "".join(w for _, w in sorted(cs))
        if not 2 <= len(name) <= 4 or name in out:
            raise ValueError(f"第 {i + 1} 欄姓名「{name}」讀不出或重複")
        out[name] = (present[i][1], leave[i])
    d = ROW_DATE.fullmatch(dates[0][1])
    if d[1]:
        return out, roc_iso(d[1], d[2], d[3])
    if year is None:
        raise ValueError("逐日列的日期沒有年份")
    return out, roc_iso(year, d[4], d[5])


def load_tables(p0, name, text, roster, log=print):
    """一冊議事錄的出席表 → [{session, page, date, people: {person_id: (出席, 請假)}}]；整張對不上的不收（印 log）。"""
    out = []
    for page, session, year in attendance_pages(text):
        label = f"{p0}/{name} PDF 第 {page} 頁"
        if session is None:
            log(f"cyi_book：出席表 {label} 一頁有多張表，不收")
            continue
        try:
            cols, first = parse_attendance(page_words(p0, name, page), year)
        except ValueError as e:
            log(f"cyi_book：出席表 {session}（{label}）{e}，整張不收")
            continue
        people, unknown = {}, []
        for n, v in cols.items():
            pid, why = resolve(n, roster)
            if pid:
                people[pid] = v
            else:
                unknown.append(f"{n}（{why}）")
        if unknown:
            log(f"cyi_book：出席表 {session}（{label}）有對不到名錄的欄 {'、'.join(unknown)}，整張不收")
            continue
        out.append({"session": session, "page": page, "date": first, "people": people, "p0": p0, "name": name})
    return out


# ---------- 組成 ----------

def slug(session):
    """「第11屆第7次定期會」→ 7r；「第11屆114年第4次臨時會」→ 114-4t。"""
    return re.sub(r"\D+", "-", session.replace(f"第{TERM}屆", "")).strip("-") + ("r" if "定期" in session else "t")


def unique(rows, key, what, log=print):
    """同一個 key 出現不只一次（兩冊都有）的整組不收。"""
    n = Counter(key(r) for r in rows)
    for k, c in n.items():
        if c > 1:
            log(f"cyi_book：{what} {k} 出現 {c} 次，不收")
    return [r for r in rows if n[key(r)] == 1]


def load_books(log=print):
    """快取 → [(p0, 附件路徑, 檔名, 文字)]；清單上的附件快取沒有就 raise（不寫，避免刪掉舊 fact）。"""
    out = []
    for p0, title in parse_list((CACHE / "list.html").read_text(encoding="utf-8")):
        files = parse_detail((CACHE / f"annf_{p0}.html").read_text(encoding="utf-8"))
        if not files:
            log(f"cyi_book：{title}（p0={p0}）官網沒有議事錄附件，不收")
        for rel, name in files:
            text = book_text(p0, name)
            if text is None:
                raise FileNotFoundError(f"嘉義市議事錄快取沒有 {p0}/{name}；先跑 python3 -m etl.sources.cyi_book --fetch")
            out.append((p0, rel, name, text))
    return out


def build(conn, books, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    pids = set()
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"cyi_book：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        pids.add(pid)
    meetings, tables = [], []
    for p0, rel, name, text in books:
        meetings += [m | {"rel": rel} for m in parse_oral(p0, text, log)]
        tables += [t | {"rel": rel} for t in load_tables(p0, name, text, roster, log)]
    meetings = unique(meetings, lambda m: f"{m['session']}第{m['no']}次會議", "市政總質詢", log)
    tables = unique(tables, lambda t: t["session"], "出席表", log)
    gov = {}
    for m in sorted(meetings, key=lambda m: m["date"]):
        for n, (page, printed, _) in m["askers"].items():
            pid, why = resolve(n, roster)
            if not pid:
                log(f"cyi_book：市政總質詢 {m['session']}第 {m['no']} 次會議 {n}：{why}，不收")
                continue
            if pid not in pids:
                continue
            data = {"term": TERM, "session": m["session"], "doc_type": GOV_DOC, "dept": None,
                    "title": f"市政總質詢紀錄（第 {m['no']} 次會議，本人發言自議事錄第 {printed} 頁起）",
                    "councillors": [n], "group_size": 1, "page": page, "printed_page": printed}
            gov.setdefault(pid, []).append((f"cyigov:{slug(m['session'])}-{m['no']}:{pid}", data,
                                            f"{file_url(m['rel'])}#page={page}", m["date"]))
    att = {}
    for t in sorted(tables, key=lambda t: t["date"]):
        for pid, (present, leave) in t["people"].items():
            if pid not in pids:
                continue
            data = {"term": TERM, "session": t["session"], "title": f"{t['session']}議員出席表（合計列）",
                    "meetings": present + leave, "present": present, "leave": leave, "duty": 0, "from_lists": True}
            att.setdefault(pid, []).append((f"cyiattend:{slug(t['session'])}:{pid}", data,
                                            f"{file_url(t['rel'])}#page={t['page']}", t["date"]))
    return ts, meetings, tables, gov, att


def _print_logs(logs, indent=""):
    for line, n in sorted(Counter(logs).items()):
        print(f"{indent}{line}（{n} 次）" if n > 1 else f"{indent}{line}")


def run(conn):
    logs = []
    books = load_books(logs.append)
    ts, meetings, tables, gov, att = build(conn, books, logs.append)
    _print_logs(logs)
    ng, dg = write(conn, "cyigov", gov, "interpellation")
    na, da = write(conn, "cyiattend", att, "attendance")
    print(f"cyi_book：議事錄 {len(books)} 冊；市政總質詢 {len(meetings)} 場，{len(gov)} 人 {ng} 筆（刪除 {dg}）；"
          f"出席表 {len(tables)} 張，{len(att)} 人 {na} 筆（刪除 {da}）；對象 {len(ts)} 人")


# ---------- 自我檢查 ----------

def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    logs = []
    books = load_books(logs.append)
    ts, meetings, tables, gov, att = build(dump_conn(), books, logs.append)
    _print_logs(logs, "  ")
    print("市政總質詢場次：", sorted(Counter(m["session"] for m in meetings).items()))
    print("出席表：", sorted(t["session"] for t in tables))
    for t in sorted(ts, key=lambda t: t["name"]):
        pid = t["person_id"]
        a, g = att.get(pid, []), gov.get(pid, [])
        print(f"  {t['name']}（{pid}）出席 {sum(d['present'] for _, d, _, _ in a)}／{sum(d['meetings'] for _, d, _, _ in a)}"
              f"、請假 {sum(d['leave'] for _, d, _, _ in a)}；市政總質詢 {len(g)} 場")
        if any(s in t["name"] for s in samples):
            for _, d, u, dt in a:
                print(f"    {d['session']:<18} {dt} 出席 {d['present']:>2} 請假 {d['leave']:>2} {u}")
            for _, d, u, dt in g:
                print(f"    {dt} {d['session']} {d['title']} {u}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        fetch_all()
    else:
        check([a for a in sys.argv[1:] if not a.startswith("--")])
