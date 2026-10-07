"""新北市議會第 4 屆議事錄系統 ntpbook.ntp.gov.tw：大會出席與書面質詢（V15）。

只寫給有新北市議員任職 fact 且有 2026 candidacy 的人；姓名以 etl.match 的漢字正規化對全部新北市議員名錄，
名錄同名或對不到的不收（印 log）。

- 出席：每個會期（IndexByMJ 列出的成立大會、定期會、臨時會）的 BookAgenda 頁，每一次會議一份「摘要紀錄」PDF（有文字層），
  「出　席：」後是出席議員，多數紀錄接著有「請　假：」名單，再接「列　席：」。兩份名單都沒有的人原因不明，
  所以顯示出席、請假（公假另列為公差／公假）次數，不另列缺席（使用者 2026-10-04 決定）。M 是本站收錄、列有出席名單的會議次數
  （本人任職起日以後）；出席欄只寫「詳如簽到簿」（多為審查委員會業務質詢與市政總質詢會議）或停會的紀錄不列入。每人每會期一筆 fact。
- 書面質詢：每個會期 BookAnnex 頁「書面質詢及答復」一節，一份 PDF 一個連結，連結文字寫日期和姓名
  （「114年11月10日陳偉杰議員個人書面質詢及答復」）。PDF 是掃描檔，不抓題目；只收「個人」書面質詢，
  聯合質詢的連署人要打開 PDF 才知道，先不收。每人每會期一筆 fact，同會期有多份時全部列在 files。
自我檢查：python3 -m etl.sources.nwt_book（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import html
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import get, now_utc, pdf_text
from etl.match import VARIANTS, han
from etl.sources.national_councilors import TERM_START

HOST = "https://ntpbook.ntp.gov.tw"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "nwt_book"
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔（robots.txt 404，V15）
TERM = 4
# ponytail: 會期頁（議程、附錄）每次只重抓最新 RECENT 個會期，較舊的用快取；附錄約落後 2 個月上架，
#   超過 RECENT 個會期才補上的附錄會漏。升級：run(full=True) 重抓全部會期頁（約 40 次請求）。
RECENT = 4
_VAR = str.maketrans(VARIANTS)

BOOK = re.compile(r'href="/Home/BookAgenda\?cBookMdslID=([0-9a-f-]{36})"[^>]*>\s*<p[^>]*>\s*(第4屆[^<]*?)\s*</p>')
ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
ROW_DATE = re.compile(r"<td[^>]*>\s*(\d{3})-(\d\d)-(\d\d)\s*</td>")
SUMMARY = re.compile(r'<a href="(https://ntpbook\.ntp\.gov\.tw/Mam/BookAgendaAnnex/[^"]+\.pdf)"[^>]*>\s*摘要紀錄\s*</a>')
ANNEX_LINK = re.compile(r'<a href="(https://ntpbook\.ntp\.gov\.tw/Mam/BookAnnex/[^"]+\.pdf)"[^>]*>\s*<p[^>]*>(.*?)</p>', re.S)
# 「陳偉杰議員個人…」或（第 3 次定期會）「陳議員偉杰個人…」；名字含「、」（兩人以上）是聯合，不收
# 第 3 次定期會另有「呂議員家愷書個人面質詢」「廖議員宜琨個人質詢」「陳議員啟能個人質詢書面質詢」等寫法
PERSONAL = re.compile(r"^(\d{2,3}年.*?日)([^、日]+?)(?:議員)?(?:個人書面質詢|書個人面質詢|個人質詢書面質詢|個人質詢)及答復$")
TITLE_AFTER = re.compile(r"(?:議員|副議長|議長)$")
TITLE_INSIDE = re.compile(r"^(.{1,2}?)(?:議員|副議長|議長)(.+)$")
# 出席名單後面多半接「請　假：」名單（V15 只看了一份沒有請假欄的紀錄），再接「列　席：」
PRESENT = re.compile(r"出\s*席\s*[：:](.*?)(?:請\s*假\s*[：:](.*?))?列\s*席\s*[：:]", re.S)
NOTE = re.compile(r"[（(][^）)]*[）)]")
PAGE_MARK = re.compile(r"第\s*\d+\s*/\s*\d+\s*頁")
LATIN = re.compile(r"[A-Za-z]")

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


# ---------- 解析 ----------

def parse_books(page):
    """IndexByMJ → [{id, session}]（第 4 屆，頁面順序：新到舊），id 重複只留一次。"""
    out, seen = [], set()
    for bid, session in BOOK.findall(page):
        if bid not in seen:
            seen.add(bid)
            out.append({"id": bid, "session": session})
    return out


def parse_agenda(page):
    """BookAgenda → [{date, url}]：每一份大會摘要紀錄（一天可能不只一份），依頁面順序。"""
    out = []
    for row in ROW.findall(page):
        links = SUMMARY.findall(row)
        if not links:
            continue
        d = ROW_DATE.search(row)
        if not d:
            raise ValueError(f"新北議程列有摘要紀錄但沒有日期：{links}")
        y, m, day = d.groups()
        out += [{"date": f"{int(y) + 1911}-{m}-{day}", "url": u} for u in links]
    return out


def _names(block):
    """名單文字 → [(姓名, 括號註記)]（原文寫法，依序）。原住民姓名的拼音併入前一個名字；「洪佳君（公假）」→ (洪佳君, 公假)。"""
    names = []
    for tok in PAGE_MARK.sub(" ", block or "").split():
        note = "".join(NOTE.findall(tok))
        tok = NOTE.sub("", tok)
        if not tok:
            continue
        if LATIN.search(tok) and names and not LATIN.search(names[-1][0]):
            names[-1] = (names[-1][0] + tok, names[-1][1] + note)
        else:
            names.append((tok, note))
    return names


def parse_present(text):
    """摘要紀錄文字 → (出席者, 請假者, 公差／公假者)。請假名單上註記（公假）（公差）的另列，和高雄一樣與請假分開。
    出席欄沒有名單（「詳如簽到簿」、颱風停會等）就 raise。"""
    m = PRESENT.search(text)
    if not m:
        raise ValueError("摘要紀錄找不到「出席：…列席：」")
    if "簽到簿" in m.group(1):
        raise ValueError("出席欄只寫「詳如簽到簿」")
    off = _names(m.group(2))
    duty = [n for n, note in off if "公假" in note or "公差" in note]
    return [n for n, _ in _names(m.group(1))], [n for n, _ in off if n not in duty], duty


def parse_written(page):
    """BookAnnex → 「書面質詢及答復」一節的 [{name, dates, url, title}]（只收個人書面質詢），另回傳其他（聯合）連結文字。"""
    i = page.find("書面質詢及答復</div>")
    if i < 0:
        return [], []
    j = page.find("panel-heading", i)
    section = page[i:j if j > 0 else len(page)]
    personal, other = [], []
    for url, label in ANNEX_LINK.findall(section):
        title = re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", "", label)))
        m = PERSONAL.match(title)
        if m:
            # 寫法不一：「蘇錦雄Paylang．Caya議員個人…」多一個「議員」、「李議員倩萍個人…」、「陳副議長鴻源」
            name = TITLE_INSIDE.sub(r"\1\2", TITLE_AFTER.sub("", m.group(2)))
            personal.append({"name": name, "dates": m.group(1), "url": url, "title": title})
        else:
            other.append(title)
    return personal, other


# ---------- 對象與名錄 ----------

def key(name):
    return han(name).translate(_VAR)


def targets(conn, office="nwt_councilor"):
    """有新北市議員（或 office 指定的）任職 fact 且有 2026 candidacy 的人：[{person_id, name, since}]（since＝任職起日）。"""
    rows = conn.execute("""
        SELECT p.person_id, p.name, MIN(o.date) AS since FROM fact o JOIN person p USING (person_id)
        WHERE o.kind = 'office' AND json_extract(o.data, '$.office') = ?
          AND EXISTS (SELECT 1 FROM fact c WHERE c.person_id = o.person_id AND c.kind = 'candidacy')
        GROUP BY p.person_id ORDER BY p.person_id""", (office,))
    return [{"person_id": r["person_id"], "name": r["name"], "since": r["since"] or TERM_START} for r in rows]


def roster_index(conn, office="nwt_councilor"):
    """全部新北市議員（或 office 指定的）任職 fact（含沒參選者，用來判斷同名）的正規化姓名 → [person_id]。"""
    rows = conn.execute("""
        SELECT DISTINCT p.person_id, p.name FROM fact o JOIN person p USING (person_id)
        WHERE o.kind = 'office' AND json_extract(o.data, '$.office') = ?""", (office,))
    idx = {}
    for r in rows:
        idx.setdefault(key(r["name"]), []).append(r["person_id"])
    return idx


def resolve(name, roster):
    """官方文件上的姓名 → (person_id, None) 或 (None, 原因)。"""
    ids = roster.get(key(name), [])
    if len(ids) > 1:
        return None, "名錄同名"
    if not ids:
        return None, "名錄沒有此人"
    return ids[0], None


# ---------- 快取 ----------

def _cached(name, url, refresh):
    path = CACHE / name
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(url))
    return path.read_bytes()


def load_books(full=False, refresh=True):
    """會期清單與各會期的議程頁、附錄頁 → [{id, session, agenda: html, annex: html}]（新到舊）。"""
    books = parse_books(_cached("index.html", HOST + "/Home/Home/IndexByMJ", refresh).decode("utf-8"))
    if not books:
        raise ValueError("新北議事錄系統找不到第 4 屆會期")
    for i, b in enumerate(books):
        again = refresh and (full or i < RECENT)
        b["agenda"] = _cached(f"agenda_{b['id']}.html", f"{HOST}/Home/BookAgenda?cBookMdslID={b['id']}", again).decode("utf-8")
        b["annex"] = _cached(f"annex_{b['id']}.html", f"{HOST}/Home/BookAnnex?cBookMdslID={b['id']}", again).decode("utf-8")
    return books


def summary_text(url, fetch_missing=True):
    """摘要紀錄 PDF（以檔名 uuid 快取，刊出後不會改版）→ 文字；沒有快取且 fetch_missing=False 時回 None。"""
    path = CACHE / "summary" / url.rsplit("/", 1)[1]
    if not path.exists():
        if not fetch_missing:
            return None
        data = fetch(url)
        if not data.startswith(b"%PDF"):
            raise ValueError(f"摘要紀錄不是 PDF：{url}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return pdf_text(path.read_bytes())


# ---------- 組成紀錄 ----------

def attendance(books, roster, texts, log=print):
    """→ {person_id: [{session, book_id, meetings: [(date, present)]}]}，涵蓋名錄上每位能唯一對到的議員。

    texts：{摘要紀錄 url: 文字或 None}；None（沒抓到）或解析失敗的那次大會不列入 M。
    出席名單上對不到名錄的姓名印 log。"""
    out = {}
    pids = sorted({ids[0] for ids in roster.values() if len(ids) == 1})
    for b in books:
        meetings = []
        for s in parse_agenda(b["agenda"]):
            if s["date"] < TERM_START:
                continue
            text = texts.get(s["url"])
            if text is None:
                log(f"nwt_book：{b['session']} {s['date']} 摘要紀錄未取得，不列入：{s['url']}")
                continue
            try:
                lists = parse_present(text)
            except ValueError as e:
                log(f"nwt_book：{b['session']} {s['date']} {e}，不列入：{s['url']}")
                continue
            present, leave, duty = set(), set(), set()
            for label, names, into in (("出席", lists[0], present), ("請假", lists[1], leave), ("公假", lists[2], duty)):
                for n in names:
                    pid, why = resolve(n, roster)
                    if pid:
                        into.add(pid)
                    else:
                        log(f"nwt_book：{b['session']} {s['date']} {label}名單 {n}：{why}")
            meetings.append((s["date"], present, leave, duty))
        for pid in pids:
            rows = [(d, "present" if pid in p else "leave" if pid in lv else "duty" if pid in du else None)
                    for d, p, lv, du in meetings]
            if rows:
                out.setdefault(pid, []).append({"session": b["session"], "book_id": b["id"], "meetings": rows})
    return out


def written(books, roster, log=print):
    """→ {person_id: [{session, book_id, files: [{dates, url, title}]}]}（個人書面質詢，依會期）。"""
    out = {}
    for b in books:
        personal, _ = parse_written(b["annex"])
        by_pid = {}
        for w in personal:
            pid, why = resolve(w["name"], roster)
            if not pid:
                log(f"nwt_book：{b['session']} 書面質詢 {w['name']}：{why}，不收")
                continue
            files = by_pid.setdefault(pid, [])
            if w["url"] not in {f["url"] for f in files}:
                files.append({k: w[k] for k in ("dates", "url", "title")})
        for pid, files in by_pid.items():
            out.setdefault(pid, []).append({"session": b["session"], "book_id": b["id"], "files": files})
    return out


def agenda_url(book_id):
    return f"{HOST}/Home/BookAgenda?cBookMdslID={book_id}"


def annex_url(book_id):
    return f"{HOST}/Home/BookAnnex?cBookMdslID={book_id}"


def attendance_facts(person_id, since, sessions):
    """[(fact_key, data, source_url, date)]；只算任職起日以後的大會，沒有大會的會期不出 fact。"""
    out = []
    for s in sessions:
        rows = [(d, p) for d, p in s["meetings"] if d >= since]
        if not rows:
            continue
        # 兩份名單都沒有的次數不另列（使用者 2026-10-04 決定：只顯示出席、請假、公差／公假）
        data = {"term": TERM, "session": s["session"], "title": f"{s['session']}大會摘要紀錄",
                "meetings": len(rows), "present": sum(st == "present" for _, st in rows),
                "leave": sum(st == "leave" for _, st in rows), "duty": sum(st == "duty" for _, st in rows),
                "from_lists": True}
        out.append((f"ntpattend:{s['book_id']}:{person_id}", data, agenda_url(s["book_id"]), rows[0][0]))
    return out


def written_facts(person_id, sessions):
    out = []
    for s in sessions:
        name = s["session"].replace(f"第{TERM}屆", "")
        name = re.sub(r"次定期會$", "次定期大會", name)
        data = {"term": TERM, "session": s["session"], "title": f"{name}書面質詢及答復（掃描檔）",
                "doc_type": "書面質詢", "dept": None, "scanned": True,
                "files": [{"dates": f["dates"], "url": f["url"]} for f in s["files"]]}
        out.append((f"ntpwritten:{s['book_id']}:{person_id}", data, s["files"][0]["url"], first_date(s["files"])))
    return out


def first_date(files):
    """連結文字的日期（「114年10月28日、11月7日」）→ 最早的西元日期；讀不到回 None。"""
    m = [re.match(r"(\d+)年(\d+)月(\d+)日", f["dates"]) for f in files]
    return min((f"{int(y) + 1911}-{int(mo):02d}-{int(d):02d}" for y, mo, d in (x.groups() for x in m if x)), default=None)


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


def build(conn, books, texts, log=print):
    ts = targets(conn)
    roster = roster_index(conn)
    att, wr = attendance(books, roster, texts, log), written(books, roster, log)
    att_facts, wr_facts = {}, {}
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"nwt_book：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        if pid in att:
            att_facts[pid] = attendance_facts(pid, t["since"], att[pid])
        if pid in wr:
            wr_facts[pid] = written_facts(pid, wr[pid])
    return ts, att_facts, wr_facts


def run(conn, full=False):
    books = load_books(full)
    texts = {s["url"]: summary_text(s["url"]) for b in books for s in parse_agenda(b["agenda"]) if s["date"] >= TERM_START}
    logs = Counter()  # 依訊息（去掉日期）合併計數，避免同一位前議員每次會議印一行
    ts, att_facts, wr_facts = build(conn, books, texts, lambda s: logs.update([re.sub(r" \d{4}-\d\d-\d\d|：https://\S+", "", s)]))
    for line, n in sorted(logs.items()):
        print(f"{line}（{n} 次）" if n > 1 else line)
    na, da = write(conn, "ntpattend", att_facts, "attendance")
    nw, dw = write(conn, "ntpwritten", wr_facts, "interpellation")
    print(f"nwt_book：會期 {len(books)} 個、摘要紀錄 {len(texts)} 份；對象 {len(ts)} 人；"
          f"出席 {len(att_facts)} 人 {na} 筆（刪除 {da}）；書面質詢 {len(wr_facts)} 人 {nw} 筆（刪除 {dw}）")


# ---------- 自我檢查 ----------

def dump_conn():
    import tempfile
    from etl.db import open_db
    d = tempfile.mkdtemp()
    return open_db(Path(d) / "check.db", Path(__file__).resolve().parents[2] / "data" / "civic.sql")


def check(samples=()):
    """讀快取與 data/civic.sql：對象人數、出席與書面質詢的人數與筆數，並列出抽查議員的逐會期數字與連結。"""
    conn = dump_conn()
    books = load_books(refresh=False)
    texts = {s["url"]: summary_text(s["url"], fetch_missing=False) for b in books for s in parse_agenda(b["agenda"])
             if s["date"] >= TERM_START}
    logs = []
    ts, att_facts, wr_facts = build(conn, books, texts, logs.append)
    for line in sorted(set(logs)):
        print(" ", line)
    print(f"會期 {len(books)} 個；摘要紀錄 {len(texts)} 份（已快取 {sum(t is not None for t in texts.values())}）")
    print(f"對象 {len(ts)} 人；出席：{len(att_facts)} 人 {sum(map(len, att_facts.values()))} 筆；"
          f"書面質詢：{len(wr_facts)} 人 {sum(map(len, wr_facts.values()))} 筆"
          f"（PDF {sum(len(d['files']) for fs in wr_facts.values() for _, d, _, _ in fs)} 份）")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in [p for p in names if names[p] in samples]:
        print(f"\n{names[pid]}（{pid}）")
        for _, d, url, _ in att_facts.get(pid, []):
            print(f"  出席 {d['session']:<12} {d['present']:>2}／{d['meetings']:<2}（請假 {d['leave']}、公假 {d['duty']}） {url}")
        for _, d, _, _ in wr_facts.get(pid, []):
            print(f"  書面 {d['title']}：{' '.join(f['url'] for f in d['files'])}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:  # 只更新快取，不寫 DB
        bs = load_books("--full" in sys.argv)
        urls = [s["url"] for b in bs for s in parse_agenda(b["agenda"]) if s["date"] >= TERM_START]
        print(f"會期 {len(bs)} 個、摘要紀錄 {len(urls)} 份", flush=True)
        for i, u in enumerate(urls):
            summary_text(u)
            if i % 25 == 0:
                print(i, u, flush=True)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
