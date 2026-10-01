"""臺北市議會第 14 屆大會出席／請假（V4）。來源：議會網站「會議紀錄 › 大會」議事錄 PDF 表頭的
「出席議員：… 計 N 位」「請假議員：… 計 N 位」。

議事錄沒有缺席欄，一次會議（可跨數日）簽到過一次即列出席，所以只產生出席與請假，不推缺席
（見 docs/validation/V4-council-attendance.md §2.3、§5）。
部分日期請假（`闕枚莎(9/13-9/14)`）同時列在出席與請假：照官方算出席，括號原文記在 partial_leave。
"""
import html
import json
import re
import time

from etl.db import upsert, upsert_fact
from etl.fetch import get as fetch, now_utc, pdf_text
from etl.sources.tcc_councilors import load_identity

BASE = "https://www.tcc.gov.tw/"
LIST_URL = BASE + "MeetingMinutes.aspx?n=13534&kind=2&subkind=816652133AE2F06E&PageSize=200"
MIN_INTERVAL = 1.0  # 秒；禮貌爬取
TERM = 14

ROW = re.compile(
    r'data-title="屆次會別"[^>]*><span>([^<]*)</span></td>'
    r'<td[^>]*data-title="類別"[^>]*><span>([^<]*)</span></td>'
    r'<td[^>]*data-title="資料名稱"[^>]*><span><a href="(MeetingMinutesDetail\.aspx\?n=13534&GrpKind=2&FileGrpKindSN=([0-9A-F]+))">([^<]*)</a></span></td>'
    r'<td[^>]*data-title="資料日期"[^>]*><span>(\d+/\d\d/\d\d)</span>'
)
PDF_LINK = re.compile(r'href="(https://obasfront\.tcc\.gov\.tw/[^"]*\.pdf[^"]*)"')
DAY = re.compile(r"(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日")
PAREN = re.compile(r"(\S+?)\s*[(（]([^)）]*)[)）]")

_last = 0.0


def get(url):
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return fetch(url)
    finally:
        _last = time.monotonic()


def parse_list(page):
    """大會議事錄清單 → [{sn, session, meeting, detail_url}]；談話會沒有名單，不收。"""
    rows = ROW.findall(page)
    n_cells = page.count('data-title="資料名稱"')
    if n_cells != len(rows) or not rows:
        raise ValueError(f"大會議事錄清單格式未知：{n_cells} 列只解析出 {len(rows)} 列")
    out = []
    for session, kind, href, sn, meeting, _ in rows:
        if kind != "大會":
            raise ValueError(f"清單出現非大會項目：{kind} {session} {meeting}")
        if "談話會" in meeting:
            continue
        out.append({
            "sn": sn,
            "session": html.unescape(session).strip(),
            "meeting": html.unescape(meeting).strip(),
            "detail_url": BASE + html.unescape(href),
        })
    return out


def parse_detail(page):
    """詳細頁 → 議事錄 PDF 的下載網址（只該有一個）。"""
    links = PDF_LINK.findall(page)
    if len(links) != 1:
        raise ValueError(f"詳細頁 PDF 連結數 {len(links)}，預期 1")
    return html.unescape(links[0])


def _names(block):
    """名單區塊 → [(姓名, 括號原文或 None)]；姓名以空白分隔，括號前可能有空白（`葉林傳 (11/23-11/24)`）。"""
    block = PAREN.sub(lambda m: f"{m.group(1)}\0{m.group(2).strip()}", block)
    out = []
    for tok in block.split():
        name, _, note = tok.partition("\0")
        out.append((name, note or None))
    return out


def _counted(head, label):
    m = re.search(label + r"：(.*?)計\s*(\d+)\s*位", head, re.S)
    if not m:
        raise ValueError(f"找不到「{label}：… 計 N 位」")
    names = _names(m.group(1))
    if len(names) != int(m.group(2)):
        raise ValueError(f"{label}名單 {len(names)} 人與「計 {m.group(2)} 位」不符：{names}")
    return names


def parse_minutes(text):
    """議事錄文字 → {days, attendees, leave, attendees_n, leave_n}；leave 是 [(姓名, 部分請假原文或 None)]。"""
    head = text.split("列席")[0]
    when = re.search(r"時間：(.*?)地點：", head, re.S)
    if not when:
        raise ValueError("找不到「時間：… 地點：」")
    days = [f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}" for y, m, d in DAY.findall(when.group(1))]
    if not days:
        raise ValueError(f"時間欄沒有日期：{when.group(1)!r}")
    attendees = _counted(head, "出席議員")
    leave = _counted(head, "請假議員") if "請假議員" in head else []
    if any(note for _, note in attendees):
        raise ValueError(f"出席名單帶括號註記，格式未知：{attendees}")
    att = [n for n, _ in attendees]
    if len(set(att)) != len(att) or len({n for n, _ in leave}) != len(leave):
        raise ValueError("名單內有重複姓名")
    for name, note in leave:
        # 同時在出席與請假，只有「部分日期請假」一種合理解釋；沒括號就不知道怎麼算
        if name in att and note is None:
            raise ValueError(f"{name} 同時在出席與請假名單，但沒有部分請假日期")
    return {"days": days, "attendees": att, "leave": leave, "attendees_n": len(att), "leave_n": len(leave)}


def statuses(parsed):
    """→ {姓名: (status, partial_leave)}；部分請假照官方算出席。"""
    out = {n: ("present", None) for n in parsed["attendees"]}
    for name, note in parsed["leave"]:
        out[name] = ("present", note) if name in out else ("leave", note)
    return out


def write_meeting(conn, item, parsed, identity, fetched_at):
    """每位有對照、且名列當次名單的議員寫一筆；回傳 (寫入筆數, 沒有對照的姓名)。
    identity 有、名單沒有的人不寫：表示他當時不在任（例如遞補、就職前）。"""
    written, unmapped = 0, []
    for name, (status, partial) in statuses(parsed).items():
        if name not in identity:
            unmapped.append(name)
            continue
        person_id = identity[name][0]
        upsert_fact(
            conn, f"attend:{item['sn']}:{person_id}", person_id, "attendance",
            {
                "term": TERM,
                "session": item["session"],
                "meeting": item["meeting"],
                "days": parsed["days"],
                "status": status,
                "partial_leave": partial,
                "attendees_n": parsed["attendees_n"],
                "leave_n": parsed["leave_n"],
                "title": f"{item['session']} {item['meeting']}",
            },
            item["detail_url"], fetched_at, date=parsed["days"][0],
        )
        written += 1
    return written, unmapped


def covered_councillors(conn):
    row = conn.execute("SELECT state FROM source_state WHERE source = 'tcc_attendance'").fetchone()
    return set(json.loads(row["state"])["covered"]) if row else set()


def known_meetings(conn):
    rows = conn.execute("SELECT fact_key FROM fact WHERE kind = 'attendance'")
    return {r["fact_key"].split(":")[1] for r in rows}


# ponytail: 增量＝DB 已有 FileGrpKindSN 的會議就跳過；議事錄事後改版不會重抓。
#   identity 出現未涵蓋的議員時整份重掃（約 250 次請求），完成後記進 source_state。
#   PDF 失效（HTTP 200 卻回 HTML）的會議只警告，下次執行會再試；.doc 備援未做（V4 §7-2 未驗證格式）。
def run(conn, full=False):
    identity = load_identity()
    exhaustive = full or bool(set(identity) - covered_councillors(conn))
    known = set() if exhaustive else known_meetings(conn)
    fetched_at = now_utc()
    unmapped = {}
    for item in parse_list(get(LIST_URL).decode("utf-8")):
        if item["sn"] in known:
            continue
        pdf_url = parse_detail(get(item["detail_url"]).decode("utf-8"))
        data = get(pdf_url)
        if not data.startswith(b"%PDF"):
            print(f"警告：{item['session']} {item['meeting']} 議事錄不是 PDF（{len(data)} bytes），跳過：{pdf_url}")
            continue
        try:
            parsed = parse_minutes(pdf_text(data))
        except ValueError as e:
            raise ValueError(f"{item['session']} {item['meeting']}（{item['detail_url']}）：{e}") from e
        _, names = write_meeting(conn, item, parsed, identity, fetched_at)
        for n in names:
            unmapped[n] = unmapped.get(n, 0) + 1
    if unmapped:
        print(f"tcc_attendance：名單上沒有 identity 對照、已略過的姓名（次數）：{unmapped}")
    upsert(
        conn, "source_state",
        {"source": "tcc_attendance", "state": json.dumps({"covered": sorted(identity)}, ensure_ascii=False)},
        ("source",),
    )
