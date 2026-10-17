"""苗栗縣議會第 20 屆（www.mcc.gov.tw「會議記錄」typeid=2626）：逐人縣政總質詢頁碼連結與大會出席（V16）。

每次會議一份 Word 轉出的會議紀錄 PDF（全程逐字紀錄，有文字層），附在詳細頁 iframcirculatedview.php 的
admin/upload/ 下（V16 已定案第 10 點：2026-10-17 使用者放寬此路徑，其他 robots 規則照舊）。pdftotext -layout 每頁以 \\f 分隔，
頁底印刷頁碼與 PDF 頁序相同（parse_record 逐頁核對，不同的印 log），連結用 PDF 頁序 #page=N。

- 縣政總質詢：只收第 1 頁議程寫「縣政總質詢」的會議（部門工作報告日沒有點名，歸屬不可靠，不收）。
  質詢者要同時有 ①主席點名句（主席發言中「請／由／首先是／接著是 … 質詢」、不跨標點的一句裡出現的姓名，見 calls()）與
  ②本人發言標籤（「周議員玉滿質詢:」或「禹耀東議員質詢：」），兩者都有才掛，連到點名之後本人第一個發言標籤所在頁。
  只有一邊的印 log，不掛人；被點名後本人發言不到 MIN_CHARS 字（宣布改書面質詢）的不收。點名句含「聯合」且有多人的，
  是聯合質詢，掛每位列名者並標示同組名單。同一份 PDF 掛在兩次會議時（第 3 次定期會第 25、26 次），只留表頭相符的那次。
  只放標題與 PDF 頁連結，不擷取內文、不摘要（V16 已定案第 6 點）。
- 出席：第 1 頁「出席議員:李議長文斌 張副議長淑芬 … 翁議員杰 等 35 名(請假 2 名)」。第 13、14 次臨時會（2025-03-17 預備會議）起
  才逐人列名（2025-03-17 預備會議起），之前只有人數，不收（SINCE）。只有出席名單、請假只有人數，所以只算「出席 N／M 次」（V16 已定案第 5 點）。
  名單人數與「等 N 名」不符、有讀不出的詞、重複或對不到名錄的名字，整場不收（印 log）；已不在名錄的前議員（FORMER）只在
  期限前接受。任期中遞補的人（任職 fact 沒有起日）從第一次列名的會議起算。每人每會期一筆 fact。
- 姓名：會議紀錄把職稱插在姓名中間（「周議員玉滿」「張副議長淑芬」），還原為全名；溫／温、尙／尚只在本模組比對時視為同字
  （NAME_VARIANTS）。官方錯字只照 NAME_FIX（逐鍵：circulated_id＋原文寫法，附證據）更正，不做模糊比對。
- 日期：官方「時間」有年份誤植（第 7 次定期會第 18、22 次會議寫 114 年），與同會期其他場次的中位數相差超過 45 天時，
  照登官方日期但不當作 fact 日期（比照 kin_book：data.no_date，標題註明官方記載日期）。

UA civic-lens-etl/0.1、同主機間隔 ≥ 1.1 秒、循序。只寫給有苗栗縣議員任職 fact 且有 2026 candidacy 的人；
姓名以 etl.match 的漢字正規化對全部苗栗縣議員名錄，同名或對不到的不收（印 log）。
自我檢查：python3 -m etl.sources.mia_book [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import html
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

from etl.fetch import get
from etl.sources.hua_book import write
from etl.sources.kin_book import GOV_DOC
from etl.sources.kin_book import present_names as kin_present_names
from etl.sources.nwt_book import resolve, roster_index, targets

HOST = "https://www.mcc.gov.tw/"
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "mia"
OFFICE = "mia_councilor"
TERM = 20
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔
LIST_URL = HOST + "iframcirculated_list.php?menu=1765&typeid=2626&Page={}"
VIEW_URL = HOST + "iframcirculatedview.php?menu=1765&typeid=2626&circulated_id={}"
SINCE = "2025-03-17"  # 出席名單逐人列名的第一天（第 13、14 次臨時會預備會議）；之前只有人數

LIST_ITEM = re.compile(r'href="iframcirculatedview\.php\?menu=1765&typeid=2626&circulated_id=(\d+)" title="([^"]*)"')
# 詳細頁的附件；會議紀錄本體的檔名就是會議標題（「第20屆第7次定期會第19次會議.pdf」），其餘是工作報告、報告案、附檔
ATTACH = re.compile(r'<a href="(admin/upload/twgov_file_\d+\.pdf)"[^>]*title="\[開新分頁下載\]([^"]*?)\s*"')
RECORD_FILE = re.compile(rf"^第{TERM}屆.*(?:會議|典禮|大會)\.pdf$")
LIST_SESSION = re.compile(rf"^第{TERM}屆第([\d、]+)次(定期會|臨時會)")
# 會議紀錄（比對去掉空白後的文字）
HEAD = re.compile(r"苗栗縣議會第(\d+)屆第([\d、]*)次(定期會|臨時會)")  # 少數表頭漏了會期次數（「第20屆第次定期會」）
WHEN = re.compile(r"時間[:：﹕](?:民國)?(\d+)年(\d+)月(\d+)日?")
LABEL = re.compile(r"^\S.{0,40}[:：﹕]\s*$")  # 發言者標籤獨占一行、頂格；內文都有縮排
ASK = re.compile(r"^(?:([一-鿿])(?:副議長|議長|議員)([一-鿿]{1,2})|([一-鿿]{2,3})議員)(?:質詢)+$")
CALL = re.compile(r"(?:請|由|首先是|接著是|接下來是)(.*)")  # 套在逐句（不跨標點）上；句中要有「質詢」（或誤植「資詢」）或以「議員」結尾
CLAUSE = re.compile(r"[^。！？；，,]+")
CHAIR_INLINE = re.compile(r"(主席[(（][^)）]{2,8}[)）])[:：﹕]?")  # 主席標籤被排進上一段內文（沒有換行）
PRESENT = re.compile(r"出席議員\s*[:：﹕](.*?)列\s*席", re.S)
PRESENT_N = re.compile(r"(?:等|(?<=\s)議員)?\s*(\d+)\s*名")  # 「等 35 名」；少數寫「議員 36 名」
NAME_VARIANTS = str.maketrans({"溫": "温", "尙": "尚"})  # 主席點名寫「溫俊勇」「黎尙安」，名錄是「温俊勇」「黎尚安」
# 官方錯字（人工審閱，逐鍵）：(circulated_id, 原文寫法) → 姓名
NAME_FIX = {
    # 第 7 次定期會第 19 次會議（115-06-03）p.1 出席欄「張副議長淑」少「芬」：同頁「主席:張副議長淑芬」，名單仍是 35 人、記載 35 名
    (1274, "張副議長淑"): "張淑芬",
    # 第 1 次定期會第 20 次會議（112-05-26）p.33 發言標籤「農楊議員恭林質詢:」多一字：同頁前兩段是「楊議員恭林質詢:」與
    # 農業處長答覆，此段接續同一問題；p.24 主席點名「請楊恭林議員…」（主席點名句仍須相符才掛）
    (802, "農楊議員恭林質詢"): "楊恭林",
}
# 不在本站名錄的前議員：{姓名: 接受到這天為止（不含）}。名單上的這個名字只在期限前接受，之後出現就整場不收。
# 徐永煌：出席名單最後一次列名是第 7 次定期會第 28 次會議（2026-06-16），第 21、22 次臨時會預備會議（2026-08-03）起不再列名，
# 2026-10 議會名錄也沒有他（不在本站名錄，他的質詢不收）
FORMER = {"徐永煌": "2026-08-01"}
MIN_CHARS = 200  # 本人質詢標籤內文合計下限：被點名後只說一句「改為書面質詢」的不算一場口頭質詢

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


def _cached(name, url, refresh):
    path = CACHE / name
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(url))
    return path.read_bytes().decode("cp950", errors="replace")


def flat(text):
    return re.sub(r"\s+", "", text)


# ---------- 清單與附件 ----------

def parse_list(page):
    """清單一頁 → [(circulated_id, 標題)]（不限屆次）。"""
    return [(int(cid), html.unescape(t).strip()) for cid, t in LIST_ITEM.findall(page)]


def record_pdf(view):
    """詳細頁 → 會議紀錄本體的附件路徑（admin/upload/…pdf）；沒有或不只一份回 None。"""
    hits = [u for u, name in ATTACH.findall(view) if RECORD_FILE.match(html.unescape(name).strip())]
    return hits[0] if len(hits) == 1 else None


def load_list(refresh=True):
    """→ [(circulated_id, 標題)]：第 20 屆全部會議紀錄（清單新到舊，翻到出現第 19 屆的那頁為止）。"""
    out = []
    for n in range(100):
        items = parse_list(_cached(f"list/p{n}.html", LIST_URL.format(n), refresh))
        if not items:
            break
        out += [it for it in items if it[1].startswith(f"第{TERM}屆")]
        if any(not t.startswith(f"第{TERM}屆") for _, t in items):
            break
    if not out:
        raise ValueError("苗栗議會會議記錄清單沒有第 20 屆資料")
    return out


def _view(cid):
    return _cached(f"view/{cid}.html", VIEW_URL.format(cid), False)


def record_text(cid, fetch_missing=True):
    """會議紀錄 PDF → 文字（pdftotext -layout，快取 .txt）；沒有附件或沒有快取且 fetch_missing=False 時回 None。"""
    pdf = CACHE / "pdf" / f"{cid}.pdf"
    txt = pdf.with_suffix(".txt")
    if not txt.exists():
        if not pdf.exists():
            if not fetch_missing:
                return None
            rel = record_pdf(_view(cid))
            if rel is None:
                return None
            data = fetch(HOST + rel)
            if data[:4] != b"%PDF":
                raise ValueError(f"苗栗會議紀錄不是 PDF：{cid} {rel}")
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(data)
        txt.write_text(subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, check=True).stdout.decode("utf-8"),
                       encoding="utf-8")
    return txt.read_text(encoding="utf-8")


def list_session(title):
    m = LIST_SESSION.match(title)
    return f"第{TERM}屆第{m[1]}次{m[2]}" if m else None


# ---------- 會議紀錄 ----------

def parse_record(cid, text, log=print):
    """會議紀錄全文 → {session, nth_title, roc, date, gov, present, turns}；讀不到表頭或時間回 None。
    turns：[(標籤, PDF 頁, 去空白後的內文)]；present：(記載人數, [出席欄原文詞]) 或 None（沒有逐人名單）。"""
    pages = text.split("\f")
    first = flat(pages[0])
    head, when = HEAD.search(first), WHEN.search(first)
    if not (head and when):
        return None
    y, mo, d = (int(x) for x in when.groups())
    agenda = first[head.end():first.find("時間")]
    present = None
    head_text = re.sub(r"(?m)^\s*\d+\s*$", "", "\n".join(pages[:2]))  # 出席名單可能跨頁：接第 2 頁、去掉頁碼行
    pm = PRESENT.search(head_text)
    if pm:
        n = PRESENT_N.search(pm[1])
        present = (int(n[1]) if n else None, (pm[1][:n.start()] if n else pm[1]).split())
    for i, p in enumerate(pages):
        lines = [l.strip() for l in p.split("\n") if l.strip()]
        if lines and lines[-1].isdigit() and int(lines[-1]) != i + 1:
            log(f"mia_book：{cid} PDF 第 {i + 1} 頁印刷頁碼是 {lines[-1]}")
    raw, cur = [], None
    for i, p in enumerate(pages):
        for line in p.split("\n"):
            if LABEL.match(line):
                cur = [line.strip().rstrip(":：﹕").strip(), i + 1, ""]
                raw.append(cur)
            elif cur:
                cur[2] += flat(line)
    turns = []
    for label, page, body in raw:
        parts = CHAIR_INLINE.split(body)
        turns.append((label, page, parts[0]))
        turns += [(parts[k], page, parts[k + 1]) for k in range(1, len(parts), 2)]
    return {"session": f"第{int(head[1])}屆第{head[2]}次{head[3]}" if head[2] else None, "roc": f"{y}-{mo:02d}-{d:02d}",
            "date": f"{y + 1911}-{mo:02d}-{d:02d}", "gov": "縣政總質詢" in agenda, "present": present, "turns": turns}


def asker(cid, label):
    """發言標籤 → 質詢者姓名（「周議員玉滿質詢」「禹耀東議員質詢」）；不是議員質詢標籤回 None。"""
    if (cid, label) in NAME_FIX:
        return NAME_FIX[(cid, label)]
    m = ASK.match(label)
    if not m:
        return None
    return m[3] or m[1] + m[2]


def calls(turns, names):
    """主席點名 → [(turn 序號, [姓名], 是否聯合)]；names 是要找的姓名（名錄＋當天發言標籤）。
    逐句（不跨標點）找「請／由／首先是／接著是／接下來是」之後出現的姓名（全名或「周議員玉滿」），句子要有「質詢」
    （或誤植「資詢」），或以「議員」結尾（「接著請許櫻萍議員。」）。"""
    out = []
    forms = {n: {n.translate(NAME_VARIANTS), n[0] + "議員" + n[1:]} for n in names}
    for i, (label, _, body) in enumerate(turns):
        if not label.startswith("主席"):
            continue
        for clause in CLAUSE.findall(body.translate(NAME_VARIANTS)):
            m = CALL.search(clause)
            if not m or not ("質詢" in clause or "資詢" in clause or clause.endswith("議員")):
                continue
            span = m[1]
            hit = sorted((min(span.find(f) for f in fs if f in span), n) for n, fs in forms.items() if any(f in span for f in fs))
            if hit:
                out.append((i, [n for _, n in hit], "聯合" in clause))
    return out


def gov_entries(cid, rec, roster_names, log=print):
    """縣政總質詢的一份會議紀錄 → [{name, page, group, turns}]：主席點名＋本人發言標籤都有的質詢者。"""
    turns = rec["turns"]
    asks = [(i, asker(cid, label)) for i, (label, _, _) in enumerate(turns)]
    asks = [(i, n) for i, n in asks if n]
    labeled = Counter(n for _, n in asks)
    called = calls(turns, set(roster_names) | set(labeled))
    first_call, groups = {}, {}
    # 起點：本人單獨被點名的第一句；只出現在多人句（開場預告名單、聯合質詢）的，用第一次被點名的那句
    for i, ns, joint in sorted(called, key=lambda c: (len(c[1]) > 1, c[0])):
        for n in ns:
            first_call.setdefault(n, i)
    for i, ns, joint in called:
        for n in ns:
            if joint and len(ns) > 1:
                groups.setdefault(n, [])
                groups[n] += [x for x in ns if x not in groups[n]]
    label = f"{rec['session']} {rec['roc']}（{cid}）"
    out = []
    for n, i in first_call.items():
        own = [j for j, x in asks if x == n and j > i]
        if not own:
            log(f"mia_book：縣政總質詢 {label} 主席點名 {n}，之後沒有本人質詢標籤，不收")
            continue
        chars = sum(len(turns[j][2]) for j in own)
        if chars < MIN_CHARS:
            log(f"mia_book：縣政總質詢 {label} {n} 被點名後本人發言只有 {chars} 字（可能改書面質詢），不收")
            continue
        # 連結頁：該場本人第一個質詢標籤（可能在被點名之前就先在別人時間開講）；掛人條件仍是點名之後有本人標籤
        start = next(j for j, x in asks if x == n)
        out.append({"name": n, "page": turns[start][1], "group": groups.get(n, [n]), "turns": len(own)})
    for n, k in labeled.items():
        if n not in first_call:
            log(f"mia_book：縣政總質詢 {label} {n} 有質詢標籤 {k} 段但主席沒有點名，不收")
    return out


def odd_dates(recs):
    """同會期場次日期的中位數相差超過 45 天的 circulated_id（官方年份誤植）。"""
    by = {}
    for cid, r in recs.items():
        by.setdefault(r["session"], []).append(r["date"])
    out = set()
    for cid, r in recs.items():
        ds = sorted(by[r["session"]])
        if abs((date.fromisoformat(r["date"]) - date.fromisoformat(ds[len(ds) // 2])).days) > 45:
            out.add(cid)
    return out


def parse_all(items, texts, log=print):
    """→ {cid: rec}（rec 另加 title、sort_date、odd）。表頭會期與清單標題不同、讀不到表頭的不收。"""
    recs = {}
    for cid, title in items:
        text = texts.get(cid)
        if text is None:
            log(f"mia_book：{cid} {title} 沒有會議紀錄 PDF，不收")
            continue
        rec = parse_record(cid, text, log)
        if rec is None:
            log(f"mia_book：{cid} {title} 讀不到表頭或時間，不收")
            continue
        if rec["session"] is None:
            log(f"mia_book：{cid} {title} 表頭漏了會期次數，以清單標題為準")
        elif rec["session"] != list_session(title):
            log(f"mia_book：{cid} {title} 表頭會期 {rec['session']} 與清單不同，不收")
            continue
        recs[cid] = {**rec, "session": list_session(title), "title": title}
    by_text = {}
    for cid, title in items:
        if cid in recs:
            by_text.setdefault(texts[cid], []).append(cid)
    for cids in by_text.values():
        if len(cids) > 1:  # 同一份檔案掛在不同會議（第 3 次定期會第 25、26 次）：只留表頭次數與標題相同的
            for cid in cids:
                nth = re.search(r"第\s*(\d+)\s*次會議", texts[cid].split("\f")[0])
                if not nth or f"第{nth[1]}次會議" not in recs[cid]["title"]:
                    log(f"mia_book：{cid} {recs[cid]['title']} 與 {cids} 是同一份檔案、表頭不是這次會議，不收")
                    del recs[cid]
    odd = odd_dates(recs)
    medians = {}
    for r in recs.values():
        medians.setdefault(r["session"], []).append(r["date"])
    for cid, r in recs.items():
        if cid in odd:
            log(f"mia_book：{r['title']}（{cid}）官方日期 {r['roc']} 與同會期其他場次相差過大，照登官方日期、不作排序日期")
        ds = sorted(medians[r["session"]])
        recs[cid] = {**r, "odd": cid in odd, "sort_date": ds[len(ds) // 2] if cid in odd else r["date"]}
    return recs


def record_url(cid, page=None):
    rel = record_pdf(_view(cid))
    return HOST + rel + (f"#page={page}" if page else "")


# ---------- 縣政總質詢 ----------

def gov_facts(recs, roster, roster_names, pids, log=print, url=record_url):
    out = {}
    for cid, r in sorted(recs.items(), key=lambda x: x[1]["sort_date"]):
        if not r["gov"]:
            continue
        for e in gov_entries(cid, r, roster_names, log):
            pid, why = resolve(e["name"], roster)
            if not pid:
                log(f"mia_book：縣政總質詢 {r['title']}（{cid}）{e['name']}：{why}，不收")
                continue
            if pid not in pids:
                continue
            group = e["group"]
            joint = f"聯合質詢：{'、'.join(group)}；" if len(group) > 1 else ""
            data = {"term": TERM, "session": r["session"], "doc_type": GOV_DOC, "dept": None,
                    "title": f"縣政總質詢紀錄（{joint}會議紀錄第 {e['page']} 頁起）",
                    "councillors": group, "group_size": len(group), "page": e["page"]}
            if r["odd"]:
                data.update(no_date=True, title=f"{data['title']}（官方記載日期 {r['roc']}）")
            out.setdefault(pid, []).append((f"miagov:{cid}:{pid}", data, url(cid, e["page"]), None if r["odd"] else r["date"]))
    return out


# ---------- 出席 ----------

def present_names(cid, words):
    """出席欄的詞 → [姓名]；讀不出的詞原樣保留（之後的檢查會擋下）。"""
    out = []
    for w in words:
        if (cid, w) in NAME_FIX:
            out.append(NAME_FIX[(cid, w)])
            continue
        names, _ = kin_present_names(w)  # 兩人之間漏了空白（「張副議長淑芬鄭議員秋風」）時依職稱切開
        out += names
    return out


def collect_meetings(recs, roster, log=print):
    """→ [{cid, session, date, present_ids}]（依日期）：SINCE 起、逐人列名且人數相符、每個名字都對得到的會議。"""
    out = []
    for cid, r in sorted(recs.items(), key=lambda x: (x[1]["sort_date"], x[0])):
        if r["sort_date"] < SINCE:
            continue
        label = f"{r['title']}（{cid}，{r['roc']}）"
        n, words = r["present"] or (None, [])
        if not words:
            log(f"mia_book：出席 {label} 沒有逐人出席名單，不列入")
            continue
        if n is None:
            log(f"mia_book：出席 {label} 名單沒有記載人數（「等 N 名」），無法核對，不列入")
            continue
        names = present_names(cid, words)
        if len(names) != n or len(set(names)) != len(names):
            log(f"mia_book：出席 {label} 記載 {n} 名，名單讀到 {len(names)} 個（或有重複），不列入")
            continue
        ids, unknown = set(), []
        for t in names:
            pid, why = resolve(t.translate(NAME_VARIANTS), roster)
            if pid:
                ids.add(pid)
            elif t in FORMER and r["sort_date"] < FORMER[t]:
                pass
            else:
                unknown.append(f"{t}（{why}）")
        if unknown:
            log(f"mia_book：出席 {label} 名單有對不到名錄的人 {'、'.join(unknown)}，不列入")
            continue
        out.append({"cid": cid, "session": r["session"], "date": r["sort_date"], "present_ids": ids})
    return out


def attendance_facts(meetings, pids, replacements=frozenset(), url=record_url):
    """{person_id: [(fact_key, data, url, date)]}：每人每會期一筆，只有出席次數。replacements 從第一次列名的會議起算。"""
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
            data = {"term": TERM, "session": session, "title": f"{session}會議紀錄", "meetings": len(sm),
                    "present": sum(pid in m["present_ids"] for m in sm), "leave": None, "duty": None, "from_lists": True}
            out.setdefault(pid, []).append((f"miaattend:{slug}:{pid}", data, url(sm[0]["cid"]), sm[0]["date"]))
    return out


# ---------- 組成 ----------

def build(conn, items, texts, log=print, url=record_url):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    pids = set()
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"mia_book：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        pids.add(pid)
    names = [re.sub(r"\s.*", "", r[0]) for r in conn.execute(
        "SELECT DISTINCT p.name FROM fact o JOIN person p USING (person_id) "
        "WHERE o.kind = 'office' AND json_extract(o.data, '$.office') = ?", (OFFICE,))]
    recs = parse_all(items, texts, log)
    meetings = collect_meetings(recs, roster, log)
    replacements = {r[0] for r in conn.execute(
        "SELECT person_id FROM fact WHERE kind = 'office' AND json_extract(data, '$.office') = ? AND date IS NULL", (OFFICE,))}
    return ts, recs, meetings, gov_facts(recs, roster, names, pids, log, url), attendance_facts(meetings, pids, replacements, url)


def load_all(refresh=True, progress=False):
    items = load_list(refresh)
    texts = {}
    for i, (cid, title) in enumerate(items):
        texts[cid] = record_text(cid, refresh)
        if progress:
            print(f"mia_book：{i + 1}/{len(items)} {cid} {title}", flush=True)
    return items, texts


def _print_logs(logs, indent=""):
    for line, n in sorted(Counter(logs).items()):
        print(f"{indent}{line}（{n} 次）" if n > 1 else f"{indent}{line}")


def run(conn):
    items, texts = load_all()
    logs = []
    ts, recs, meetings, gf, att = build(conn, items, texts, logs.append)
    _print_logs(logs)
    ng, dg = write(conn, "miagov", gf, "interpellation")
    na, da = write(conn, "miaattend", att, "attendance")
    print(f"mia_book：會議紀錄 {len(items)} 份（縣政總質詢 {sum(r['gov'] for r in recs.values())} 場），{len(gf)} 人 {ng} 筆（刪除 {dg}）；"
          f"出席收錄 {len(meetings)} 場；對象 {len(ts)} 人；出席 {len(att)} 人 {na} 筆（刪除 {da}）")


# ---------- 自我檢查 ----------

def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    items, texts = load_all(refresh=False)
    logs = []
    ts, recs, meetings, gf, att = build(dump_conn(), items, texts, logs.append)
    _print_logs(logs, "  ")
    print("出席會期：", sorted(Counter(m["session"] for m in meetings).items()))
    print(f"會議紀錄 {len(recs)} 份，縣政總質詢 {sum(r['gov'] for r in recs.values())} 場；出席收錄 {len(meetings)} 場"
          f"（{meetings[0]['date']}～{meetings[-1]['date']}）" if meetings else "")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid, name in sorted(names.items(), key=lambda x: x[1]):
        a, g = att.get(pid, []), gf.get(pid, [])
        p, m = sum(d["present"] for _, d, _, _ in a), sum(d["meetings"] for _, d, _, _ in a)
        print(f"  {name}（{pid}）出席 {p}／{m}；縣政總質詢 {len(g)} 場")
        if any(s in name for s in samples):
            for _, d, u, dt in a:
                print(f"    {d['session']:<16} {dt} {d['present']:>2}／{d['meetings']:<2} {u}")
            for _, d, u, dt in g:
                print(f"    {dt} {d['session']} {d['title']} {u}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        load_all(progress=True)
    else:
        check([a for a in sys.argv[1:] if not a.startswith("--")])
