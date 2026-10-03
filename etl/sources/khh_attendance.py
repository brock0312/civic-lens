"""高雄市議會第 4 屆議員出缺勤（V15）。來源：公報議事錄附錄「議員出席情形統計表」PDF（cissearch.kcc.gov.tw），
每個會期（成立大會、臨時會、定期大會）一份，逐次會議、逐人標記出席或假別，另有合計列。

統計表的姓名是直排（一欄一人），一份表左右兩頁各半數議員，定期大會再分成多組頁。解析靠 pdftotext -bbox 的字框：
- 會議列：只有符號（○△◇☆□▽§☉）的字詞；多字的符號字詞依字寬均分。符號的 x 決定欄位。
- 姓名：會議列上方、圖說與標題下方的單一漢字，依 x 分欄、依 y 接成姓名；直排字框會整體偏移約半個字，
  所以姓名欄和符號欄依序配對（欄數必須相同、偏移量一致）。
- 合計列：符號區下方的一兩位數字（新版前面可能黏著列名「席7」），依 x 對到欄。
每欄依符號數出各類次數，再和官方合計列核對：印出全部類別時逐項相等，否則（舊版 0 不印）非零的數字依序相等。
核對不過、欄內有空白格、同表同名的欄都不收並列出。舊版統計表（第 4 屆成立大會至第 3 次定期大會等）沒有缺席欄，
absent 記 None。

只寫給有高雄市議員任職 fact 且有 2026 candidacy 的人（khh_videos.targets），姓名以 etl.match 的漢字正規化對名錄，
名錄同名或對不到的不收。
"""
import html
import http.cookiejar
import json
import re
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import UA, now_utc
from etl.match import VARIANTS, han
from etl.sources.khh_videos import targets

HOST = "https://cissearch.kcc.gov.tw/"
BASE = HOST + "System/Bulletin/"
SEARCH_URL = BASE + "Default.aspx"
KEYWORD = "出席情形統計表"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "khh_attendance"
MIN_INTERVAL = 1.1  # 秒；同主機禮貌間隔（robots.txt 404）
TERM = 4
P = "ctl00$ContentPlaceHolder1$"

SYMBOLS = "○△◇☆□▽§☉"  # 圖說順序＝合計列順序
CATS = ["出席", "請假", "病假", "公差", "公假", "喪假", "事假", "缺席"]
LEAVE = ["請假", "病假", "喪假", "事假"]
DUTY = ["公差", "公假"]  # 公務，和請假分開列（使用者 2026-10-03 決定）
_VAR = str.maketrans(VARIANTS)
_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')
_NUM = re.compile(r"^([\u3400-\u9fff]?)(\d+)$")  # 新版合計列的第一個數字黏著列名：「席7」
GAP = 3.0  # pt；同一欄的 x 中心差距遠小於此，相鄰欄約 11–12pt

RESULT = re.compile(
    r"<td data-type='附錄' data-meeting='[^']*' data-types='議事錄'>.*?"
    r"<a href=\"(View\.aspx\?scan=1&BulletinSN=(\d+)&pages=[\d,]+)#pdfStart\"[^>]*>(第4屆[^<]*?)議員出席情形統計表</a>", re.S)
IFRAME = re.compile(r"Pdfview\.aspx\?file=~/(Upload/Attachment/[^'\"&]+\.pdf)")

_last = 0.0
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def get(url, data=None):
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
    try:
        with _opener.open(req, timeout=120) as resp:
            return resp.read()
    finally:
        _last = time.monotonic()


def _hidden_fields(page):
    out = {}
    for m in re.finditer(r'<input[^>]*type="hidden"[^>]*>', page):
        n = re.search(r'name="([^"]*)"', m.group())
        v = re.search(r'value="([^"]*)"', m.group())
        if n:
            out[html.unescape(n.group(1))] = html.unescape(v.group(1)) if v else ""
    return out


def search(keyword=KEYWORD):
    """公報全文檢索（ASP.NET 表單 POST，第 4 屆）→ 結果頁 HTML。"""
    page = get(SEARCH_URL).decode("utf-8")
    form = _hidden_fields(page) | {
        "__EVENTTARGET": P + "linkBtnSearch", "__EVENTARGUMENT": "",
        P + "uscPeriodSessionMeeting$ddlPeriod": "07", P + "uscPeriodSessionMeeting$ddlSession": "0704",
        P + "uscPeriodSessionMeeting$ddlMeeting": "", P + "txtKeyword": keyword, "ctl00$txtKeyword": "",
    }
    return get(SEARCH_URL, form).decode("utf-8")


def parse_search(page):
    """檢索結果 → [{sn, session, view_url}]（只收第 4 屆、分類「附錄」的統計表）。"""
    return [{"sn": sn, "session": title, "view_url": BASE + html.unescape(href)}
            for href, sn, title in RESULT.findall(page)]


def pdf_url(view_page):
    links = set(IFRAME.findall(view_page))
    if len(links) != 1:
        raise ValueError(f"View 頁 PDF 連結數 {len(links)}，預期 1")
    return HOST + urllib.parse.quote(html.unescape(links.pop()))


# ---------- 解析 ----------

def bbox_pages(pdf_bytes):
    """PDF → 每頁 [(x0, y0, x1, y1, 字)]。"""
    out = subprocess.run(["pdftotext", "-bbox", "-", "-"], input=pdf_bytes, capture_output=True, check=True).stdout
    return parse_bbox(out.decode("utf-8"))


def parse_bbox(text):
    return [[(float(a), float(b), float(c), float(d), html.unescape(t)) for a, b, c, d, t in _WORD.findall(p)]
            for p in text.split("<page ")[1:]]


def _clusters(xs):
    """排序後相鄰差 > GAP 就分群 → 各群平均。"""
    groups = []
    for x in sorted(xs):
        if groups and x - groups[-1][-1] <= GAP:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [sum(g) / len(g) for g in groups]


def _nearest(cols, x, tol):
    i = min(range(len(cols)), key=lambda k: abs(cols[k] - x))
    return i if abs(cols[i] - x) <= tol else None


def parse_page(words):
    """一頁 → {names, rows: [{欄: 符號}], totals: {欄: [數字（由上而下）]}}；格式不對 raise ValueError。"""
    # 符號字（多字字詞依字寬均分）
    syms = []
    for x0, y0, x1, y1, t in words:
        if t and all(c in SYMBOLS for c in t):
            w = (x1 - x0) / len(t)
            syms += [(x0 + (i + 0.5) * w, (y0 + y1) / 2, c) for i, c in enumerate(t)]
    lines = {}
    for x, y, c in syms:
        key = next((k for k in lines if abs(k - y) <= GAP), y)
        lines.setdefault(key, []).append((x, c))
    rows = sorted((y, v) for y, v in lines.items() if len(v) >= 10)  # 圖說裡單獨的符號（「☆ 公 差」）不是會議列
    if not rows:
        raise ValueError("找不到會議列")
    cols = _clusters([x for _, v in rows for x, _ in v])
    pitch = statistics.median(b - a for a, b in zip(cols, cols[1:]))
    top_row, bottom_row = rows[0][0], rows[-1][0]

    # 姓名：圖說、標題、頁首（含「統計表」「註」或符號夾字的字詞，以及同一行的字）下方，會議列上方
    marks = [(y0 + y1) / 2 for x0, y0, x1, y1, t in words
             if ("統計表" in t or "註" in t or (any(c in SYMBOLS for c in t) and _CJK.search(t))) and y1 < top_row]
    ceiling = max([(y0 + y1) / 2 for x0, y0, x1, y1, t in words if any(abs((y0 + y1) / 2 - m) <= GAP for m in marks)],
                  default=0) + GAP
    chars = [((x0 + x1) / 2, (y0 + y1) / 2, t) for x0, y0, x1, y1, t in words
             if len(t) == 1 and _CJK.match(t) and ceiling < (y0 + y1) / 2 < top_row - GAP
             and (x0 + x1) / 2 > cols[0] - pitch / 4]  # 舊版會議列名「第 37 次」的「次」緊貼第一欄左邊
    ncols = _clusters([x for x, _, _ in chars])
    if len(ncols) < 2:
        raise ValueError("找不到姓名")
    names = ["".join(t for _, _, t in sorted((c for c in chars if _nearest(ncols, c[0], GAP) == i), key=lambda c: c[1]))
             for i in range(len(ncols))]

    # 姓名欄沒有空缺；符號欄在整欄劃掉（未在任）時會少一欄，所以依格距算出每個符號欄是第幾欄，首尾兩欄必須都在
    npitch = statistics.median(b - a for a, b in zip(ncols, ncols[1:]))
    pos = [(c - cols[0]) / npitch for c in cols]
    idx = [round(p) for p in pos]
    if any(abs(p - i) > 0.25 for p, i in zip(pos, idx)) or len(set(idx)) != len(idx) or idx[-1] != len(ncols) - 1:
        raise ValueError(f"姓名 {len(ncols)} 欄、符號 {len(cols)} 欄，對不上")
    shift = [ncols[i] - c for i, c in zip(idx, cols)]
    if max(shift) - min(shift) > 2 or abs(statistics.median(shift)) > pitch * 0.7:
        raise ValueError(f"姓名欄與符號欄的偏移不一致：{min(shift):.1f}～{max(shift):.1f}pt")
    gridx = [n - statistics.median(shift) for n in ncols]  # 每一欄（含整欄空白）在符號座標的 x

    grid = []
    for _, v in rows:
        cells = {}
        for x, c in v:
            i = _nearest(gridx, x, GAP)
            if i is None or i in cells:
                raise ValueError("會議列的符號對不上欄位")
            cells[i] = c
        grid.append(cells)

    # 合計列：符號區下方的一兩位數字；「席7」這種黏著列名的，數字在字框右端
    # 表下的備註（「113 年 2 月 1 日辭職」）也有數字：只看第一個「註」字以上
    floor = min([y0 for x0, y0, x1, y1, t in words if "註" in t and y0 > bottom_row], default=float("inf"))
    # 舊版相鄰兩欄的兩位數會黏成一個字詞（「4247」）：寬度約 k 欄就均分成 k 個數
    nums = []
    for x0, y0, x1, y1, t in words:
        m = _NUM.match(t)
        if not m or not bottom_row + GAP < (y0 + y1) / 2 < floor:
            continue
        p, d = m.groups()
        k = 1 if p else max(1, round((x1 - x0) / pitch))
        if len(d) % k or len(d) // k > 2:
            continue  # 頁碼
        n, w = len(d) // k, (x1 - x0) / k
        nums += [(x0 + j * w, x0 + (j + 1) * w, (y0 + y1) / 2, p, d[j * n:(j + 1) * n]) for j in range(k)]
    plain = [(x1 - x0) / len(d) for x0, x1, _, p, d in nums if not p]
    dw = statistics.median(plain) if plain else 5.0
    totals = {}
    for x0, x1, y, p, d in sorted(nums, key=lambda n: n[2]):
        xc = x1 - dw * len(d) / 2 if p else (x0 + x1) / 2
        i = _nearest(gridx, xc, pitch * 0.4)
        if i is not None:
            totals.setdefault(i, []).append(int(d))
    return {"names": names, "rows": grid, "totals": totals}


def has_absent_column(pages):
    """統計表有沒有缺席欄：圖說或列名出現「缺」（舊版圖說只到 §事假）。"""
    return any("缺" in t for words in pages for *_, t in words)


def parse_table(pages):
    """一份統計表（每頁字框）→ {meetings, absent_column, people: {姓名: {類別: 次數}}, rejected: [(姓名, 代碼, 原因)]}。
    代碼：blank（有空白格）、absent_without_column、mismatch（符號和合計列不符）、duplicate。
    整份不可用時 raise ValueError。"""
    absent_col = has_absent_column(pages)
    ncat = 8 if absent_col else 7
    halves = {}  # 姓名組 → {rows, totals}
    for words in pages:
        if not any(t and all(c in SYMBOLS for c in t) for *_, t in words):
            continue
        pg = parse_page(words)
        h = halves.setdefault(tuple(pg["names"]), {"rows": [], "totals": []})
        h["rows"] += pg["rows"]
        if pg["totals"]:
            h["totals"].append(pg["totals"])
    if not halves:
        raise ValueError("沒有統計表頁")
    meetings = {len(h["rows"]) for h in halves.values()}
    if len(meetings) != 1:
        raise ValueError(f"各組頁的會議數不同：{sorted(meetings)}")
    people, rejected, seen = {}, [], {}
    for names, h in halves.items():
        if len(h["totals"]) != 1:
            raise ValueError(f"姓名組 {names[:3]}… 的合計列出現在 {len(h['totals'])} 頁，預期 1 頁")
        totals = h["totals"][0]
        for i, name in enumerate(names):
            seen[name] = seen.get(name, 0) + 1
            col = [r.get(i) for r in h["rows"]]
            if None in col:
                rejected.append((name, "blank", f"有 {col.count(None)} 格空白"))
                continue
            counts = [col.count(s) for s in SYMBOLS[:ncat]]
            if sum(counts) != len(col):
                rejected.append((name, "absent_without_column", "有缺席符號，但統計表沒有缺席欄"))
                continue
            official = totals.get(i, [])
            ok = official == counts if len(official) == ncat else [n for n in official if n] == [c for c in counts if c]
            if not ok:
                rejected.append((name, "mismatch", f"符號數 {counts} 和合計列 {official} 不符"))
                continue
            people[name] = dict(zip(CATS, counts))
    for name, n in seen.items():
        if n > 1:
            people.pop(name, None)
            rejected.append((name, "duplicate", f"同一份表出現 {n} 次"))
    return {"meetings": meetings.pop(), "absent_column": absent_col, "people": people, "rejected": rejected}


def fact_data(session, meetings, counts, absent_column):
    leave_types = {k: counts[k] for k in LEAVE + DUTY}  # 官方六個假別的逐項次數
    return {
        "term": TERM,
        "session": session,
        "title": f"{session}議員出席情形統計表",
        "meetings": meetings,
        "present": counts["出席"],
        "leave": sum(counts[k] for k in LEAVE),
        "duty": sum(counts[k] for k in DUTY),
        "leave_types": leave_types,
        "absent": counts["缺席"] if absent_column else None,
    }


def roster_index(conn):
    """所有高雄市議員任職 fact 的漢字姓名 → [person_id]（含沒參選者，用來判斷同名）。"""
    rows = conn.execute("""
        SELECT DISTINCT p.person_id, p.name FROM fact o JOIN person p USING (person_id)
        WHERE o.kind = 'office' AND json_extract(o.data, '$.office') = 'khh_councilor'""")
    idx = {}
    for r in rows:
        idx.setdefault(han(r["name"]).translate(_VAR), []).append(r["person_id"])
    return idx


def match_people(table_names, roster, wanted):
    """統計表姓名 → {姓名: person_id}（只限 wanted 裡的人）；回傳 (對上的, [(姓名, 原因)])。"""
    out, skipped = {}, []
    for name in table_names:
        ids = roster.get(han(name).translate(_VAR), [])
        if len(ids) > 1:
            skipped.append((name, "名錄同名"))
        elif not ids:
            skipped.append((name, "名錄沒有此人"))
        elif ids[0] in wanted:
            out[name] = ids[0]
    return out, skipped


def write_table(conn, item, parsed, roster, wanted, fetched_at):
    """回傳 (寫入筆數, 沒對上的 [(姓名, 原因)])。
    候選人的欄位被整欄不收時，另寫一筆 attendance_excluded，人物頁據此說明少了哪個會期。"""
    matched, skipped = match_people(parsed["people"], roster, wanted)
    for name, pid in matched.items():
        upsert_fact(conn, f"kattend:{item['sn']}:{pid}", pid, "attendance",
                    fact_data(item["session"], parsed["meetings"], parsed["people"][name], parsed["absent_column"]),
                    item["pdf_url"], fetched_at)
    codes = {name: code for name, code, _ in parsed["rejected"]}
    excluded, _ = match_people(codes, roster, wanted)
    for name, pid in excluded.items():
        upsert_fact(conn, f"kattendx:{item['sn']}:{pid}", pid, "attendance_excluded",
                    {"term": TERM, "session": item["session"], "title": f"{item['session']}議員出席情形統計表",
                     "reason": codes[name]},
                    item["pdf_url"], fetched_at)
    return len(matched), skipped


def load_index():
    path = CACHE / "index.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


# ponytail: 統計表刊出後不會改版，以 BulletinSN 快取 PDF；每次只重查檢索結果（2 次請求），新的 SN 才下載。
def fetch_tables():
    known = {it["sn"]: it for it in load_index()}
    items = parse_search(search())
    if not items:
        raise ValueError("公報檢索找不到任何議員出席情形統計表")
    CACHE.mkdir(parents=True, exist_ok=True)
    for it in items:
        pdf = CACHE / f"{it['sn']}.pdf"
        if it["sn"] in known and pdf.exists():
            it["pdf_url"] = known[it["sn"]]["pdf_url"]
            continue
        it["pdf_url"] = pdf_url(get(it["view_url"]).decode("utf-8"))
        data = get(it["pdf_url"])
        if not data.startswith(b"%PDF"):
            raise ValueError(f"{it['session']} 統計表不是 PDF：{it['pdf_url']}")
        pdf.write_bytes(data)
    (CACHE / "index.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return items


def parse_cached(items, log=print):
    """[(item, parsed)]；整份不可用的表列出後略過。"""
    out = []
    for it in items:
        try:
            out.append((it, parse_table(bbox_pages((CACHE / f"{it['sn']}.pdf").read_bytes()))))
        except ValueError as e:
            log(f"khh_attendance：{it['session']}（{it['pdf_url']}）整份不收：{e}")
    return out


def run(conn):
    tables = parse_cached(fetch_tables())
    roster = roster_index(conn)
    wanted = {t["person_id"] for t in targets(conn)}
    fetched_at = now_utc()
    total = 0
    for it, parsed in tables:
        n, skipped = write_table(conn, it, parsed, roster, wanted, fetched_at)
        total += n
        for name, why in [(n, w) for n, _, w in parsed["rejected"]] + skipped:
            print(f"khh_attendance：{it['session']} 不收 {name}：{why}")
    print(f"khh_attendance：統計表 {len(tables)} 份，對象 {len(wanted)} 人，寫入 {total} 筆")


def _self_check(samples=("黃明太", "湯詠瑜", "黃飛鳳")):
    """讀快取（不連網）：每份表解析人數、對上人數、出席／請假／缺席合計，並列出抽查議員的逐表數字。"""
    import tempfile
    from etl.db import open_db
    with tempfile.TemporaryDirectory() as d:
        conn = open_db(Path(d) / "check.db", Path(__file__).resolve().parents[2] / "data" / "civic.sql")
        roster = roster_index(conn)
        wanted = {t["person_id"] for t in targets(conn)}
    items = load_index()
    sums = dict.fromkeys(["present", "leave", "duty", "absent", "meetings"], 0)
    per_person = {}
    for it, parsed in parse_cached(items):
        matched, skipped = match_people(parsed["people"], roster, wanted)
        print(f"{it['session']:<14} 會議 {parsed['meetings']:>2} 次　解析 {len(parsed['people'])} 人　"
              f"對上候選人 {len(matched)} 人　缺席欄 {'有' if parsed['absent_column'] else '無'}")
        for name, why in [(n, w) for n, _, w in parsed["rejected"]] + skipped:
            print(f"    不收 {name}：{why}")
        for name, pid in matched.items():
            d = fact_data(it["session"], parsed["meetings"], parsed["people"][name], parsed["absent_column"])
            for k in sums:
                sums[k] += d[k] or 0
            per_person.setdefault(name, []).append((it["session"], d))
    print(f"\n表 {len(items)} 份；對上 {len(per_person)}/{len(wanted)} 位候選人；合計 {sums}")
    for name in samples:
        print(f"\n{name}：")
        for session, d in per_person.get(name, []):
            print(f"  {session:<14} 會議 {d['meetings']:>2}　出席 {d['present']:>2}　請假 {d['leave']}　公差／公假 {d['duty']}"
                  f" {[(k, v) for k, v in d['leave_types'].items() if v]}　缺席 {d['absent']}")


if __name__ == "__main__":
    _self_check(*([sys.argv[1:]] if sys.argv[1:] else []))
