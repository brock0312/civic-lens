"""新竹縣議會第 20 屆（www.hcc.gov.tw）：逐人質詢 PDF 與大會出席（V16）。

- 質詢：「議員質詢」頁（question?program=198&council_type=22）每個定期會一頁 detail，「議員」「議長」「副議長」列每份 PDF 一個連結，
  連結文字是議員姓名（聯合質詢列多人，例「張珈源 、何建樺、吳傳地聯合質詢」）。歸屬只看連結文字（不看檔名：檔名有錯字，如「陳柏誠」
  「上官議員宛庭」），連結文字空白的不收。PDF 有文字層的是縣政總質詢逐字紀錄：開頭「質詢議員：」與連結文字的姓名必須相同，
  不同就不收（印 log；沒有封面時改看主席開場「現在開始 N 分鐘是某議員的質詢時間」）；沒有文字層的是掃描檔
  （多為「書面質詢資料」，也有「質詢大綱」），只連結並標「質詢資料（掃描檔）」。致詞不收。
  只連 PDF、不摘要（V16 已定案第 6 點）；PDF 沒有日期，fact 日期是該定期會第一次會議（只用來排序，頁面顯示會期，data.no_date）。
- 出席：「會議紀錄」頁（record?program=195&council_type=22）每次大會一份「會議紀要」PDF（文字層），「出席議員：」到「列席人員：」
  是出席名單，沒有請假名單，所以只算「出席 N／M 次」（V16 已定案第 5 點，比照新北、金門）。紀要沒有記載出席人數，無從核對人數；
  改以：名單每個詞都要是名錄上唯一的議員（或遞補前的前議員 FORMER）、不重複、紀要表頭的會期與清單標題相同，否則整次會議不收（印 log）。
  同一會議時間的紀要重複上架時只算一次；沒有出席名單的紀錄（總預算審議聯席會的下午場次等）、會議日期在任期前（官方誤植）的不列入。
  程序委員會不列入。任期中遞補的人（任職 fact 沒有起日）從第一次列名的會議起算。每人每會期一筆 fact。
- **改採書面質詢**（2026-10-18 使用者決定）：縣政總質詢日的會議紀要逐項列出「一、黃豪杰議員。（書面另錄）」「二、王副議長炳漢（書面）」
  「三、鄭美琴議員。（另錄）」；註記「書面另錄」或「書面」的項目，項目本身要是一位議員（「○○○議員」「王副議長炳漢」「張鎮榮議長」）才收，
  聯合質詢等多人項目不收。每人每天一筆另一種 doc_type（WRITTEN_DOC，書面內容官方沒有公開），連到該份會議紀要，標題照錄註記。
  同一會期另有本人縣政總質詢逐字紀錄的不收（印 log）。

robots.txt 404；隱私宣告沒有著作權或擷取限制（V16）。UA civic-lens-etl/0.1、同主機間隔 ≥ 1.1 秒、循序。
只寫給有新竹縣議員任職 fact 且有 2026 candidacy 的人；姓名以 etl.match 的漢字正規化對全部新竹縣議員名錄，同名或對不到的不收（印 log）。
自我檢查：python3 -m etl.sources.hsq_book [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import html
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
from collections import Counter
from pathlib import Path

from etl.fetch import get
from etl.sources.hua_book import write
from etl.sources.kin_book import PERSON, bare
from etl.sources.national_councilors import TERM_START
from etl.sources.nwt_book import resolve, roster_index, targets

HOST = "https://www.hcc.gov.tw"
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "hsq"
OFFICE = "hsq_councilor"
TERM = 20
COUNCIL_TYPE = 22  # 網站的屆次代碼：第二十屆
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔（robots.txt 404，V16）
QLIST_URL = HOST + f"/question?program=198&page={{}}&council_type={COUNCIL_TYPE}"
QDETAIL_URL = HOST + "/question-detail?article={}"
RECORD_URL = HOST + f"/record?program=195&page={{}}&council_type={COUNCIL_TYPE}"
UPLOAD = HOST + "/upload/web_program/"

LAST_PAGE = re.compile(r'chg_page\((\d+)\)"><span class="icon-backward')
SESSION_LINK = re.compile(r'<a href="question-detail\?article=(\d+)" title="(第\d+屆第\d+次定期會)">')
DETAIL_TITLE = re.compile(r'<h2 class="intro-title">(.*?)</h2>')
DETAIL_ROW = re.compile(r'<tr>\s*<td class="membertable--width">(.*?)</td>(.*?)</tr>', re.S)
LINK = re.compile(r'<a href="(https://www\.hcc\.gov\.tw/upload/web_program/[^"]+\.pdf)"[^>]*>(.*?)</a>', re.S)
RECORD_ITEM = re.compile(r'<div class="schedule-content__list">(.*?)<div class="record-btn"><a href="([^"]+\.pdf)"', re.S)
RECORD_TITLE = re.compile(r'<p class="schedule-title">(.*?)</p>')
LIST_SESSION = re.compile(rf"^第{TERM}屆第(\d+)次(定期會|臨時會)")
# 會議紀要（比對去掉空白後的文字）
MIN_HEAD = re.compile(r"新竹縣議會第(\d+)屆第(\d+)次(定期會|臨時會)")
MIN_TIME = re.compile(r"會議時間：中華民國(\d+)年(\d+)月(\d+)日[（〈(]星期.[）〉)](?:(\d+)時(?:(\d+)分)?)?")
MIN_PRESENT = re.compile(r"出席議員：(.*?)(?=列席人員：|今日議程：|主席：)")  # 少數紀要沒有列席人員
ASKERS = re.compile(r"質詢議員[：:](.*?)記錄[：:]")
ANNOUNCE = re.compile(r"主席[（(][^）)]*[）)]：.{0,20}?現在(?:開始|起)?.{0,8}?是(.+?)的?(?:聯合)?質詢")
# 逐字紀錄封面把陳栢誠寫成陳柏誠（第 2 次定期會；檔名也是），只在封面與連結文字比對時視為同字
COVER_VARIANTS = str.maketrans("柏", "栢")
NAME = re.compile(r"^[一-鿿]{2,5}$")
GOV_DOC = "縣政總質詢紀錄"
SWITCH_DOC = "改採書面質詢（內容未公開）"  # 與 site/app.js 的 WRITTEN_SWITCH 相同
SWITCH_ITEM = re.compile(r"([一二三四五六七八九十]+)、([^、，。（()）]{2,12}?)。?[（(](書面另錄|書面|另錄)[)）]")
WRITTEN_DOC = "質詢資料"  # 掃描檔：多數是「書面質詢資料」，也有「質詢大綱」（第 5 次定期會林秉君），所以不稱書面質詢
# 會議紀要名單上已離職的前議員（不在現任名錄）：{姓名: 遞補者}。只在遞補者第一次列名之前的會議接受，之後出現就整次會議不收。
# 2026-10 實測：鄭昱芸列名至 2024-03-13，陳星宏 2024-06-17 起列名；陳德木只見於 2023-02-06、范振龍見於 2023-07-03～08-18，
# 陳栢誠 2023-11-06 起列名（同一席次的先後任由名單時序推定，只用來限定前議員名字可接受的期間，不影響任何人的歸屬）
FORMER = {"鄭昱芸": "陳星宏", "陳德木": "陳栢誠", "范振龍": "陳栢誠"}

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


def quote(url):
    return urllib.parse.quote(url, safe="/:")


def norm(text):
    return re.sub(r"\s", "", text)


def _text(cell):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", cell))).strip()


def _cached(name, url, refresh):
    path = CACHE / name
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(url))
    return path.read_text(encoding="utf-8")


def _pages(prefix, url, refresh):
    """清單的每一頁（第 1 頁的「最後頁」決定頁數）→ [html]。"""
    first = _cached(f"{prefix}/p1.html", url.format(1), refresh)
    m = LAST_PAGE.search(first)
    return [first] + [_cached(f"{prefix}/p{n}.html", url.format(n), refresh) for n in range(2, int(m[1]) + 1 if m else 2)]


def pdf_path(url):
    return CACHE / "pdf" / url.split("/upload/web_program/", 1)[1]


def pdf_text(url, fetch_missing=True):
    """PDF → 文字（pdftotext -layout，快取在 .txt）；沒有快取且 fetch_missing=False 時回 None。PDF 留在快取（每份 0.1–1 MB）。"""
    pdf = pdf_path(url)
    txt = pdf.with_suffix(".txt")
    if not txt.exists():
        if not pdf.exists():
            if not fetch_missing:
                return None
            data = fetch(quote(url))
            if data[:4] != b"%PDF":
                raise ValueError(f"新竹縣議會檔案不是 PDF：{url}")
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(data)
        txt.write_text(subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, check=True).stdout.decode("utf-8"),
                       encoding="utf-8")
    return txt.read_text(encoding="utf-8")


def file_id(url):
    """「…/upload/web_program/2026/08/18/03邱靖雅議員_113749.pdf」→「2026-08-18-113749」（上傳日＋檔名尾的時間戳）。"""
    rel = url.split("/upload/web_program/", 1)[1]
    m = re.match(r"(\d{4})/(\d\d)/(\d\d)/.*_(\d+)\.pdf$", rel)
    if not m:
        raise ValueError(f"新竹縣議會檔名格式未知：{url}")
    return "-".join(m.groups())


# ---------- 質詢 ----------

def parse_sessions(page):
    """質詢清單 → [(article, 會期)]。"""
    return [(a, s) for a, s in SESSION_LINK.findall(page) if s.startswith(f"第{TERM}屆")]


def link_names(text):
    """連結文字 → [姓名]：「張珈源 、何建樺、吳傳地聯合質詢」「張珈源 &何建樺&吳傳地」「王炳漢 副議長質詢」→ 姓名；空白回 []。"""
    text = re.sub(r"聯合質詢|(?:副議長|議長)?質詢$|副議長$|議長$", "", text.strip())
    return [t for t in re.split(r"[\s、&＆,，]+", text) if t]


def parse_detail(page):
    """detail 頁 → (會期, [{role, text, names, url}])；致詞不收。"""
    title = DETAIL_TITLE.search(page)
    if not title:
        raise ValueError("新竹縣議會質詢頁找不到會期標題")
    out = []
    for role, cell in DETAIL_ROW.findall(page):
        role = _text(role)
        if role not in ("議長", "副議長", "議員"):
            continue
        for url, label in LINK.findall(cell):
            text = _text(label)
            if "致詞" in text:
                continue
            out.append({"role": role, "text": text, "names": link_names(text), "url": html.unescape(url)})
    return _text(title[1]), out


def title_names(raw):
    """「吳議員傳地何議員建樺」「劉建民議員、林秉君議員（聯合質詢）」「楊議員昌德」→ [姓名]（raw 已去掉空白）。
    以頓號分隔；一段裡黏著幾個「姓＋職稱＋名」時依職稱切開；切不乾淨的段原樣保留（比對時一定不相符）。"""
    out = []
    for tok in re.split(r"[、，,]", re.sub(r"[（(][^）)]*[）)]|聯合質詢", "", raw)):
        ms = list(PERSON.finditer(tok))
        if ms and sum(len(m[0]) for m in ms) == len(tok):
            out += [m[1] + m[2] for m in ms]
        elif tok:
            out.append(bare(tok))
    return out


def pdf_askers(text):
    """縣政總質詢逐字紀錄 → 本場質詢議員 [姓名]：封面「質詢議員：楊 議員 昌 德」；沒有封面時用主席開場
    「現在開始 150 分鐘是張珈源議員、何建樺議員、吳傳地議員聯合質詢的時間」。兩者都沒有回 None。"""
    s = norm(text or "")
    m = ASKERS.search(s) or ANNOUNCE.search(s[:300])
    return title_names(m[1]) if m else None


def classify(text):
    """PDF 文字 → 'transcript'（有文字層）或 'scanned'（沒有文字層）。"""
    return "transcript" if len(norm(text or "")) >= 50 else "scanned"


def question_docs(details, texts, log=print):
    """→ [{session, url, names, kind, joint}]：kind 是 transcript／scanned；逐字紀錄封面的質詢議員與連結文字不同的不收。"""
    out = []
    for session, items in details:
        for it in items:
            label = f"{session} 「{it['text']}」（{it['url'].rsplit('/', 1)[1]}）"
            if not it["names"]:
                log(f"hsq_book：質詢 {label} 連結文字沒有姓名，不收")
                continue
            text = texts.get(it["url"])
            if text is None:
                log(f"hsq_book：質詢 {label} PDF 未取得（連結失效或未下載），不收")
                continue
            kind = classify(text)
            if kind == "transcript":
                askers = pdf_askers(text)
                if askers is None:
                    log(f"hsq_book：質詢 {label} 有文字層但封面沒有「質詢議員：」，不收")
                    continue
                if sorted(a.translate(COVER_VARIANTS) for a in askers) != sorted(it["names"]):
                    log(f"hsq_book：質詢 {label} 封面質詢議員 {'、'.join(askers)} 與連結文字不同，不收")
                    continue
                head = MIN_HEAD.search(norm(text)[:200])  # 沒有封面的紀錄沒有會期表頭，以清單為準
                if head and f"第{int(head[1])}屆第{int(head[2])}次{head[3]}" != session:
                    log(f"hsq_book：質詢 {label} 封面會期與清單不同，不收")
                    continue
            out.append({"session": session, "url": it["url"], "names": it["names"], "kind": kind})
    return out


def question_facts(docs, roster, pids, starts, log=print):
    out = {}
    for d in docs:
        resolved = []
        for name in d["names"]:
            pid, why = resolve(name, roster)
            if not pid:
                log(f"hsq_book：質詢 {d['session']} {name}：{why}")
            resolved.append(pid)
        if not all(resolved):
            continue  # 聯合質詢有人對不到時整份不收，避免只掛部分人
        others = "、".join(d["names"])
        joint = f"（聯合質詢：{others}）" if len(d["names"]) > 1 else ""
        if d["kind"] == "transcript":
            data = {"term": TERM, "session": d["session"], "doc_type": GOV_DOC, "dept": None, "councillors": d["names"],
                    "title": f"縣政總質詢紀錄{joint}（PDF）", "no_date": True}
        else:
            data = {"term": TERM, "session": d["session"], "doc_type": WRITTEN_DOC, "dept": None, "councillors": d["names"],
                    "title": f"質詢資料{joint}（PDF，掃描檔）", "scanned": True, "no_date": True}
        for pid in resolved:
            if pid in pids:
                out.setdefault(pid, []).append((f"hsqq:{file_id(d['url'])}:{pid}", data, quote(d["url"]), starts.get(d["session"])))
    return out


# ---------- 改採書面質詢 ----------

def switch_items(text):
    """會議紀要 → [(姓名或 None, 原文項目, 註記)]：縣政總質詢逐項註記「書面另錄」「書面」的項目；項目不是一位議員時姓名為 None。"""
    s, out, used = norm(text or ""), [], set()
    for m in SWITCH_ITEM.finditer(s):
        used.add(m.end(3))
        if "書面" not in m[3]:
            continue
        name = bare(m[2])
        out.append((name if NAME.match(name) and name != m[2] else None, m[2], m[3]))
    for m in re.finditer(r"[（(](書面另錄|書面)(?=[)）])", s):  # 沒有被逐項解析到的註記（聯合質詢等）：印 log 不收
        if m.end() not in used:
            out.append((None, s[max(0, m.start() - 20):m.start()], m[1]))
    return out


def switch_facts(records, texts, roster, pids, docs, log=print):
    """→ {person_id: [(fact_key, data, url, date)]}：每人每天一筆；同會期有本人逐字紀錄的不收。"""
    spoke = {(d["session"], n) for d in docs if d["kind"] == "transcript" for n in d["names"]}
    out, seen = {}, set()
    for r in records:
        m = parse_minutes(texts.get(r["url"]))
        if not m or m["date"] < TERM_START or m["session"] != list_session(r["title"]):
            continue
        for name, raw, note in switch_items(texts.get(r["url"])):
            if not name:
                log(f"hsq_book：會議紀要 {r['title']}（{m['date']}）「{raw}（{note}）」不是一位議員，不收")
                continue
            pid, why = resolve(name, roster)
            if not pid:
                log(f"hsq_book：會議紀要 {m['date']} {note} {name}：{why}，不收")
                continue
            if pid not in pids or (m["date"], pid) in seen:
                continue
            if (m["session"], name) in spoke:
                log(f"hsq_book：會議紀要 {m['date']} {name} 註記{note}，但同會期有本人縣政總質詢逐字紀錄，書面不收")
                continue
            seen.add((m["date"], pid))
            data = {"term": TERM, "session": m["session"], "doc_type": SWITCH_DOC, "dept": None,
                    "title": f"縣政總質詢：會議紀要註記「{note}」（書面內容議會未公開）", "link_label": "會議紀要（PDF）",
                    "councillors": [name], "group_size": 1}
            out.setdefault(pid, []).append((f"hsqwr:{m['date']}:{pid}", data, quote(r["url"]), m["date"]))
    return out


# ---------- 出席 ----------

def parse_records(page):
    """會議紀錄清單一頁 → [{title, url}]（第 20 屆的定期會、臨時會大會；程序委員會不收）。"""
    out = []
    for body, url in RECORD_ITEM.findall(page):
        t = RECORD_TITLE.search(body)
        title = _text(t[1]) if t else ""
        if LIST_SESSION.match(title) and "委員會" not in title:
            out.append({"title": title, "url": html.unescape(url)})
    return out


def list_session(title):
    m = LIST_SESSION.match(title)
    return f"第{TERM}屆第{int(m[1])}次{m[2]}"


def parse_minutes(text):
    """會議紀要 → {session, date, time, names}；不是大會紀要（沒有表頭、會議時間或出席名單）回 None。"""
    s = norm(text or "")
    head, when, present = MIN_HEAD.search(s), MIN_TIME.search(s), MIN_PRESENT.search(s)
    if not (head and when and present):
        return None
    y, mo, d = (int(x) for x in when.groups()[:3])
    hh, mm = when[4], when[5]
    return {"session": f"第{int(head[1])}屆第{int(head[2])}次{head[3]}", "date": f"{y + 1911}-{mo:02d}-{d:02d}",
            "time": f"{int(hh):02d}:{int(mm or 0):02d}" if hh else None,
            "names": [t for t in re.split(r"[、，,]", present[1]) if t]}


def collect_meetings(records, texts, roster, log=print):
    """→ [{session, date, url, title, present_ids}]（依日期、時間）。名單有對不到的詞、重複，或表頭會期與清單不同時整次不收。"""
    parsed = []
    for r in records:
        text = texts.get(r["url"])
        if text is None:
            log(f"hsq_book：會議紀要 {r['title']} 未取得，不列入")
            continue
        m = parse_minutes(text)
        if m is None:
            log(f"hsq_book：會議紀要 {r['title']} 讀不到表頭、會議時間或出席名單，不列入")
            continue
        parsed.append({**m, **r})
    parsed.sort(key=lambda m: (m["date"], m["time"] or ""))
    succ = {}  # 遞補者第一次列名的日期
    for m in parsed:
        for name in FORMER.values():
            if name in m["names"]:
                succ.setdefault(name, m["date"])
    out, seen = [], set()
    for m in parsed:
        label = f"{m['title']}（{m['date']} {m['time'] or '未記載時刻'}）"
        dup = (m["date"], m["time"] or m["title"])  # 沒有時刻的紀要（縣政考察等）以標題區分
        if m["date"] < TERM_START:
            log(f"hsq_book：會議紀要 {label} 會議日期在第 {TERM} 屆任期前（官方誤植），不列入")
            continue
        if m["session"] != list_session(m["title"]):
            log(f"hsq_book：會議紀要 {label} 表頭會期 {m['session']} 與清單標題不同，不列入")
            continue
        if dup in seen:
            log(f"hsq_book：會議紀要 {label} 與另一份紀要的會議時間相同，視為重複，不列入")
            continue
        odd = [t for t in m["names"] if not NAME.match(t)]
        if odd or len(set(m["names"])) != len(m["names"]):
            log(f"hsq_book：會議紀要 {label} 名單有非姓名的詞 {odd[:3]} 或重複姓名，不列入")
            continue
        ids, unknown = set(), []
        for t in m["names"]:
            pid, why = resolve(t, roster)
            if pid:
                ids.add(pid)
            elif t in FORMER and m["date"] < succ.get(FORMER[t], "9999"):
                log(f"hsq_book：會議紀要出席名單 {t}：前議員（{FORMER[t]}遞補前），照收")
            else:
                unknown.append(f"{t}（{why}）")
        if unknown:
            log(f"hsq_book：會議紀要 {label} 名單有對不到名錄的人 {'、'.join(unknown)}，不列入")
            continue
        seen.add(dup)
        out.append({"session": m["session"], "date": m["date"], "url": m["url"], "title": m["title"], "present_ids": ids,
                    "n": len(m["names"])})
    return out


def session_starts(records, texts):
    """各會期第一次會議的日期（用全部讀得到的紀要，不論是否收錄），當質詢 fact 的排序日期。"""
    out = {}
    for r in records:
        m = parse_minutes(texts.get(r["url"]))
        if m and m["date"] >= TERM_START:
            out[m["session"]] = min(out.get(m["session"], m["date"]), m["date"])
    return out


def attendance_facts(meetings, pids, replacements=frozenset()):
    """{person_id: [(fact_key, data, url, date)]}：每人每會期一筆，只有出席次數（沒有請假名單）。
    replacements：任期中遞補的人，從第一次列入出席名單的會議起算。"""
    out = {}
    for pid in pids:
        ms = meetings
        if pid in replacements:
            first = next((i for i, m in enumerate(meetings) if pid in m["present_ids"]), None)
            ms = meetings[first:] if first is not None else []
        by_session = {}
        for m in ms:
            by_session.setdefault(m["session"], []).append(m)
        for session, sm in by_session.items():
            slug = re.sub(r"\D+", "-", session.replace(f"第{TERM}屆", "")).strip("-") + ("r" if "定期" in session else "t")
            data = {"term": TERM, "session": session, "title": f"{session}會議紀要", "meetings": len(sm),
                    "present": sum(pid in m["present_ids"] for m in sm), "leave": None, "duty": None, "from_lists": True}
            out.setdefault(pid, []).append((f"hsqattend:{slug}:{pid}", data, quote(sm[0]["url"]), sm[0]["date"]))
    return out


# ---------- 組成 ----------

def build(conn, details, records, texts, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    pids = set()
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"hsq_book：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        pids.add(pid)
    docs = question_docs(details, texts, log)
    meetings = collect_meetings(records, texts, roster, log)
    replacements = {r[0] for r in conn.execute(
        "SELECT person_id FROM fact WHERE kind = 'office' AND json_extract(data, '$.office') = ? AND date IS NULL", (OFFICE,))}
    qf = question_facts(docs, roster, pids, session_starts(records, texts), log)
    return (ts, docs, meetings, qf, attendance_facts(meetings, pids, replacements),
            switch_facts(records, texts, roster, pids, docs, log))


def load_all(refresh=True):
    sessions = [s for p in _pages("question", QLIST_URL, refresh) for s in parse_sessions(p)]
    if not sessions:
        raise ValueError("新竹縣議會質詢清單找不到第 20 屆定期會")
    details = []
    for article, session in sessions:
        title, items = parse_detail(_cached(f"question/{article}.html", QDETAIL_URL.format(article), refresh))
        if title != session:
            raise ValueError(f"新竹縣議會質詢頁會期不符：{session} / {title}")
        details.append((session, items))
    records = [r for p in _pages("record", RECORD_URL, refresh) for r in parse_records(p)]
    if not records:
        raise ValueError("新竹縣議會會議紀錄清單沒有第 20 屆大會")
    urls = [it["url"] for _, items in details for it in items] + [r["url"] for r in records]
    texts = {}
    for u in dict.fromkeys(urls):
        try:
            texts[u] = pdf_text(u, refresh)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            texts[u] = None  # 官網連結失效（2026-10 實測第 4 次定期會 2 份）：不收，之後重跑會再試
    return details, records, texts


def run(conn):
    details, records, texts = load_all()
    logs = Counter()
    ts, docs, meetings, qf, att, sw = build(conn, details, records, texts, lambda s: logs.update([s]))
    for line, n in sorted(logs.items()):
        print(f"{line}（{n} 次）" if n > 1 else line)
    nq, dq = write(conn, "hsqq", qf, "interpellation")
    na, da = write(conn, "hsqattend", att, "attendance")
    nw, dw = write(conn, "hsqwr", sw, "interpellation")
    print(f"hsq_book：質詢 PDF {sum(len(i) for _, i in details)} 份（收錄 {len(docs)}），{len(qf)} 人 {nq} 筆（刪除 {dq}）；"
          f"會議紀要 {len(records)} 份、收錄大會 {len(meetings)} 次；對象 {len(ts)} 人；出席 {len(att)} 人 {na} 筆（刪除 {da}）；"
          f"改採書面質詢 {len(sw)} 人 {nw} 筆（刪除 {dw}）")


def run_written(conn):
    """局部補跑只寫「改採書面質詢」（不動質詢 PDF 與出席）：只讀快取。"""
    details, records, texts = load_all(refresh=False)
    logs = Counter()
    *_, sw = build(conn, details, records, texts, lambda s: logs.update([s]))
    for line, n in sorted(logs.items()):
        print(f"{line}（{n} 次）" if n > 1 else line)
    nw, dw = write(conn, "hsqwr", sw, "interpellation")
    print(f"hsq_book：改採書面質詢 {len(sw)} 人 {nw} 筆（刪除 {dw}）")


# ---------- 自我檢查 ----------

def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    details, records, texts = load_all(refresh=False)
    logs = []
    ts, docs, meetings, qf, att, sw = build(dump_conn(), details, records, texts, logs.append)
    for line, n in sorted(Counter(logs).items()):
        print(" ", line, f"（{n} 次）" if n > 1 else "")
    print("會期：", sorted(Counter(m["session"] for m in meetings).items(), key=lambda x: x[0]))
    print(f"質詢 PDF {sum(len(i) for _, i in details)} 份（收錄 {len(docs)}：{Counter(d['kind'] for d in docs)}）；"
          f"會議紀要 {len(records)} 份，收錄大會 {len(meetings)} 次（{meetings[0]['date']}～{meetings[-1]['date']}）")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid, name in sorted(names.items(), key=lambda x: x[1]):
        a, q = att.get(pid, []), qf.get(pid, [])
        p, m = sum(d["present"] for _, d, _, _ in a), sum(d["meetings"] for _, d, _, _ in a)
        print(f"  {name}（{pid}）出席 {p}／{m}；縣政總質詢紀錄 {sum(d['doc_type'] == GOV_DOC for _, d, _, _ in q)}、"
              f"掃描檔 {sum(d['doc_type'] == WRITTEN_DOC for _, d, _, _ in q)}；改採書面 {len(sw.get(pid, []))}："
              + "、".join(dt for _, _, _, dt in sorted(sw.get(pid, []), key=lambda x: x[3])))
        if any(s in name for s in samples):
            for _, d, url, dt in a:
                print(f"    {d['session']:<12} {dt} {d['present']:>2}／{d['meetings']:<2} {urllib.parse.unquote(url)}")
            for _, d, url, dt in q:
                print(f"    {d['session']} {d['title']} {urllib.parse.unquote(url)}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        load_all()
    check([a for a in sys.argv[1:] if not a.startswith("--")])
