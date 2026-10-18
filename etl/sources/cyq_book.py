"""嘉義縣議會第 20 屆議事錄（ws.cyscc.gov.tw 全冊 PDF）：逐人「質詢與答覆」頁碼連結（V16）。

清單：api.cyscc.gov.tw/1/News_Toggle/54?handler=News（官網「議事錄」專區的 JSON），每個定期會一筆、2–3 個 PDF
（上冊／下冊的命名和內容不一定一致，所以每冊都讀）。V16 已定案第 12 點：2026-10-17 使用者放寬，允許讀取取得清單所需的頁面、
下載 ws.cyscc.gov.tw 上的議事錄 PDF（www 的 robots 是 Disallow: /；ws 主機 robots 404、api 主機沒有 robots）。
PDF 一冊 20–290 MB，用 curl 串流下載到 data/cache/cyq/pdf/，pdftotext -layout 轉成同名 .txt；有 .txt 就不再下載。

- 「質詢與答覆」章：每天一張分隔頁（只有「115.5.26 口頭質詢與答覆」一行），之後每頁頁首「1744 質詢與答覆」或
  「質詢與答覆 1745」。一天＝分隔頁之後、到下一張分隔頁或第一個頁首不是「質詢與答覆」的非空白頁為止（章節結束，後面是臨時會紀錄）。
  當天第一頁的「115.05.26 記錄人：」日期要與分隔頁相同，不同整天不收（印 log）。
- 掛人只用發言標籤（獨占一行的「林岱杰議員：」，全名）。每人每天一筆，當天本人標籤 ≥ MIN_TURNS 段才收
  （只插話一兩句的不算），連到當天本人第一個標籤所在的 PDF 頁 #page=N。質詢時間表是排定名單（有人借時間、改書面），
  只在 check() 對照印出，不拿來掛人。主席點名（「請我們岱杰議員」常只叫名字）不用。
- 印刷頁碼：PDF 頁序和印刷頁碼的差值不固定（每天的分隔頁會讓差值跳 2），所以讀每頁頁首；連結頁的頁首要與當天其他頁首的
  差值一致才採用，否則標題改寫 PDF 頁序（印 log）。
- 序言寫明「本刊質詢及答覆，係依據錄音摘要彙整，未克一一送請發言人校閱」：標題稱「質詢與答覆紀錄」，不稱逐字稿。
  只放標題與 PDF 頁連結，不擷取內文、不摘要（V16 已定案第 6 點）。出缺勤只有「出席：張議長明達等 31 人」，不做。
- 文字層亂碼或掃描的冊（第 7 次定期會上冊：亂碼，沒有質詢章）不收，印 log；check() 列出每冊狀態與每會期是否有質詢章。
- **改採書面質詢**（2026-10-18 使用者決定；書面內容議事錄沒有收錄）：每人每天一筆另一種 doc_type（WRITTEN_DOC），兩個來源：
  ①會議紀錄「貳、縣政總質詢與業務質詢：姜梅紅、蔡政宜（書面質詢）、簡嘉億（書面質詢）等議員」，名字緊接「（書面質詢）」才收，
  也收「（…等議員，蔡政宜議員書面質詢。）」；日期是該份會議紀錄的「時間：中華民國…」，連到紀錄所在 PDF 頁。
  ②質詢與答覆章裡主席（「主席張議長明達：」「陳副議長怡岳：」）的發言：以句號、逗號、頓號切開，一段裡只有一位「○○○議員」接著
  「（他）（要／用／是／也是）書面質詢」（或下一段緊接「他要書面質詢」）才收，連到該頁；「蔡政宜和武清山議員，他們兩位書面質詢」
  要逐一點名且人數與宣布的位數相同才收。「我們副議長的質詢，用書面質詢」這種沒點名的、
  議員自己說「其他的再用書面質詢」都不收。同一天本人有口頭質詢（發言標籤 ≥ MIN_TURNS）的不收書面（印 log）。

UA civic-lens-etl/0.1、同主機間隔 ≥ 1.1 秒、循序。只寫給有嘉義縣議員任職 fact 且有 2026 candidacy 的人；
姓名以 etl.match 的漢字正規化（啟／啓 同字）對全部嘉義縣議員名錄，同名或對不到的不收（印 log）；官方錯字只照 NAME_FIX。
自我檢查：python3 -m etl.sources.cyq_book [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from etl.fetch import UA, get
from etl.sources.hua_book import write
from etl.sources.kin_book import GOV_DOC
from etl.sources.nwt_book import resolve, roster_index, targets

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "cyq"
OFFICE = "cyq_councilor"
TERM = 20
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔
LIST_URL = "https://api.cyscc.gov.tw/1/News_Toggle/54?handler=News&PageSize=100&PageNumber=1"
FILE_URL = re.compile(r"^https://ws\.cyscc\.gov\.tw/001/Upload/1/relfile/62/\d+/[0-9a-f-]+\.pdf$")
SESSION = re.compile(rf"^第{TERM}屆第(\d+)次定期會")
MIN_TURNS = 3  # 當天本人發言標籤下限：只插話一兩句的不算一場質詢

DIVIDER = re.compile(r"^(\d{3})\.(\d{1,2})\.(\d{1,2})口頭質詢與答覆$")  # 分隔頁（去空白後整頁）
HEADER = re.compile(r"^\s*(?:(\d+)\s+質詢與答覆|質詢與答覆\s+(\d+))\s*$")
RECORDER = re.compile(r"(\d{3})\.(\d{1,2})\.(\d{1,2})\s*記錄人")
LABEL = re.compile(r"(?m)^[ \t]{0,3}([一-鿿]{2,4})議員[：:][ \t]*$")
# 改採書面質詢（見模組說明）
MINUTES = re.compile(r"時間：中華民國(\d+)年(\d+)月(\d+)日")
ASK_LIST = re.compile(r"貳、縣政總質詢與業務質詢[：:]?(.*?)(?:參、|$)")
ANNOTATED = re.compile(r"^([一-鿿]{2,4})(?:[（(]書面質詢[)）]|議員書面質詢)(?:等議員)?$")
CHAIR = re.compile(r"^(?:主席)?[一-鿿]?副?議長[一-鿿]{2,3}$")
TURN = re.compile(r"(?m)^[ \t]{0,3}((?:主席)?[一-鿿]{2,10})[：:]")
FILLER = r"(?:(?:好|那|再來是?|接著是?|接下來是?|另外|所以|我們|是|今天)，?)*"
SAY_WRITTEN = r"(?:他|她)?(?:說)?(?:要|是|也是)?(?:用|改用|改)?書面質詢"
CHAIR_ONE = re.compile(rf"^{FILLER}([一-鿿]{{2,4}})議員{SAY_WRITTEN}$")
CHAIR_NAME = re.compile(rf"^{FILLER}([一-鿿]{{2,4}})議員$")
CHAIR_SAY = re.compile(rf"^{SAY_WRITTEN}$")
# 「蔡政宜和武清山議員，他們兩位書面質詢」「今天蔡奇璋議員、林秀琴議員、賴瓊如議員，三位都書面質詢」：點名人數要與宣布的位數相同
CHAIR_GROUP = re.compile(rf"^{FILLER}(?:今天)?((?:[一-鿿]{{2,4}}?(?:議員)?(?:、|和|跟|及))+[一-鿿]{{2,4}}議員)，(?:他們)?(兩|二|三|四)位都?書面質詢$")
COUNT = {"兩": 2, "二": 2, "三": 3, "四": 4}
WRITTEN_DOC = "改採書面質詢（內容未公開）"  # 與 site/app.js 的 WRITTEN_SWITCH 相同
TOC = re.compile(r"(\d{3})\.(\d{1,2})\.(\d{1,2})\s*口頭質詢與答覆\s*\.{3,}")
# 官方錯字（人工審閱，逐鍵）：(檔名 uuid, 標籤寫法) → 姓名
NAME_FIX = {
    # 第 5 次定期會下冊 114.06.17（PDF 第 867 頁起，印刷 1933）發言標籤「翁聰賢傑議員：」94 段多一字：緊接在前的主席發言是
    # 「來，聰賢。」；當天開場（PDF 第 791 頁）主席唸的排定名單有「莊竣傑議員、翁聰賢議員」；當天沒有其他「翁聰賢議員：」標籤
    ("7c20b639-942b-4aff-ace0-22a0d2ac336b", "翁聰賢傑"): "翁聰賢",
}

_last = {}


def fetch(url):
    host = urlsplit(url).netloc
    wait = _last.get(host, 0.0) + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return get(url)
    finally:
        _last[host] = time.monotonic()


def download(url, dest):
    """大檔用 curl 串流寫檔（不整個讀進記憶體）；先寫 .part，完整才改名。"""
    host = urlsplit(url).netloc
    wait = _last.get(host, 0.0) + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    part = dest.with_suffix(".part")
    try:
        subprocess.run(["curl", "-sS", "-f", "-L", "--max-time", "1500", "-A", UA, "-o", str(part), url], check=True)
    finally:
        _last[host] = time.monotonic()
    with open(part, "rb") as f:
        if f.read(4) != b"%PDF":
            raise ValueError(f"嘉義縣議事錄不是 PDF：{url}")
    part.rename(dest)


# ---------- 清單 ----------

def parse_list(data):
    """News_Toggle/54 JSON → [{sn, session, files: [(檔名, url)]}]：第 20 屆定期會（依會期次數）。"""
    out = []
    for row in data["Data"]:
        m = SESSION.match(row["主題"])
        if not m:
            continue
        files = []
        for f in json.loads(re.search(r"OpenRelFile\((\{.*\})\);?$", row["Path"])[1])["files"]:
            if not FILE_URL.match(f["FileName"]):
                raise ValueError(f"嘉義縣議事錄附件網址格式不符：{f['FileName']}")
            files.append((f["SrcFileName"], f["FileName"]))
        out.append({"sn": row["S_N"], "session": f"第{TERM}屆第{int(m[1])}次定期會", "nth": int(m[1]), "files": files})
    return sorted(out, key=lambda v: v["nth"])


def load_list(refresh=True):
    path = CACHE / "toggle54.json"
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(LIST_URL))
    out = parse_list(json.loads(path.read_text(encoding="utf-8")))
    if not out:
        raise ValueError("嘉義縣議事錄清單沒有第 20 屆定期會")
    return out


def volume_pages(url, fetch_missing=True):
    """議事錄 PDF → 逐頁文字（pdftotext -layout，\\f 分頁，快取 .txt）；沒有快取且 fetch_missing=False 回 None。"""
    pdf = CACHE / "pdf" / url.rsplit("/", 1)[1]
    txt = pdf.with_suffix(".txt")
    if not txt.exists():
        if not pdf.exists():
            if not fetch_missing:
                return None
            pdf.parent.mkdir(parents=True, exist_ok=True)
            download(url, pdf)
        tmp = txt.with_suffix(".tmp")
        subprocess.run(["pdftotext", "-layout", "-q", str(pdf), str(tmp)], check=True)
        tmp.rename(txt)
    return txt.read_text(encoding="utf-8").split("\f")


# ---------- 解析 ----------

def flat(text):
    return re.sub(r"\s+", "", text)


def roc_iso(y, m, d):
    return f"{int(y) + 1911}-{int(m):02d}-{int(d):02d}"


def text_status(pages):
    """沒有質詢章時說明原因：掃描（幾乎沒字）、亂碼（非中文的怪字比中文多）或正常文字但沒有這章。"""
    body = "".join(pages)
    cjk = sum(1 for c in body if 0x4E00 <= ord(c) <= 0x9FFF)
    odd = sum(1 for c in body if 0x100 <= ord(c) < 0x4000 or c == "�")
    if len(flat(body)) < 20 * len(pages):
        return "掃描影像（幾乎沒有文字層）"
    if odd > cjk:
        return "文字層亂碼"
    return "沒有質詢與答覆章"


def page_header(page):
    """頁首印刷頁碼；第一個非空白行不是「質詢與答覆」頁首回 None。"""
    line = next((l for l in page.split("\n") if l.strip()), "")
    m = HEADER.match(line)
    return int(m[1] or m[2]) if m else None


def parse_days(pages, label="", log=print):
    """→ [{date, roc, pages: [(PDF 頁, 印刷頁或 None, 文字)]}]：每天從分隔頁到下一張分隔頁或章節結束。"""
    out, cur = [], None
    for i, p in enumerate(pages):
        m = DIVIDER.match(flat(p))
        if m:
            cur = {"date": roc_iso(*m.groups()), "roc": ".".join(m.groups()), "pages": []}
            out.append(cur)
            continue
        if cur is None or not flat(p):
            continue
        printed = page_header(p)
        if printed is None:
            log(f"cyq_book：{label} PDF 第 {i + 1} 頁頁首不是「質詢與答覆」，{cur['roc']} 到此為止")
            cur = None
            continue
        cur["pages"].append((i + 1, printed, p))
    days = []
    for d in out:
        first = d["pages"][0][2] if d["pages"] else ""
        r = RECORDER.search(first)
        if not r or roc_iso(*r.groups()) != d["date"]:
            log(f"cyq_book：{label} {d['roc']} 當天第一頁的記錄日期 {'.'.join(r.groups()) if r else '（讀不到）'} 與分隔頁不同，整天不收")
            continue
        days.append(d)
    return days


def printed_page(day, page, label="", log=print):
    """連結頁的印刷頁碼：頁首與當天多數頁首的差值一致才採用，否則 None（印 log）。"""
    offsets = Counter(pr - pg for pg, pr, _ in day["pages"])
    off = offsets.most_common(1)[0][0]
    pr = next(pr for pg, pr, _ in day["pages"] if pg == page)
    if pr - page != off:
        log(f"cyq_book：{label} {day['roc']} PDF 第 {page} 頁頁首 {pr} 與當天其他頁首差值不同，標題改用 PDF 頁序")
        return None
    return pr


def asker(file_id, name):
    return NAME_FIX.get((file_id, name), name)


def day_entries(day, file_id, label="", log=print):
    """→ [{name, page, printed, turns}]：當天本人發言標籤 ≥ MIN_TURNS 段的議員，連到第一個標籤所在頁。"""
    first, turns = {}, Counter()
    for pg, _, text in day["pages"]:
        for m in LABEL.finditer(text):
            n = asker(file_id, m[1])
            first.setdefault(n, pg)
            turns[n] += 1
    out = []
    for n, pg in first.items():
        if turns[n] < MIN_TURNS:
            log(f"cyq_book：{label} {day['roc']} {n} 發言標籤只有 {turns[n]} 段（插話），不收")
            continue
        out.append({"name": n, "page": pg, "printed": printed_page(day, pg, label, log), "turns": turns[n]})
    return out


def minutes_written(pages, label="", log=print):
    """會議紀錄 →[{date, roc, page, name}]：縣政總質詢名單上緊接「（書面質詢）」的議員。"""
    out = []
    for i, p in enumerate(pages):
        f = flat(p)
        heads = list(MINUTES.finditer(f))
        for k, h in enumerate(heads):
            block = f[h.end():heads[k + 1].start() if k + 1 < len(heads) else len(f)]
            m = ASK_LIST.search(block)
            if not m or "書面" not in m[1]:
                continue
            body = m[1].rstrip("。")
            if body[:1] in "（(":  # 整段括起來：「（蔡信典…等議員，蔡政宜議員書面質詢。）」
                body = re.sub(r"。?[）)]$", "", body[1:])
            for tok in re.split(r"[、，,]", body):
                if "書面" not in tok:
                    continue
                n = ANNOTATED.match(re.sub(r"等議員$", "", tok))
                if not n:
                    log(f"cyq_book：{label} PDF 第 {i + 1} 頁會議紀錄「{tok}」切不出姓名，不收")
                    continue
                out.append({"date": roc_iso(*h.groups()), "roc": ".".join(h.groups()), "page": i + 1, "name": n[1], "how": "會議紀錄"})
    return out


def chair_written(day, label="", log=print):
    """質詢與答覆章當天主席發言中逐一點名改採書面質詢的議員 → [{date, roc, page, name}]。"""
    out = []
    for pg, _, text in day["pages"]:
        turns = list(TURN.finditer(text))
        for k, t in enumerate(turns):
            if not CHAIR.match(t[1]):
                continue
            body = flat(text[t.end():turns[k + 1].start() if k + 1 < len(turns) else len(text)])
            for sent in re.split(r"[。！？；]", body):
                if "書面" not in sent:
                    continue
                g = CHAIR_GROUP.match(sent)
                if g:
                    names = [re.sub(r"議員$", "", x) for x in re.split(r"、|和|跟|及", g[1])]
                    if len(names) == COUNT[g[2]] and all(re.fullmatch(r"[一-鿿]{2,4}", n) for n in names):
                        out += [{"date": day["date"], "roc": day["roc"], "page": pg, "name": n, "how": "主席"} for n in names]
                        continue
                parts = re.split(r"[，、,]", sent)
                found = False
                for j, part in enumerate(parts):
                    one = CHAIR_ONE.match(part)
                    name = CHAIR_NAME.match(part)
                    if one or (name and j + 1 < len(parts) and CHAIR_SAY.match(parts[j + 1])):
                        out.append({"date": day["date"], "roc": day["roc"], "page": pg, "name": (one or name)[1], "how": "主席"})
                        found = True
                if not found and "書面質詢" in sent:
                    log(f"cyq_book：{label} {day['roc']} 主席提到書面質詢「{sent[:60]}」但沒有逐一點名，不收")
    return out


def toc_days(pages):
    """目錄（前 20 頁）列的質詢日期；沒有乾淨目錄回空集合。"""
    return {roc_iso(*m.groups()) for p in pages[:20] for m in TOC.finditer(p)}


def collect(volumes, texts, log=print):
    """→ (entries [{session, date, roc, url, file, name, page, printed, turns}], status {url: 狀態},
    written [{session, date, roc, url, page, name, how}])。"""
    entries, status, written = [], {}, []
    for v in volumes:
        found, listed = set(), set()
        for fname, url in v["files"]:
            pages = texts.get(url)
            label = f"{v['session']} {fname}"
            if pages is None:
                status[url] = "沒有快取"
                log(f"cyq_book：{label} 沒有快取，不收")
                continue
            listed |= toc_days(pages)
            written += [{**w, "session": v["session"], "url": url} for w in minutes_written(pages, label, log)]
            days = parse_days(pages, label, log)
            if not days:
                status[url] = text_status(pages)
                log(f"cyq_book：{label} {status[url]}，不收")
                continue
            status[url] = f"質詢與答覆 {len(days)} 天"
            file_id = url.rsplit("/", 1)[1][:-4]
            for d in days:
                found.add(d["date"])
                written += [{**w, "session": v["session"], "url": url} for w in chair_written(d, label, log)]
                for e in day_entries(d, file_id, label, log):
                    entries.append({**e, "session": v["session"], "date": d["date"], "roc": d["roc"], "url": url, "file": fname})
        if not found:
            log(f"cyq_book：{v['session']} 每一冊都沒有可讀的質詢與答覆章，整個會期不收")
        for d in sorted(listed - found):
            log(f"cyq_book：{v['session']} 目錄列有 {d} 口頭質詢與答覆，但沒有解析到")
    return entries, status, written


def facts(entries, roster, pids, log=print):
    out, seen = {}, set()
    for e in entries:
        pid, why = resolve(e["name"], roster)
        if not pid:
            log(f"cyq_book：{e['session']} {e['roc']} {e['name']}：{why}，不收")
            continue
        if pid not in pids:
            continue
        k = f"cyqbook:{e['date']}:{pid}"
        if k in seen:
            log(f"cyq_book：{e['roc']} {e['name']} 在兩冊都有質詢章，只留第一冊")
            continue
        seen.add(k)
        where = f"議事錄第 {e['printed']} 頁起" if e["printed"] else f"議事錄 PDF 第 {e['page']} 頁起"
        data = {"term": TERM, "session": e["session"], "doc_type": GOV_DOC, "dept": None,
                "title": f"質詢與答覆紀錄（{where}；依錄音摘要整理）",
                "councillors": [e["name"]], "group_size": 1, "page": e["page"], "printed_page": e["printed"]}
        out.setdefault(pid, []).append((k, data, f"{e['url']}#page={e['page']}", e["date"]))
    return out


def written_facts(written, entries, roster, pids, log=print):
    """記載改採書面質詢：每人每天一筆（會議紀錄優先，其次主席發言）；同一天本人有口頭質詢的不收。"""
    oral = {(e["date"], resolve(e["name"], roster)[0]) for e in entries}
    out, seen = {}, set()
    for w in sorted(written, key=lambda w: (w["date"], w["how"] != "會議紀錄")):
        pid, why = resolve(w["name"], roster)
        if not pid:
            log(f"cyq_book：{w['roc']} 書面質詢 {w['name']}：{why}，不收")
            continue
        if pid not in pids or (w["date"], pid) in seen:
            continue
        if (w["date"], pid) in oral:
            log(f"cyq_book：{w['roc']} {w['name']} 記載書面質詢，但當天也有口頭質詢的發言標籤，書面不收")
            continue
        seen.add((w["date"], pid))
        src = "會議紀錄記載書面質詢" if w["how"] == "會議紀錄" else "主席宣布改採書面質詢"
        data = {"term": TERM, "session": w["session"], "doc_type": WRITTEN_DOC, "dept": None,
                "title": f"縣政總質詢：{src}（書面內容議會未公開）", "link_label": f"議事錄 PDF 第 {w['page']} 頁",
                "councillors": [w["name"]], "group_size": 1, "page": w["page"]}
        out.setdefault(pid, []).append((f"cyqwr:{w['date']}:{pid}", data, f"{w['url']}#page={w['page']}", w["date"]))
    return out


def build(conn, volumes, texts, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    pids = set()
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"cyq_book：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        pids.add(pid)
    entries, status, written = collect(volumes, texts, log)
    return ts, entries, status, facts(entries, roster, pids, log), written_facts(written, entries, roster, pids, log)


def load_all(refresh=True, progress=False):
    volumes = load_list(refresh)
    texts = {}
    for v in volumes:
        for fname, url in v["files"]:
            texts[url] = volume_pages(url, refresh)
            if progress:
                print(f"cyq_book：{v['session']} {fname} {'有' if texts[url] else '沒有'}快取", flush=True)
    return volumes, texts


def _print_logs(logs, indent=""):
    for line, n in sorted(Counter(logs).items()):
        print(f"{indent}{line}（{n} 次）" if n > 1 else f"{indent}{line}")


def run(conn):
    volumes, texts = load_all()
    logs = []
    ts, entries, status, by_pid, wr = build(conn, volumes, texts, logs.append)
    _print_logs(logs)
    n, stale = write(conn, "cyqbook", by_pid, "interpellation")
    nw, sw = write(conn, "cyqwr", wr, "interpellation")
    print(f"cyq_book：議事錄 {len(volumes)} 個會期 {len(texts)} 冊；質詢場次 {len(entries)} 筆；對象 {len(ts)} 人，"
          f"有紀錄 {len(by_pid)} 人 {n} 筆（刪除 {stale}）；記載改採書面質詢 {len(wr)} 人 {nw} 筆（刪除 {sw}）")


def run_written(conn):
    """局部補跑只寫「記載改採書面質詢」（不動口頭質詢紀錄）：只讀快取。"""
    volumes, texts = load_all(refresh=False)
    logs = []
    *_, wr = build(conn, volumes, texts, logs.append)
    _print_logs(logs)
    nw, sw = write(conn, "cyqwr", wr, "interpellation")
    print(f"cyq_book：記載改採書面質詢 {len(wr)} 人 {nw} 筆（刪除 {sw}）")


# ---------- 自我檢查 ----------

def timetable(text):
    """質詢時間表（pdftotext -layout，第 7 次定期會）→ {日期: {姓名}}：空行分隔的每一段有一個日期，段內的姓名都排在該日（附註「※」以下不算）。"""
    out = {}
    for block in re.split(r"\n\s*\n", text):
        block = block.split("※")[0]  # 表下的附註
        m = re.search(r"(\d{3})\.(\d{2})\.(\d{2})", block)
        if m:
            out[roc_iso(*m.groups())] = set(re.findall(r"[一-鿿]{2,4}", re.sub(r"副?議長", "", block))) - {"星期"}
    return out


def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    volumes, texts = load_all(refresh=False)
    logs = []
    ts, entries, status, by_pid, wr = build(dump_conn(), volumes, texts, logs.append)
    _print_logs(logs, "  ")
    for v in volumes:
        for fname, url in v["files"]:
            print(f"  {v['session']} {fname}：{status[url]}")
    days = Counter(e["date"] for e in entries)
    print(f"質詢場次 {len(entries)} 筆（{len(days)} 天）；對象 {len(ts)} 人，有紀錄 {len(by_pid)} 人 "
          f"{sum(map(len, by_pid.values()))} 筆")
    qt = CACHE / "qtime_s7.pdf"
    if qt.exists():
        sched = timetable(subprocess.run(["pdftotext", "-layout", str(qt), "-"], capture_output=True, check=True).stdout.decode())
        for d, names in sorted(sched.items()):
            spoke = {e["name"] for e in entries if e["date"] == d}
            print(f"  時間表 {d}：排定沒發言 {sorted(names - spoke)}；發言沒排定 {sorted(spoke - names)}")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in sorted(names, key=names.get):
        if samples and not any(s in names[pid] for s in samples):
            continue
        rows = sorted(by_pid.get(pid, []), key=lambda x: x[3])
        print(f"  {names[pid]} {len(rows)}：" + "、".join(f"{date}#{d['page']}({d['printed_page']})" for _, d, _, date in rows)
              + (f"；書面 {len(wr[pid])}：" + "、".join(f"{date}#{d['page']}{d['title'][6:8]}" for _, d, _, date in sorted(wr[pid], key=lambda x: x[3])) if pid in wr else ""))
        if samples:
            for _, d, u, date in rows:
                print(f"    {date} {d['session']} {d['title']} {u}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        load_all(progress=True)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
