"""屏東縣議會第 20 屆會議紀錄（www.ptcc.gov.tw「議事日程表及會議紀錄」）：施政總質詢日的「質詢議員：」列名（V16）。

清單：?Page=Schedule&Guid=0fbef497-…（每頁 10 筆，GoStartPage=0,10,…），第 20 屆的每份議事日程表（含變更、延長版）
→ 詳細頁 ?Page=ScheduleDetail&Guid=… 每個開會日一列，「會議紀錄」欄是 /lib/GetFile.php?fil_guid=… 的 1–2 頁 Word PDF
（檔名「1150702會議紀錄.pdf」，也有「會議記錄」；審查委員會紀錄檔名有會別，不收）。HTML 註解裡的舊欄位不算。
同一天在原版、變更版日程表各有一個 fil_guid（換版就變），所以以檔名日期去重、fact_key 用「日期＋person_id」；
連結用清單順序第一份日程表的 fil_guid，每次重跑重抓。官網沒有 robots.txt（404）。V16 已定案第 12 點。

- 會議紀錄只是摘要：出席「詳如簽到簿」、施政總質詢「（另錄）」都沒有公開，所以標題寫「會議紀錄列為質詢議員」，
  不暗示有質詢內容；出缺勤不做。
- **只收明文「質詢議員：A、B、C」那一行**（施政總質詢日）；同一個開會段（「時間：」起）裡只列了質詢議員的那幾位，
  每人每天一筆。不收：「發言議員：」（部門報告日）、「原排定質詢議員：」、整句敘述（停會、皆不質詢）；
  同一天有「○○議員採書面質詢」的，列名者若出現在提到書面質詢的那一句就排除；只寫職稱（周議長、盧副議長）或不像姓名的不收。
- PDF 第一個「時間：中華民國 115 年 7 月 2 日」要與檔名日期相同，不同整天不收（印 log）。會期取 PDF 表頭。

UA civic-lens-etl/0.1、同主機間隔 ≥ 1.1 秒、循序。只寫給有屏東縣議員任職 fact 且有 2026 candidacy 的人；
姓名以 etl.match 的正規化對全部屏東縣議員名錄，同名或對不到的不收（印 log）；官方錯字只照 NAME_FIX。
自我檢查：python3 -m etl.sources.pif_book [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import html
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from etl.fetch import get, pdf_text
from etl.sources.hua_book import write
from etl.sources.nwt_book import resolve, roster_index, targets

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "pif"
OFFICE = "pif_councilor"
TERM = 20
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔
HOST = "https://www.ptcc.gov.tw"
LIST_URL = HOST + "/?GoStartPage={start}&Page=Schedule&Guid=0fbef497-8774-a8d4-aaad-417f7831b0ee"
DETAIL_URL = HOST + "/?Page=ScheduleDetail&Guid={guid}"
FILE_URL = HOST + "/lib/GetFile.php?fil_guid={guid}"
DOC_TYPE = "施政總質詢會議紀錄列名"

LIST_ITEM = re.compile(r'<a href="\?Page=ScheduleDetail&Guid=([0-9a-f-]{36})">\s*([^<]+?)\s*<')
ATTACH = re.compile(r"href=/lib/GetFile\.php\?fil_guid=([0-9a-f-]{36}) title='(\d{7})會議[紀記]錄(?:-pdf|\(第\d天\))?\.pdf_PDF格式")  # 官方檔名異寫：「-pdf」「(第1天)」
# 以下都比對 NFKC 正規化後的文字：Word 轉出的 PDF 混有 CJK 相容字（U+F93F「錄」等），全形「：（）」也變半形
HEADER = re.compile(r"屏東縣議會第(\d+)屆第([\d、]+)次(定期|臨時)會")
WHEN = re.compile(r"時間:中華民國(\d+)年(\d+)月(\d+)日")
ASKERS = re.compile(r"^\s*(?:\([一二三四五六七八九十]+\))?\s*質詢議員:(.*)$")
ITEM = re.compile(r"^\s*(?:\([一二三四五六七八九十]+\)|[一二三四五六七八九十]+、)")  # 下一個編號項目：名單到此為止
NAME = re.compile(r"[一-鿿]{2,4}(?: [A-Za-z]+)*")  # 原住民姓名的羅馬拼音（「李紀財 Mulaneng Paliuliu」）
# 官方錯字（人工審閱，逐鍵）：(檔名日期, 寫法) → 姓名
NAME_FIX = {}

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


def _cached(name, url, refresh):
    p = CACHE / name
    if refresh or not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(fetch(url))
    return p.read_bytes()


# ---------- 清單 ----------

def parse_list(page):
    """列表頁 → [(guid, 標題)]（全部屆次）。"""
    return [(g, html.unescape(t)) for g, t in LIST_ITEM.findall(page)]


def parse_detail(page):
    """詳細頁 → [(檔名日期 7 碼, fil_guid)]：「會議紀錄」欄的大會會議紀錄（去掉 HTML 註解；審查會紀錄檔名不符，不收）。"""
    return [(roc, fg) for fg, roc in ATTACH.findall(re.sub(r"<!--.*?-->", "", page, flags=re.S))]


def load_schedules(refresh=True, progress=False):
    """→ [(guid, 標題, 詳細頁 html)]：第 20 屆的議事日程表，清單順序。列表翻到某頁沒有第 20 屆就停。"""
    out = []
    for start in range(0, 1000, 10):
        items = parse_list(_cached(f"list_{start}.html", LIST_URL.format(start=start), refresh).decode("utf-8"))
        mine = [(g, t) for g, t in items if f"第{TERM}屆" in t]
        if not mine:
            break
        out += mine
    if not out:
        raise ValueError("屏東議事日程表清單沒有第 20 屆")
    rows = []
    for g, t in out:
        rows.append((g, t, _cached(f"d_{g}.html", DETAIL_URL.format(guid=g), refresh).decode("utf-8")))
        if progress:
            print(f"pif_book：{t}", flush=True)
    return rows


def day_files(schedules):
    """→ {檔名日期: fil_guid}：同一天以清單順序第一份日程表的為準。"""
    out = {}
    for _, _, page in schedules:
        for roc, fg in parse_detail(page):
            out.setdefault(roc, fg)
    return out


def minutes_text(roc, fil_guid, fetch_missing=True):
    """會議紀錄 PDF → 文字（pdftotext -layout，快取 min_<日期>.txt）；沒有快取且 fetch_missing=False 回 None。"""
    txt = CACHE / f"min_{roc}.txt"
    if not txt.exists():
        if not fetch_missing:
            return None
        data = fetch(FILE_URL.format(guid=fil_guid))
        if data[:4] != b"%PDF":
            raise ValueError(f"屏東會議紀錄不是 PDF：{roc} {fil_guid}")
        (CACHE / f"min_{roc}.pdf").write_bytes(data)
        txt.write_text(pdf_text(data), encoding="utf-8")
    return txt.read_text(encoding="utf-8")


# ---------- 解析 ----------

def flat(text):
    return re.sub(r"\s+", "", text)


def roc_iso(y, m, d):
    return f"{int(y) + 1911}-{int(m):02d}-{int(d):02d}"


def squash(text):
    """去掉空白，但緊鄰拉丁字母的空白留一個（羅馬拼音姓名「李紀財 Mulaneng Paliuliu」）。"""
    latin = re.compile(r"[A-Za-z]")
    return re.sub(r"\s+", lambda m: " " if latin.match(text[m.start() - 1:m.start()] or "-")
                  or latin.match(text[m.end():m.end() + 1] or "-") else "", text)


def written_sentences(lines):
    """提到書面質詢的句子：以編號項目、「質詢議員:」「原排定」與句號切開，避免名單本身被算進去。"""
    parts = re.split(r"。|\([一二三四五六七八九十]+\)|(?<![一-鿿])[一二三四五六七八九十]+、|質詢議員:|原排定", flat("\n".join(lines)))
    return [x for x in parts if "書面" in x]


def asker_lines(lines):
    """「質詢議員:」行，接上換行接續的部分（到空行、下一個編號項目或另一個「X:」行為止）。"""
    out = []
    for i, line in enumerate(lines):
        m = ASKERS.match(line)
        if not m:
            continue
        parts = [m[1]]
        for nxt in lines[i + 1:]:
            if not nxt.strip() or ITEM.match(nxt) or ":" in nxt:
                break
            parts.append(nxt)
        out.append(squash("、".join(parts)))  # 換行也當分隔：有的名單換行處漏了頓號（1120601、1140623）
    return out


def parse_minutes(roc, text, log=print):
    """→ {date, session, names: [列名且沒採書面的姓名]}；日期對不上或讀不到表頭回 None。"""
    text = unicodedata.normalize("NFKC", text)
    f = flat(text)
    h, w = HEADER.search(f), WHEN.search(f)
    if not h or not w or int(h[1]) != TERM:
        log(f"pif_book：{roc} 讀不到第 {TERM} 屆表頭或時間（{'沒有文字層' if len(f) < 50 else '格式不符'}），整天不收")
        return None
    date = roc_iso(*w.groups())
    if date != roc_iso(roc[:3], roc[3:5], roc[5:]):
        log(f"pif_book：{roc} 會議紀錄時間 {'.'.join(w.groups())} 與檔名日期不同，整天不收")
        return None
    session = f"第{TERM}屆第{h[2]}次{h[3]}會"
    lines = text.split("\n")
    written = written_sentences(lines)
    names = []
    for line in asker_lines(lines):
        for m in re.finditer(r"([^、,]*)\(([^)]*)\)", line):
            log(f"pif_book：{roc} 質詢議員「{m[0]}」含括號說明，整段不收")
        for tok in (t.strip() for t in re.split(r"[、,]", re.sub(r"[^、,]*\([^)]*\)", "", line))):
            n = NAME_FIX.get((roc, tok), tok)
            if not tok:
                continue
            if "議長" in tok or not NAME.fullmatch(n):
                log(f"pif_book：{roc} 質詢議員「{tok}」不是姓名（職稱或敘述），不收")
                continue
            if any(flat(n) in x for x in written):
                log(f"pif_book：{roc} {n} 列為質詢議員但同日採書面質詢，不收")
                continue
            if n not in names:
                names.append(n)
    if not names and "原排定" in f:
        log(f"pif_book：{roc} 只有原排定質詢議員或敘述，沒有「質詢議員：」行，不收")
    return {"date": date, "roc": roc, "session": session, "names": names}


def facts(days, files, roster, pids, log=print):
    out = {}
    for d in days:
        for n in d["names"]:
            pid, why = resolve(n, roster)
            if not pid:
                log(f"pif_book：{d['roc']} {n}：{why}，不收")
                continue
            if pid not in pids:
                continue
            group = d["names"]
            title = "施政總質詢（會議紀錄列為質詢議員）"
            if len(group) > 1:
                title += f"；同場列名：{'、'.join(group)}"
            data = {"term": TERM, "session": d["session"], "doc_type": DOC_TYPE, "dept": None, "title": title,
                    "councillors": group, "group_size": len(group)}
            out.setdefault(pid, []).append((f"pifmin:{d['date']}:{pid}", data, FILE_URL.format(guid=files[d["roc"]]), d["date"]))
    return out


def build(conn, files, texts, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    pids = set()
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"pif_book：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        pids.add(pid)
    days = []
    for roc in sorted(files):
        if texts.get(roc) is None:
            log(f"pif_book：{roc} 沒有快取，不收")
            continue
        d = parse_minutes(roc, texts[roc], log)
        if d:
            days.append(d)
    return ts, days, facts(days, files, roster, pids, log)


def load_all(refresh=True, progress=False):
    files = day_files(load_schedules(refresh, progress))
    texts = {}
    for i, (roc, fg) in enumerate(sorted(files.items())):
        texts[roc] = minutes_text(roc, fg, refresh)
        if progress:
            print(f"pif_book：{i + 1}/{len(files)} {roc}", flush=True)
    return files, texts


def _print_logs(logs, indent=""):
    for line, n in sorted(Counter(logs).items()):
        print(f"{indent}{line}（{n} 次）" if n > 1 else f"{indent}{line}")


def run(conn):
    files, texts = load_all()
    logs = []
    ts, days, by_pid = build(conn, files, texts, logs.append)
    _print_logs(logs)
    n, stale = write(conn, "pifmin", by_pid, "interpellation")
    print(f"pif_book：會議紀錄 {len(files)} 天，有質詢議員列名 {sum(bool(d['names']) for d in days)} 天；"
          f"對象 {len(ts)} 人，有紀錄 {len(by_pid)} 人 {n} 筆（刪除 {stale}）")


# ---------- 自我檢查 ----------

def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    files, texts = load_all(refresh=False)
    logs = []
    ts, days, by_pid = build(dump_conn(), files, texts, logs.append)
    _print_logs(logs, "  ")
    listed = [d for d in days if d["names"]]
    print(f"會議紀錄 {len(files)} 天（快取 {sum(t is not None for t in texts.values())}），有質詢議員列名 {len(listed)} 天 "
          f"{sum(len(d['names']) for d in listed)} 人次；對象 {len(ts)} 人，有紀錄 {len(by_pid)} 人 {sum(map(len, by_pid.values()))} 筆")
    for roc, t in sorted(texts.items()):
        if t and "施政總質詢" in flat(t) and not any(d["roc"] == roc and d["names"] for d in days):
            print(f"  施政總質詢日沒有收錄：{roc}")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid in sorted(names, key=names.get):
        if samples and not any(s in names[pid] for s in samples):
            continue
        rows = sorted(by_pid.get(pid, []), key=lambda x: x[3])
        print(f"  {names[pid]} {len(rows)}：" + "、".join(date for _, _, _, date in rows))
        if samples:
            for k, d, u, date in rows:
                print(f"    {k} {d['session']} {d['title']} {u}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        load_all(progress=True)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
