"""確定有罪判決（G5，V7 §3.2）：只顯示人工核可表 data/convictions.csv 上的判決，每次執行都重新驗證，失效就移除。

核可表的每一列都要通過 V7 §3.2 的兩道關卡，由 Claude 初審、verifier 複核後才寫入：
- finality_basis：已確定的正面證據，A（文末「不得上訴」）、B（歷審 [撤回上訴]）、C（後續裁定稱確定判決）、D（最高法院駁回或自為判決）。
  F（共同被告推論）、G（一審查無上訴紀錄）判斷不了，不收。
- identity_path：1＝判決內文有可對到公開名冊的身分錨點；2＝同案其他審級判決有錨點。identity_basis 寫明錨點與比對經過。
顯示欄位（court、case_no、offense、result）照判決原文，不做摘要式定性；不收起訴、行政罰、親屬。

每次執行（fail closed，任何一步失敗就不顯示該筆）：
1. 重抓 FJUD 原文（UA 用 etl.fetch 的 civic-lens-etl/0.1，V7 §2.1 實測放行）；被擋或下架 → 不顯示。
2. 從原文抓出 jid，重抓歷審清單；有尚未結案的上級審（href 為空或 red==1，V7 §2.3 E）→ 不顯示。
"""
import csv
import json
import re
import time
import urllib.parse
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import get, now_utc

PATH = Path(__file__).resolve().parents[2] / "data" / "convictions.csv"
FIELDS = ("fjud_id", "person_id", "court", "case_no", "judgment_date", "offense", "result", "finality_basis",
          "identity_path", "identity_basis", "reviewed_by", "reviewed_at", "note")
FJUD = "https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id="
HISTORY = "https://judgment.judicial.gov.tw/controls/GetJudHistory.ashx?jid="
KIND = "conviction"
_ID = re.compile(r"^[A-Z]{3,5},\d{2,3},[^,]+,\d+,\d{8},\d+$")
_JID = re.compile(r"""GetJudHistory\.ashx\?jid=([^"'&\s]+)|\bjid\s*[:=]\s*["']([^"']+)["']""")


def judgment_url(fjud_id):
    return FJUD + urllib.parse.quote(fjud_id, safe="")


def load(path=PATH):
    """核可表 → 列。格式不符就 raise（核可表是人寫的，寫錯要立刻發現，不靜默略過）。"""
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    seen = set()
    for r in rows:
        k = (r["fjud_id"], r["person_id"])
        if k in seen:
            raise ValueError(f"convictions.csv 重複：{k}")
        seen.add(k)
        if not _ID.match(r["fjud_id"]):
            raise ValueError(f"convictions.csv fjud_id 格式不符（法院代碼,年度,字別,號,YYYYMMDD,序）：{r['fjud_id']}")
        ymd = r["fjud_id"].split(",")[4]
        if r["judgment_date"] != f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}":
            raise ValueError(f"convictions.csv judgment_date 與 fjud_id 的裁判日期不一致：{r}")
        if r["finality_basis"] not in ("A", "B", "C", "D"):
            raise ValueError(f"convictions.csv finality_basis 只能是 A–D（F、G 不收）：{r}")
        if r["identity_path"] not in ("1", "2"):
            raise ValueError(f"convictions.csv identity_path 只能是 1 或 2：{r}")
        missing = [f for f in ("person_id", "court", "case_no", "offense", "result", "identity_basis",
                               "reviewed_by", "reviewed_at") if not r[f].strip()]
        if missing:
            raise ValueError(f"convictions.csv 缺 {missing}：{r['fjud_id']}")
    return rows


def rejected(page):
    """FJUD 的 bot-defense 被擋時回 200、內容是短短的 Request Rejected（V7 §2.1）。"""
    return len(page) < 2000 or "Request Rejected" in page


def jid_of(page):
    m = _JID.search(page)
    return urllib.parse.unquote(m.group(1) or m.group(2)) if m else None


def pending_appeal(history):
    """歷審清單有尚未結案的上級審（V7 §2.3 E）→ 回傳該列 desc；沒有回 None。"""
    for item in history.get("list") or []:
        if item.get("href", None) == "" or item.get("red") == 1:
            return item.get("desc") or "（無說明）"
    return None


def verify(row, fetch=get, sleep=1.5):
    """重抓原文與歷審；通過回 None，否則回不顯示的原因。"""
    try:
        page = fetch(judgment_url(row["fjud_id"])).decode("utf-8", "replace")
    except Exception as e:  # 下架（404）或連線失敗：本次不顯示，下次再驗
        return f"原文抓取失敗：{e}"
    if rejected(page):
        return "原文被擋或內容過短"
    if row["case_no"].replace(" ", "") not in re.sub(r"\s", "", page):
        return "原文找不到核可表的判決字號"
    jid = jid_of(page)
    if not jid:
        return "原文找不到歷審清單的 jid"
    if sleep:
        time.sleep(sleep)
    try:
        history = json.loads(fetch(HISTORY + urllib.parse.quote(jid, safe="")))
    except Exception as e:
        return f"歷審清單抓取失敗：{e}"
    pending = pending_appeal(history)
    return f"歷審清單有尚未結案的上級審：{pending}" if pending else None


def fact_data(row):
    return {"final": True, "court": row["court"], "case_no": row["case_no"], "judgment_date": row["judgment_date"],
            "offense": row["offense"], "result": row["result"], "finality_basis": row["finality_basis"],
            "identity_path": int(row["identity_path"]), "fjud_id": row["fjud_id"]}


def run(conn, rows=None, fetch=get, sleep=1.5):
    fetched_at = now_utc()
    rows = load() if rows is None else rows
    candidates = {pid for (pid,) in conn.execute("SELECT DISTINCT person_id FROM fact WHERE kind = 'candidacy'")}
    keep = set()
    for r in rows:
        if r["person_id"] not in candidates:
            print(f"判決 {r['fjud_id']}：{r['person_id']} 不是 2026 候選人，不顯示")
            continue
        reason = verify(r, fetch, sleep)
        if reason:
            print(f"判決 {r['fjud_id']}（{r['person_id']}）本次不顯示：{reason}")
            continue
        key = f"{KIND}:{r['fjud_id']}:{r['person_id']}"
        keep.add(key)
        upsert_fact(conn, key, r["person_id"], KIND, fact_data(r), judgment_url(r["fjud_id"]), fetched_at,
                    date=r["judgment_date"])
    for (k,) in conn.execute("SELECT fact_key FROM fact WHERE kind = ?", (KIND,)).fetchall():
        if k not in keep:
            conn.execute("DELETE FROM fact WHERE fact_key = ?", (k,))
    print(f"確定有罪判決：核可表 {len(rows)} 筆，本次顯示 {len(keep)} 筆")
