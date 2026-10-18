"""彰化縣議會第 20 屆議事錄電子書（ep.chcc.gov.tw，FlipBuilder）：逐人縣政質詢紀錄的頁面連結（V16）。

議事錄 PDF 一冊 0.7–0.9 GB，不下載；每冊電子書的 mobile/javascript/search_config.js 有逐頁文字（textForPages），
陣列第 i 個元素就是電子書第 i+1 頁（totalPageCount 與陣列長度相同、config.js 沒有自訂頁碼標籤，main.js 的
「#p=」用的就是這個頁序；抽查 files/mobile/<N>.jpg 的頁面影像與 textForPages[N-1] 一致）。電子書頁序 ≠ 印刷頁碼。

- 第 2、4、5 次定期會那幾冊的文字層是錯碼：內文字型的字碼是 Big5 的「序號」加常數（中文字 +436、A1 列標點 +499，
  ASCII 位移 1），頁首字型另有一套，不解。decode() 只在一頁「錯碼字多於正常中文字」時才解碼；解不出來的字（Big5 以外的
  罕用字，例「凃」「銌」）變成 U+FFFD，含這種字的姓名自然對不到名錄，印 log 不收。
- 第 3 次定期會那冊是掃描影像（只有 1 頁有字），不收；議員宣誓就職暨第 1 次臨時會那冊沒有縣政質詢。
- 每一天的縣政質詢：「第 N 次會議：YYY 年 M 月 D 日」起到該天第一個「散會」為止。主席開場「質詢的議員依序是／質詢議員有／
  質詢順序為 … 個人質詢；… 聯合質詢」是官方名單，只收名單上的人（歸屬只靠名單＋本人發言標籤，不猜）。
  每位名單上的議員，連到當天本人發言標籤「張議員春洋：」所在的頁：取本人連續發言最多的一段，往前併入中間只有本人或同組
  議員發言的段落，取最前面那段的頁（避免把當天稍早「針對同一問題」的補充發言當成起點）。名單上但當天沒有本人發言標籤的
  （改書面質詢、未到）不收、印 log。不在名單、當天發言 ≥ 8 段的名錄議員只印 log 供人工審閱，不掛人。
- 只放標題與連結（電子書該頁），不擷取內文（V16 已定案第 6 點）。
- **改採書面質詢**（2026-10-18 使用者決定；議事錄沒有書面內容）：當天紀錄中主席（「主席(劉議員淑芳)：」到下一個「：」）的發言，
  以句號、逗號切開，一段是「○○○議員（質詢／個人質詢）（他）（改／採／用／以／改為）書面質詢」，或「A議員跟B議員書面質詢」
  「A議員、B議員及C議員書面質詢」（每位都寫全名＋議員）才收；每人每天一筆另一種 doc_type（WRITTEN_DOC），連到電子書該頁。
  主席以外的人說的、「其他的可以書面質詢」這種沒點名的、錯碼讀不出的名字都不收；同一天本人有口頭質詢的不收書面（印 log）。

robots：ep.chcc.gov.tw/robots.txt 404、www.chcc.gov.tw 沒有 robots（V16）。UA civic-lens-etl/0.1、同主機間隔 ≥ 1.1 秒、循序。
只寫給有彰化縣議員任職 fact 且有 2026 candidacy 的人；姓名以 etl.match 的漢字正規化對全部彰化縣議員名錄，同名或對不到的不收。
自我檢查：python3 -m etl.sources.cha_book [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import csv
import re
import sys
import time
from collections import Counter
from pathlib import Path

from etl.fetch import get
from etl.sources.hua_book import write
from etl.sources.kin_book import GOV_DOC
from etl.sources.nwt_book import key, resolve, roster_index, targets

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "cha"
NAMES = ROOT / "data" / "cha_names.csv"
OFFICE = "cha_councilor"
TERM = 20
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔
LIST_URL = "https://www.chcc.gov.tw/ebook/index.aspx?Parser=99,9,157"
EP = "https://ep.chcc.gov.tw/content/meetings/{}/mobile/"
BOOK_LINK = re.compile(r"https://ep\.chcc\.gov\.tw/content/meetings/(no20_r(\d+)_\w+?)/mobile/index\.html")
SKIP_BOOKS = {"no20_r03_t0708": "掃描影像，沒有文字層"}
SUSPECT_TURNS = 8
MIN_TURNS = 3  # 本人發言段數下限：只講一兩句就宣布改書面質詢的不算一場質詢
OPENING = 800  # 主席開場名單只在當天紀錄的開頭找（散會前預告明天議程也有「議程」字樣）

DAY = re.compile(r"第(\d+)次會議(?:紀錄|記錄)?：(\d+)年(\d+)月(\d+)日")
# 「質詢的議員依序是」「質詢議員有」「質詢議員：」「質詢議員陳…」「質詢順序為」，也有主席口誤成「出席議員有」；只收以個人質詢／聯合質詢結尾的組
LIST_START = re.compile(r"(?:質詢|出席)(?:的)?議員(?:依序是|依序為|有|：|:)?|質詢順序為")
LIST_FALLBACK = re.compile(r"議程(?:仍然)?是縣政(?:質詢|諮詢)[。，]")  # 少數天沒有「質詢議員」字樣，名單直接接在議程後面
LIST_END = re.compile(r"首先|現在時間|現在的時間|現在是|現場時間|誰要先")
LIST_MAX = 300  # 名單之後找不到結束語時，只看這麼長（避免把整天內文當名單）
GROUP = re.compile(r"(.*?)(個人質詢|聯合質詢)")
LIST_NAME = re.compile(r"([一-鿿\ufffd]{2,4}?)議員")

WRITTEN_DOC = "改採書面質詢（內容未公開）"  # 與 site/app.js 的 WRITTEN_SWITCH 相同
CHAIR_TURN = re.compile(r"主席[（(][^）)：]{2,10}[）)]：((?:(?!主席[（(])[^：])*)")  # 到下一個發言標籤的「：」或下一段主席發言
SW_FILLER = r"(?:接下來是?|再來是?|那|好|第[一二三四]輪(?:的是)?|所以|我們)*"
SW_VERB = r"(?:質詢|個人質詢)?(?:他|她|他們|兩位|都)*(?:是|要)?(?:改|採|用|以|採用|改為|改用|改成|要用)?書面質詢"
SW_PRONOUN = re.compile(r"^(?:他|她)(?:是|要)?(?:改|採|用|以|採用|改為|改用|改成)書面質詢$")  # 「張雪如議員個人質詢，她改成書面質詢」
SW_ONE = re.compile(rf"^{SW_FILLER}([一-鿿\ufffd]{{2,4}}?)議員{SW_VERB}$")
SW_GROUP = re.compile(rf"^{SW_FILLER}((?:[一-鿿\ufffd]{{2,4}}?議員(?:、|跟|和|及|與))+[一-鿿\ufffd]{{2,4}}?議員){SW_VERB}$")

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


# ---------- 文字層 ----------

def _big5(seq):
    """Big5 序號（A140 起每列 157 字）→ 字；不是 cp950 字元回 None。"""
    row, col = divmod(seq, 157)
    trail = 0x40 + col if col < 63 else 0xA1 + col - 63
    try:
        return bytes([0xA1 + row, trail]).decode("cp950")
    except (UnicodeDecodeError, ValueError):
        return None


def garbled(text):
    cjk = sum(1 for c in text if 0x4E00 <= ord(c) <= 0x9FFF)
    odd = sum(1 for c in text if 0x100 <= ord(c) < 0x4000)
    return odd > cjk


def decode(text):
    """錯碼頁 → 正常文字（見模組說明）；正常頁原樣回傳。"""
    if not garbled(text):
        return text
    out = []
    for c in text:
        o = ord(c)
        if 499 <= o < 656:
            ch = _big5(o - 499)
        elif o >= 907:
            ch = _big5(o - 436)
        elif o >= 0x80:
            ch = None
        elif 0x21 <= o < 0x7F:
            ch = chr(o - 1)
        else:
            ch = c
        out.append(ch or "�")
    return "".join(out)


def parse_pages(js):
    """search_config.js → textForPages（JS 字串陣列，含 JSON 不接受的跳脫，所以自己解）。"""
    body = js[js.index("[", js.index("textForPages")):]
    out = []
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"|\]', body):
        if m.group(0) == "]":
            break
        out.append(re.sub(r"\\(.)", lambda x: {"n": "\n", "t": "\t"}.get(x.group(1), x.group(1)), m.group(1)))
    return out


def book_url(book, page=None):
    return EP.format(book) + "index.html" + (f"#p={page}" if page else "")


# ---------- 快取 ----------

def load_books(refresh=True):
    """→ [{id, nth}]：議事錄清單上第 20 屆定期會的電子書（臨時會、宣誓就職那冊沒有縣政質詢）。"""
    path = CACHE / "ebook_list.html"
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(LIST_URL))
    seen = {}
    for book, nth in BOOK_LINK.findall(path.read_text(encoding="utf-8")):
        seen.setdefault(book, {"id": book, "nth": int(nth)})
    if not seen:
        raise ValueError("彰化議事錄清單沒有第 20 屆定期會電子書")
    return sorted(seen.values(), key=lambda b: b["nth"])


def book_pages(book, refresh=False):
    path = CACHE / f"{book}.js"
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(EP.format(book) + "javascript/search_config.js"))
    return [decode(p) for p in parse_pages(path.read_text(encoding="utf-8-sig"))]


# ---------- 解析 ----------

def flat(text):
    return re.sub(r"\s+", "", text)


def parse_days(pages):
    """→ [{nth, date, start（電子書頁）, chunks: [(頁, 文字)]}]：每天從會議標題到第一個「散會」。"""
    heads = []
    for i, p in enumerate(pages):
        m = DAY.search(flat(p))
        if m:
            heads.append((i, m))
    out = []
    for k, (i, m) in enumerate(heads):
        stop = heads[k + 1][0] if k + 1 < len(heads) else len(pages)
        chunks = []
        for j in range(i, stop):
            t = flat(pages[j])
            if j == i:
                t = t[m.start():]
            end = t.find("散會")
            chunks.append((j + 1, t if end < 0 else t[:end]))
            if end >= 0:
                break
        y, mo, d = (int(x) for x in m.groups()[1:])
        out.append({"nth": int(m.group(1)), "date": f"{y + 1911}-{mo:02d}-{d:02d}", "start": i + 1, "chunks": chunks})
    return out


def opening_groups(text):
    """主席開場的質詢名單 → [[姓名, …], …]（依序；聯合質詢一組多人）。找不到名單回 []。"""
    m = LIST_START.search(text[:OPENING]) or LIST_FALLBACK.search(text[:OPENING])
    if not m:
        return []
    rest = text[m.end():]
    e = LIST_END.search(rest)
    seg = rest[:e.start()] if e else rest[:LIST_MAX]
    groups = []
    for g, _ in GROUP.findall(seg):
        names = [re.sub(r"^(?:是|有|為|及|和|與)", "", n) for n in LIST_NAME.findall(g)]
        if names:
            groups.append(names)
    return groups


def labels(name):
    """發言標籤：姓（1 或 2 字）＋議員＋名＋全形冒號。主席「主席(劉議員淑芳)：」有右括號，不會對到。"""
    return [name[:k] + "議員" + name[k:] + "：" for k in (1, 2) if len(name) - k >= 1]


def events(chunks, forms):
    """forms：{姓名: [文字上的寫法, …]} → [(頁, 姓名)]：每個人的發言標籤，依出現順序。"""
    hits = []
    for n, (page, text) in enumerate(chunks):
        for name, written in forms.items():
            for lab in {lab for w in written for lab in labels(w)}:
                hits += [((n, m.start()), page, name) for m in re.finditer(re.escape(lab), text)]
    return [(page, name) for _, page, name in sorted(hits)]


def runs(evs):
    out = []
    for page, name in evs:
        if out and out[-1][0] == name:
            out[-1][2] += 1
        else:
            out.append([name, page, 1])
    return out


def start_page(rs, name, group):
    """本人連續發言最多的一段往前、往後併入中間只有本人或同組議員的段落（本人的質詢時段）→ (最前面一段本人發言的頁,
    時段內本人發言段數)；當天沒有發言回 (None, 0)。"""
    own = [i for i, r in enumerate(rs) if r[0] == name]
    if not own:
        return None, 0
    i = max(own, key=lambda j: (rs[j][2], -j))
    lo = hi = i
    while lo > 0 and rs[lo - 1][0] in group:
        lo -= 1
    while hi + 1 < len(rs) and rs[hi + 1][0] in group:
        hi += 1
    mine = [r for r in rs[lo:hi + 1] if r[0] == name]
    return mine[0][1], sum(r[2] for r in mine)


def day_entries(day, roster_names, aliases=None, log=print):
    """→ (entries [{name, listed, group, page}], skipped [姓名])：當天名單上有本人發言的議員，與名單上當天沒有口頭質詢的人
    （沒有發言標籤或只講一兩句改書面）；找不到名單回 (None, [])。另印 log（名單沒有發言、發言多卻不在名單）。
    aliases（data/cha_names.csv 該冊的 錯碼寫法 → 姓名）只用來把名單與發言標籤的錯碼寫法歸到同一人；
    是否收錄由 facts() 依人工清單的頁碼與影片說明欄核對。"""
    aliases = aliases or {}
    text = "".join(t for _, t in day["chunks"])
    groups = opening_groups(text)
    if not groups:
        log(f"cha_book：{day['date']} 找不到質詢名單，整天不收")
        return None, []
    canon = [[aliases.get(n, n) for n in g] for g in groups]
    listed = [n for g in canon for n in g]
    forms = {n: [n] for n in set(listed) | set(roster_names)}
    for g in groups:
        for n in g:
            forms[aliases.get(n, n)].append(n)
    rs = runs(events(day["chunks"], forms))
    out, skipped = [], []
    for g, cg in zip(groups, canon):
        for raw, name in zip(g, cg):
            page, n = start_page(rs, name, set(cg))
            if page is None:
                log(f"cha_book：{day['date']} 名單上的 {raw} 當天沒有本人發言標籤，不收")
                skipped.append(name)
            elif n < MIN_TURNS:
                log(f"cha_book：{day['date']} 名單上的 {raw} 本人發言只有 {n} 段（可能改書面質詢），不收")
                skipped.append(name)
            else:
                out.append({"name": name, "listed": raw, "group": cg, "page": page})
    # 標題的同組名單不列當天沒有口頭質詢的人（與影片「當天質詢議員」一致）
    out = [{**e, "group": [n for n in e["group"] if n not in skipped]} for e in out]
    turns = Counter()
    for r in rs:
        turns[r[0]] += r[2]
    for name, n in turns.items():
        if name not in listed and n >= SUSPECT_TURNS:
            log(f"cha_book：{day['date']} {name} 發言 {n} 段但不在質詢名單（待人工審閱，不歸屬）")
    return out, skipped


def chair_written(day, log=print):
    """當天主席發言中逐一點名改採書面質詢的議員 → [(電子書頁, 寫法, 句子編號)]（見模組說明）；同一句的人共用句子編號，
    written_facts 據以在其中有人當天其實口頭質詢時整句不收。"""
    out = []
    for page, text in day["chunks"]:
        for t in CHAIR_TURN.finditer(text):
            for sent in re.split(r"[。！？；]", t[1]):
                if "書面質詢" not in sent:
                    continue
                hit, sid = False, f"{page}:{sent[:30]}"
                clauses = re.split(r"[，,]", sent)
                for j, clause in enumerate(clauses):
                    g = SW_GROUP.match(clause)
                    one = None if g else SW_ONE.match(clause)
                    if not (g or one) and j + 1 < len(clauses) and SW_PRONOUN.match(clauses[j + 1]):
                        one = re.match(rf"^{SW_FILLER}([一-鿿\ufffd]{{2,4}}?)議員(?:個人質詢)?$", clause)
                    if g:
                        out += [(page, n, sid) for n in re.split(r"議員(?:、|跟|和|及|與)?", g[1]) if n]
                    elif one:
                        out.append((page, one[1], sid))
                    hit = hit or bool(g or one)
                if not hit and "議員" in sent:
                    log(f"cha_book：{day['date']} 主席提到書面質詢「{sent[:60]}」但沒有逐一點名，不收")
    return out


def load_names(path=NAMES):
    """data/cha_names.csv（人工審閱：電子書頁面影像上的真名＋當天影片說明欄有列名）→ {(冊, 錯碼寫法): {page, name}}。"""
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if not (r["book"].startswith("no20_r") and r["page"].isdigit() and r["garbled"]
                    and re.fullmatch(r"[一-鿿]{2,4}", r["name"]) and r["evidence"].strip()):
                raise ValueError(f"cha_names.csv 格式不符：{r}")
            key_ = (r["book"], r["garbled"])
            if key_ in out and out[key_]["name"] != r["name"]:
                raise ValueError(f"cha_names.csv 同一冊同一寫法對到不同人：{r}")
            out.setdefault(key_, {"name": r["name"], "pages": set()})["pages"].add(int(r["page"]))
    return out


def collect(books, texts, roster_names, names=None, log=print):
    """→ (entries [{book, session, date, page, name, listed, group}], covered {有名單的日期}, skipped {(日期, 姓名)},
    written [{book, session, date, page, name}])。"""
    names = load_names() if names is None else names
    out, covered, skipped, written = [], set(), set(), []
    for b in books:
        if b["id"] in SKIP_BOOKS:
            log(f"cha_book：{b['id']} {SKIP_BOOKS[b['id']]}，不收")
            continue
        days = parse_days(texts[b["id"]])
        if not days:
            log(f"cha_book：{b['id']} 找不到縣政質詢的會議標題，不收")
        aliases = {g: v["name"] for (book, g), v in names.items() if book == b["id"]}
        for day in days:
            written += [{"book": b["id"], "session": f"第{TERM}屆第{b['nth']}次定期會", "date": day["date"], "page": pg, "name": n,
                         "sid": f"{b['id']}:{sid}"} for pg, n, sid in chair_written(day, log)]
            entries, skip = day_entries(day, roster_names, aliases, log)
            if entries is None:
                continue
            covered.add(day["date"])
            skipped |= {(day["date"], n) for n in skip}
            for e in entries:
                out.append({**e, "book": b["id"], "session": f"第{TERM}屆第{b['nth']}次定期會", "date": day["date"]})
    return out, covered, skipped, written


# 議事錄把「陳玉姬」打成日式字形「陳玉姫」；只在本模組比對時視為同字（etl.match.VARIANTS 是全站共用，不動）
NAME_VARIANTS = str.maketrans({"姫": "姬"})


def cha_roster(conn):
    """彰化議員名錄索引，鍵也套 NAME_VARIANTS：人工確認後 person 名可能是中選會寫法（陳玉姫），文件寫官網寫法（陳玉姬）。"""
    idx = {}
    for k, ids in roster_index(conn, OFFICE).items():
        idx.setdefault(k.translate(NAME_VARIANTS), []).extend(ids)
    return idx


def video_lists():
    """影片說明欄快取 → {日期: {姓名}}（cha_videos 的快取；不連網）。"""
    from etl.sources import cha_videos
    out = {}
    try:
        items = cha_videos.load_items()
    except FileNotFoundError:
        return out
    for it in items:
        meta = cha_videos.parse_description(cha_videos.description(it["video_id"], fetch_missing=False))
        if meta:
            out.setdefault(meta["date"], set()).update(n.translate(NAME_VARIANTS) for n in meta["names"])
    return out


def facts(entries, roster, pids, names=None, videos=None, log=print):
    """人工清單改名的場次，要清單上的頁碼與算出的起始頁相同、且當天影片說明欄有列此名，才收。
    聯合質詢的同組名單只列對得到名錄的人（錯碼或名錄沒有的名字不顯示）。"""
    names = load_names() if names is None else names
    videos = video_lists() if videos is None else videos
    out = {}
    for e in entries:
        if e["listed"] != e["name"]:
            row = names.get((e["book"], e["listed"]), {})
            if e["page"] not in row.get("pages", ()):
                log(f"cha_book：{e['date']} {e['listed']}→{e['name']}：第 {e['page']} 頁不在人工清單，不收")
                continue
            if e["name"] not in videos.get(e["date"], ()):
                log(f"cha_book：{e['date']} {e['listed']}→{e['name']}：當天影片說明欄沒有列此名，不收")
                continue
        pid, why = resolve(e["name"].translate(NAME_VARIANTS), roster)
        if not pid:
            log(f"cha_book：{e['date']} {e['name']}：{why}，不收")
            continue
        if pid not in pids:
            continue
        group = [n.translate(NAME_VARIANTS) for n in e["group"] if resolve(n.translate(NAME_VARIANTS), roster)[0]]
        joint = f"聯合質詢：{'、'.join(group)}；" if len(group) > 1 else ""
        data = {"term": TERM, "session": e["session"], "doc_type": GOV_DOC, "dept": None,
                "title": f"縣政質詢紀錄（{joint}議事錄電子書第 {e['page']} 頁起）",
                "councillors": group, "group_size": len(group), "page": e["page"], "book": e["book"]}
        out.setdefault(pid, []).append((f"chabook:{e['book']}:{e['date']}:{pid}", data, book_url(e["book"], e["page"]), e["date"]))
    return out


def written_facts(written, entries, roster, pids, log=print):
    """主席宣布改採書面質詢：每人每天一筆；同一天本人有口頭質詢（名單場次）的不收，同一句點名的其他人也不收
    （例：2025-11-04 主席先說三位都書面質詢、接著改口其中一位要質詢）。"""
    oral = {(e["date"], resolve(e["name"].translate(NAME_VARIANTS), roster)[0]) for e in entries}
    bad = {w["sid"] for w in written if (w["date"], resolve(w["name"].translate(NAME_VARIANTS), roster)[0]) in oral}
    out, seen = {}, set()
    for w in written:
        if w["sid"] in bad:
            log(f"cha_book：{w['date']} {w['name']} 主席宣布書面質詢的同一句有人當天其實口頭質詢，整句不收")
            continue
        pid, why = resolve(w["name"].translate(NAME_VARIANTS), roster)
        if not pid:
            log(f"cha_book：{w['date']} 書面質詢 {w['name']}：{why}，不收")
            continue
        if pid not in pids or (w["date"], pid) in seen:
            continue
        if (w["date"], pid) in oral:
            log(f"cha_book：{w['date']} {w['name']} 主席宣布書面質詢，但當天也有口頭質詢紀錄，書面不收")
            continue
        seen.add((w["date"], pid))
        data = {"term": TERM, "session": w["session"], "doc_type": WRITTEN_DOC, "dept": None,
                "title": "縣政質詢：主席宣布改採書面質詢（書面內容議會未公開）", "link_label": f"議事錄電子書第 {w['page']} 頁",
                "councillors": [w["name"].translate(NAME_VARIANTS)], "group_size": 1, "page": w["page"], "book": w["book"]}
        out.setdefault(pid, []).append((f"chawr:{w['book']}:{w['date']}:{pid}", data, book_url(w["book"], w["page"]), w["date"]))
    return out


def roster_names(conn):
    return [r["name"] for r in conn.execute(
        "SELECT DISTINCT p.name FROM fact o JOIN person p USING (person_id) "
        "WHERE o.kind = 'office' AND json_extract(o.data, '$.office') = ?", (OFFICE,))]


def build(conn, books, texts, log=print, names=None, videos=None):
    ts = targets(conn, OFFICE)
    roster = cha_roster(conn)
    names = load_names() if names is None else names
    pids = set()
    for t in ts:
        pid, why = resolve(t["name"].translate(NAME_VARIANTS), roster)
        if pid != t["person_id"]:
            log(f"cha_book：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        pids.add(pid)
    entries, _, _, written = collect(books, texts, roster_names(conn), names, log)
    return ts, entries, facts(entries, roster, pids, names, videos, log), written_facts(written, entries, roster, pids, log)


def _log_lines(logs):
    return [f"{line}（{n} 次）" if n > 1 else line for line, n in sorted(Counter(logs).items())]


def run(conn):
    books = load_books()
    texts = {b["id"]: book_pages(b["id"], refresh=b["id"] not in SKIP_BOOKS) for b in books if b["id"] not in SKIP_BOOKS}
    logs = []
    ts, entries, by_pid, wr = build(conn, books, texts, logs.append)
    for line in _log_lines(logs):
        print(line)
    n, stale = write(conn, "chabook", by_pid, "interpellation")
    nw, sw = write(conn, "chawr", wr, "interpellation")
    print(f"cha_book：電子書 {len(books)} 冊；名單場次 {len(entries)} 筆；對象 {len(ts)} 人，有紀錄 {len(by_pid)} 人，"
          f"{n} 筆（刪除 {stale}）；主席宣布改採書面質詢 {len(wr)} 人 {nw} 筆（刪除 {sw}）")


def run_written(conn):
    """局部補跑只寫「主席宣布改採書面質詢」（不動口頭質詢紀錄，不需要影片快取）：只讀快取。"""
    books = load_books(refresh=False)
    texts = {b["id"]: book_pages(b["id"]) for b in books if b["id"] not in SKIP_BOOKS}
    logs = []
    *_, wr = build(conn, books, texts, logs.append, videos={})
    for line in _log_lines(logs):
        print(line)
    nw, sw = write(conn, "chawr", wr, "interpellation")
    print(f"cha_book：主席宣布改採書面質詢 {len(wr)} 人 {nw} 筆（刪除 {sw}）")


def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    books = load_books(refresh=False)
    texts = {b["id"]: book_pages(b["id"]) for b in books if b["id"] not in SKIP_BOOKS}
    logs = []
    ts, entries, by_pid, wr = build(dump_conn(), books, texts, logs.append)
    for line in _log_lines(logs):
        print(" ", line)
    print(f"名單場次 {len(entries)}；對象 {len(ts)} 人，有紀錄 {len(by_pid)} 人 {sum(map(len, by_pid.values()))} 筆")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in sorted(names, key=names.get):
        if samples and not any(s in names[pid] for s in samples):
            continue
        print(f"  {names[pid]} {len(by_pid.get(pid, []))}：" + "、".join(f"{date}#{d['page']}" for _, d, _, date in sorted(by_pid.get(pid, []), key=lambda x: x[3]))
              + (f"；書面 {len(wr[pid])}：" + "、".join(f"{date}#{d['page']}" for _, d, _, date in sorted(wr[pid], key=lambda x: x[3])) if pid in wr else ""))


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        for b in load_books():
            if b["id"] not in SKIP_BOOKS:
                book_pages(b["id"], refresh=True)
                print(b["id"], flush=True)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
