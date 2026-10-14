"""金門縣議會第 8 屆（agenda.kmcc.gov.tw「議事資訊整合查詢」）：縣政總質詢紀錄與大會出席（V16）。

- 縣政總質詢紀錄：/CouncilManage/AgendaGovMinutes 清單（GET，SeNumber=8，一頁列完）每列一場，欄位「質詢議員」列出本場質詢的議員，
  詳細頁 Detail/<GUID> 是全文（不需 cookie）。每場每位質詢議員一筆 fact，只連詳細頁、不擷取全文、不摘要（V16 已定案第 6 點）。
  「主席」欄也有議員名字，歸屬只看「質詢議員」欄，加上詳細頁全文開頭的「質詢議員：」行（清單欄會漏列遞補議員）與人工審閱清單
  data/kin_askers.csv（兩處都漏列的，附發言開頭作依據）。全文中名錄議員被請發言、或以發言人身分（非主席欄）出現 3 段以上
  卻不在上述名單時，只印「待審閱」log、不歸屬；審閱後加進 kin_askers.csv（add 或 not_asker）。官方日期與同會期其他場次不在同一年（113-12 定期會有一場寫 114-12-11）時，
  照登官方日期但不當作排序日期（fact date 留空，頁面改寫會期）。
- 出席：/CouncilManage/AgendaMinutes 清單每次會議一份「會議紀錄摘要」PDF（/ServerFile/Get/<GUID>，有文字層），
  「三、出席：議員 N 人」後列出席議員（「洪議長允典」「歐陽副議長儀雄」「董議員森堡」）。只有出席名單、沒有請假名單，
  所以只算「出席 N／M 次」（V16 已定案第 5 點，比照新北）。聯席審查的紀錄格式相同、全體議員出席，一併計入；分組審查委員會、
  會勘與 113-12 的總質詢紀錄 PDF 沒有「議員 N 人」，不列入。行尾漏了頓號時依職稱切開（切開後人數仍要相符）。名單人數和「N 人」不符、或名單有對不到名錄的人時，該次會議不收（印 log）；
  例外是已離職的前議員（FORMER），只在遞補者第一次列名之前的會議接受。
  任期中遞補的人（任職 fact 沒有起日）從第一次列名的會議起算（臺東的教訓）。每人每會期一筆 fact。

robots.txt 404；著作權聲明允許註明出處後合理利用（V16）。
只寫給有金門縣議員任職 fact 且有 2026 candidacy 的人；姓名以 etl.match 的漢字正規化對全部金門縣議員名錄，名錄同名或對不到的不收（印 log）。
自我檢查：python3 -m etl.sources.kin_book [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import csv
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
from etl.sources.nwt_book import TITLE_AFTER, TITLE_INSIDE, resolve, roster_index, targets

HOST = "https://agenda.kmcc.gov.tw"
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "kin"
ASKERS = ROOT / "data" / "kin_askers.csv"
OFFICE = "kin_councilor"
TERM = 8
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔（robots.txt 404，V16）
LIST_URL = HOST + "/CouncilManage/{}?IsAlreadySearch=True&SeNumber=" + str(TERM) + "&page=1&pageSize=500"

ROW = re.compile(r'<tr id="Item_([0-9a-f-]{36})">(.*?)</tr>', re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
FILE = re.compile(r'href="/ServerFile/Get/([0-9a-f-]{36})"')
ROC_DATE = re.compile(r"^(\d{2,3})-(\d\d)-(\d\d)$")
NTH = re.compile(r"^第(\d+)次$")
# 會議紀錄摘要（比對去掉空白後的文字）
PRESENT = re.compile(r"三、出席：議員(\d+)人(.*?)四、列席")
NAME = re.compile(r"^[一-鿿]{2,5}$")
NOTE = re.compile(r"[（(][^）)]*[）)]")
# 出席名單一人一個「姓＋職稱＋名」；行尾漏了頓號時兩人會黏在一起（「石議員永城董議員森堡」），依職稱切開：
# 名取 1–2 字（先試 2 字），且後面必須接下一個「姓＋職稱」或結尾
PERSON = re.compile(r"([一-鿿]{1,2}?)(?:副議長|議長|議員)([一-鿿]{1,2})(?=[一-鿿]{1,2}(?:副議長|議長|議員)|$)")
DETAIL_ASKERS = re.compile(r"質詢紀錄</span>\s*<span[^>]*>\s*質詢議員[：:]([^\n<]*)")
GOV_DOC = "縣政總質詢紀錄"
SPEAKER = re.compile(r"^\s*(主席)?([一-鿿]{1,2}?)(?:副議長|議長|議員)([一-鿿]{1,2})：\s*$", re.M)
# 會議紀錄名單上已離職的前議員：{姓名: 遞補者}。名單上的這個名字只在遞補者第一次列名之前的會議接受，之後出現就整次會議不收
# （2024-12-19 聯席審查仍列楊育菡，吳佩雯 2024-05-30 起列名）
FORMER = {"楊育菡": "吳佩雯"}

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


def _text(cell):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", cell))).strip()


def roc(s):
    """「113-12-11」→ 「2024-12-11」；格式不對 raise。"""
    m = ROC_DATE.match(s)
    if not m:
        raise ValueError(f"金門日期格式未知：{s!r}")
    y, mo, d = m.groups()
    return f"{int(y) + 1911}-{mo}-{d}"


# ---------- 清單 ----------

def parse_rows(page):
    """清單頁 → [{id, term, nth, kind, date, chair, cells, files}]；每列都要有屆、次、會別、日期，否則 raise（不猜）。"""
    out = []
    for gid, row in ROW.findall(page):
        cells = [_text(c) for c in CELL.findall(row)]
        if len(cells) < 7 or cells[0] != f"第{TERM}屆" or not NTH.match(cells[1]) or cells[2] not in ("定期會", "臨時會"):
            raise ValueError(f"金門清單列格式未知：{cells}")
        out.append({"id": gid, "nth": int(NTH.match(cells[1]).group(1)), "kind": cells[2], "roc": cells[3], "date": roc(cells[3]),
                    "chair": cells[4], "cells": cells, "files": FILE.findall(row)})
    return out


def load_list(name, refresh=True):
    """name：AgendaGovMinutes（縣政總質詢紀錄）或 AgendaMinutes（會議紀錄）。快取 data/cache/kin/<name>.html。"""
    path = CACHE / f"{name}.html"
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(LIST_URL.format(name)))
    rows = parse_rows(path.read_text(encoding="utf-8"))
    if not rows:
        raise ValueError(f"金門 {name} 清單沒有第 {TERM} 屆資料")
    return rows


def file_url(file_id):
    return f"{HOST}/ServerFile/Get/{file_id}"


def detail_url(gid):
    return f"{HOST}/CouncilManage/AgendaGovMinutes/Detail/{gid}"


def minutes_text(file_id, fetch_missing=True):
    """會議紀錄摘要 PDF → 文字（pdftotext -layout，快取）；沒有快取且 fetch_missing=False 時回 None。"""
    txt = CACHE / "raw" / f"{file_id}.txt"
    if not txt.exists():
        pdf = CACHE / "pdf" / f"{file_id}.pdf"
        if not pdf.exists():
            if not fetch_missing:
                return None
            data = fetch(file_url(file_id))
            if data[:4] != b"%PDF":
                raise ValueError(f"金門會議紀錄不是 PDF：{file_id}")
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(data)
        out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, check=True).stdout.decode("utf-8")
        txt.parent.mkdir(parents=True, exist_ok=True)
        txt.write_text(out, encoding="utf-8")
    return txt.read_text(encoding="utf-8")


def detail_page(gid, fetch_missing=True):
    """縣政總質詢紀錄詳細頁（快取 data/cache/kin/detail/<GUID>.html）；沒有快取且 fetch_missing=False 時回 None。"""
    path = CACHE / "detail" / f"{gid}.html"
    if not path.exists():
        if not fetch_missing:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(detail_url(gid)))
    return path.read_text(encoding="utf-8")


def norm(text):
    return re.sub(r"\s", "", text)


def bare(name):
    """「洪議長允典」「歐陽副議長儀雄」「董議員森堡」「董森堡議員」→ 姓名；沒有職稱回原字串。"""
    m = TITLE_INSIDE.match(name)
    return m.group(1) + m.group(2) if m else TITLE_AFTER.sub("", name)


def split_names(text):
    return [bare(t) for t in re.split(r"[、，,]", text) if t]


# ---------- 縣政總質詢紀錄 ----------

def detail_askers(page):
    """詳細頁全文開頭「質詢議員：王議員國代、吳議員佩雯」→ 姓名；沒有這一行回 []。
    清單的「質詢議員」欄會漏掉遞補議員（2026-10 實測：113-12-10 兩場漏了吳佩雯），所以兩邊合併。"""
    m = DETAIL_ASKERS.search(page or "")
    return split_names(norm(html.unescape(m.group(1)))) if m else []


def odd_dates(rows):
    """同會期場次日期的中位數相差超過 45 天的列 id（例：113-12 定期會有一場寫 114-12-11，應是誤植）。"""
    by_session = {}
    for r in rows:
        by_session.setdefault((r["nth"], r["kind"]), []).append(r["date"])
    out = set()
    for r in rows:
        ds = sorted(by_session[(r["nth"], r["kind"])])
        mid = ds[len(ds) // 2]
        if abs((date.fromisoformat(r["date"]) - date.fromisoformat(mid)).days) > 45:
            out.add(r["id"])
    return out


def session_name(r):
    return f"第{TERM}屆第{r['nth']}次{r['kind']}"


def load_askers(path=ASKERS):
    """data/kin_askers.csv（人工審閱）：detail_guid、name、decision、evidence（≤20 字的請發言或發言開頭）→ {guid: {"add": [姓名], "not_asker": [姓名]}}。
    add：清單欄與詳細頁開頭都漏列的質詢議員，照收；not_asker：偵測到但審閱後不是質詢（例：散會前一句補充），不歸屬也不再列待審閱。"""
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["decision"] not in ("add", "not_asker") or len(r["evidence"]) > 20:
                raise ValueError(f"kin_askers.csv 格式不對：{r}")
            out.setdefault(r["detail_guid"], {"add": [], "not_asker": []})[r["decision"]].append(r["name"])
    return out


def suspects(page, roster_names, covered):
    """詳細頁全文 → [(姓名, 依據)]：名錄上的議員有人請他發言（「王秀玉議員請發言」「洪成發洪議員請發言」），或以發言人身分
    （不是主席）出現至少 3 次，卻不在 covered（清單欄＋詳細頁開頭＋人工清單）。只印 log 供人工審閱，不歸屬。"""
    i = (page or "").find("質詢紀錄</span>")
    if i < 0:
        return []
    text = html.unescape(re.sub(r"<[^>]+>", "", page[i:]))
    turns = Counter(m.group(2) + m.group(3) for m in SPEAKER.finditer(text) if not m.group(1))
    flat = norm(text)
    out = []
    for name in roster_names:
        if name in covered:
            continue
        if re.search(re.escape(name) + r"[一-鿿]{0,2}議員，?請發言", flat):
            out.append((name, "被請發言"))
        elif turns[name] >= 3:
            out.append((name, f"發言 {turns[name]} 段"))
    return out


def gov_rows(rows, details, log=print, askers=None, roster_names=()):
    """→ [{id, session, date（日期異常時 None）, roc, names}]：names 是清單欄、詳細頁開頭「質詢議員：」與人工清單
    data/kin_askers.csv 合併後的質詢議員（依出現順序、不重複）。roster_names 有值時另跑 suspects() 印出待審閱的人。"""
    askers = load_askers() if askers is None else askers
    odd = odd_dates(rows)
    out = []
    for r in rows:
        listed = split_names(norm(r["cells"][6]))
        names = list(listed)
        for n in detail_askers(details.get(r["id"])):
            if n not in names:
                names.append(n)
                log(f"kin_book：縣政總質詢 {r['roc']} 詳細頁列 {n}，清單欄沒有，照詳細頁收")
        reviewed = askers.get(r["id"], {"add": [], "not_asker": []})
        for n in reviewed["add"]:
            if n not in names:
                names.append(n)
                log(f"kin_book：縣政總質詢 {r['roc']} 人工清單補 {n}")
        if details.get(r["id"]) is None:
            log(f"kin_book：縣政總質詢 {r['roc']} 詳細頁未取得，只用清單欄")
        chairs = split_names(norm(r["cells"][4]).replace("分別主持", ""))  # 主席欄不算質詢議員（主持時的發言不一定標「主席」）
        for n, why in suspects(details.get(r["id"]), roster_names, set(names + chairs + reviewed["not_asker"])):
            log(f"kin_book：縣政總質詢 {r['roc']}（{r['id']}）{n} {why}，不在質詢議員名單，待審閱（未歸屬）")
        if not names:
            log(f"kin_book：縣政總質詢 {r['roc']}（{r['id']}）沒有質詢議員，不收")
            continue
        if r["id"] in odd:
            log(f"kin_book：縣政總質詢 {session_name(r)} {r['roc']} 與同會期其他場次日期相差過大，照登官方日期、不作排序日期")
        out.append({"id": r["id"], "session": session_name(r), "nth": r["nth"], "kind": r["kind"],
                    "date": None if r["id"] in odd else r["date"], "roc": r["roc"], "names": names})
    return out


def gov_facts(govs, roster, pids, log=print):
    out = {}
    for g in govs:
        for name in g["names"]:
            pid, why = resolve(name, roster)
            if not pid:
                log(f"kin_book：縣政總質詢 {g['roc']} {name}：{why}")
                continue
            if pid not in pids:
                continue
            others = "、".join(g["names"])
            data = {"term": TERM, "session": g["session"], "doc_type": GOV_DOC, "dept": None, "councillors": g["names"],
                    "title": f"縣政總質詢紀錄（本場質詢議員：{others}）"}
            if g["date"] is None:
                data.update(no_date=True, title=f"{data['title']}（官方記載日期 {g['roc']}）")
            out.setdefault(pid, []).append((f"kingov:{g['id']}:{pid}", data, detail_url(g["id"]), g["date"]))
    return out


# ---------- 出席 ----------

def present_names(text):
    """出席名單 → ([姓名], 黏在一起而切開的詞數)。括號註記（「（依席次排列）」）不算；切不乾淨的詞原樣保留（之後的姓名檢查會擋下）。"""
    names, merged = [], 0
    for tok in re.split(r"[、，,]", NOTE.sub("", text)):
        ms = list(PERSON.finditer(tok))
        if ms and sum(len(m.group(0)) for m in ms) == len(tok):
            names += [m.group(1) + m.group(2) for m in ms]
            merged += len(ms) > 1
        elif tok:
            names.append(tok)
    return names, merged


def parse_present(text):
    """會議紀錄摘要 → (記載人數, [姓名], 黏在一起而切開的詞數)；不是大會紀錄（審查委員會、會勘、總質詢紀錄沒有「出席：議員 N 人」）回 None。"""
    m = PRESENT.search(norm(text))
    if not m:
        return None
    return (int(m.group(1)), *present_names(m.group(2)))


def collect_meetings(rows, texts, roster, log=print):
    """→ [{session, date, file, title, present_ids}]（依日期、清單順序）。人數不符或名單有非姓名的詞時該次會議不收。"""
    parsed = {f: parse_present(t) for f, t in texts.items() if t is not None}
    succ = {}  # 遞補者第一次列名的日期
    for r in sorted(rows, key=lambda r: r["date"]):
        for f in r["files"]:
            for name in FORMER.values():
                if parsed.get(f) and name in parsed[f][1]:
                    succ.setdefault(name, r["date"])
    out, seen = [], set()
    for r in sorted(rows, key=lambda r: r["date"]):
        for f in r["files"]:
            text = texts.get(f)
            label = f"{session_name(r)} {r['roc']}（{r['cells'][6]}）"
            if text is None:
                log(f"kin_book：會議紀錄 {label} 未取得，不列入")
                continue
            got = parsed[f]
            if got is None:
                continue
            n, names, merged = got
            odd = [t for t in names if not NAME.match(t)]
            if odd or len(names) != n:
                log(f"kin_book：會議紀錄 {label} 記載出席 {n} 人，名單讀到 {len(names)} 個{f'（非姓名 {odd[:3]}）' if odd else ''}，不列入")
                continue
            if len(set(names)) != len(names):
                log(f"kin_book：會議紀錄 {label} 名單有重複姓名，不列入")
                continue
            if merged:
                log(f"kin_book：會議紀錄 {label} 名單有 {merged} 處漏了頓號，依職稱切開（人數相符）")
            ids, unknown = set(), []
            for t in names:
                pid, why = resolve(t, roster)
                if pid:
                    ids.add(pid)
                elif t in FORMER and r["date"] < succ.get(FORMER[t], "9999"):
                    log(f"kin_book：會議紀錄出席名單 {t}：前議員（{FORMER[t]}遞補前），照收")
                else:
                    unknown.append(f"{t}（{why}）")
            if unknown:
                log(f"kin_book：會議紀錄 {label} 名單有對不到名錄的人 {'、'.join(unknown)}，不列入")
                continue
            title = re.sub(r"\s*\(\d+KB\)$", "", r["cells"][6])
            if (r["date"], title) in seen:
                log(f"kin_book：會議紀錄 {label} 重複，不列入")
                continue
            seen.add((r["date"], title))
            out.append({"session": session_name(r), "date": r["date"], "file": f, "title": title, "present_ids": ids, "n": n})
    return out


def attendance_facts(meetings, pids, replacements=frozenset()):
    """{person_id: [(fact_key, data, url, date)]}：每人每會期一筆，只有出席次數（沒有請假名單）。
    replacements：任期中遞補的人（任職 fact 沒有起日），從第一次列入出席名單的會議起算，之前的會議不計入分母。"""
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
            data = {"term": TERM, "session": session, "title": f"{session}會議紀錄摘要", "meetings": len(sm),
                    "present": sum(pid in m["present_ids"] for m in sm), "leave": None, "duty": None, "from_lists": True}
            out.setdefault(pid, []).append((f"kinattend:{slug}:{pid}", data, file_url(sm[0]["file"]), sm[0]["date"]))
    return out


# ---------- 組成紀錄 ----------

def build(conn, gov, minutes, details, texts, log=print):
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    pids = set()
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"kin_book：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        pids.add(pid)
    names = [r[0] for r in conn.execute("""
        SELECT DISTINCT p.name FROM fact o JOIN person p USING (person_id)
        WHERE o.kind = 'office' AND json_extract(o.data, '$.office') = ?""", (OFFICE,))]
    govs = gov_rows(gov, details, log, roster_names=names)
    meetings = collect_meetings(minutes, texts, roster, log)
    replacements = {r[0] for r in conn.execute(
        "SELECT person_id FROM fact WHERE kind = 'office' AND json_extract(data, '$.office') = ? AND date IS NULL", (OFFICE,))}
    return ts, govs, meetings, gov_facts(govs, roster, pids, log), attendance_facts(meetings, pids, replacements)


def load_all(refresh=True):
    gov = load_list("AgendaGovMinutes", refresh)
    minutes = load_list("AgendaMinutes", refresh)
    details = {r["id"]: detail_page(r["id"], refresh) for r in gov}
    texts = {f: minutes_text(f, refresh) for r in minutes for f in r["files"]}
    return gov, minutes, details, texts


def run(conn):
    gov, minutes, details, texts = load_all()
    logs = Counter()
    ts, govs, meetings, gf, att = build(conn, gov, minutes, details, texts, lambda s: logs.update([s]))
    for line, n in sorted(logs.items()):
        print(f"{line}（{n} 次）" if n > 1 else line)
    ng, dg = write(conn, "kingov", gf, "interpellation")
    na, da = write(conn, "kinattend", att, "attendance")
    print(f"kin_book：縣政總質詢紀錄 {len(gov)} 場（有質詢議員 {len(govs)} 場），{len(gf)} 人 {ng} 筆（刪除 {dg}）；"
          f"會議紀錄 {len(minutes)} 份、大會 {len(meetings)} 次；對象 {len(ts)} 人；出席 {len(att)} 人 {na} 筆（刪除 {da}）")


# ---------- 自我檢查 ----------

def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    gov, minutes, details, texts = load_all(refresh=False)
    logs = []
    ts, govs, meetings, gf, att = build(dump_conn(), gov, minutes, details, texts, logs.append)
    for line, n in sorted(Counter(logs).items()):
        print(" ", line, f"（{n} 次）" if n > 1 else "")
    print("會期：", sorted(Counter(m["session"] for m in meetings).items(), key=lambda x: x[0]))
    print(f"縣政總質詢 {len(gov)} 場（有質詢議員 {len(govs)}）；大會 {len(meetings)} 次（{meetings[0]['date']}～{meetings[-1]['date']}）")
    names = {t["person_id"]: t["name"] for t in ts}
    for pid, name in sorted(names.items(), key=lambda x: x[1]):
        a = att.get(pid, [])
        p, m = sum(d["present"] for _, d, _, _ in a), sum(d["meetings"] for _, d, _, _ in a)
        print(f"  {name}（{pid}）出席 {p}／{m}；縣政總質詢 {len(gf.get(pid, []))} 場")
        if any(s in name for s in samples):
            for _, d, url, dt in a:
                print(f"    {d['session']:<12} {dt} {d['present']:>2}／{d['meetings']:<2} {url}")
            for _, d, url, dt in gf.get(pid, []):
                print(f"    {dt} {d['title']} {url}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        load_all()
    check([a for a in sys.argv[1:] if not a.startswith("--")])
