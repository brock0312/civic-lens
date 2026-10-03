"""立法院記名表決（立法院 API /votes），只抓已串到 2026 候選人的現任立委。

**預設不在 etl/run.py 的 SOURCES**：第 11 屆記名表決很多（一天可達數百筆），逐筆存成 fact 可能讓公開的 dump 明顯變大。
啟用前先在本機量筆數：python3 -m etl.sources.ly_votes（只印每位委員參與的表決數，不寫資料庫），
確認 dump 增加的大小可以接受，再把本模組加進 SOURCES（放在 ly_records 之後）。

只列委員有投票（贊成、反對、棄權）的表決，照公報記錄呈現立場，不計分、不排名、不算「跑票」。
沒列在投票名單上不代表缺席（可能在場未按表決器），所以不收也不顯示「未投票」。
"""
import sys

from etl import lyapi
from etl.db import upsert_fact
from etl.fetch import get_json, now_utc
from etl.sources.ly_records import linked_legislators

KIND = "ly_vote"
POSITIONS = ("贊成", "反對", "棄權")


def _names(v):
    return [v] if isinstance(v, str) else list(v or [])


def vote_facts(rows, name):
    out = []
    for r in rows:
        pos = [p for p in POSITIONS if name in _names(r.get(p))]
        if len(pos) != 1 or not r.get("表決代碼"):
            continue  # 不在名單上、或同一表決出現兩種立場（資料錯誤）就不收
        result = r.get("表決結果") or {}
        out.append({
            "key": f"{KIND}:{r['表決代碼']}",
            "date": lyapi.to_date(lyapi.roc_text_date(r.get("表決時間"))),
            "data": {"topic": (r.get("表決議題") or "").strip(), "position": pos[0], "vote_id": r["表決代碼"],
                     "meet_id": r.get("會議代碼"), "meeting": r.get("會議名稱"),
                     "counts": {k: result.get(f"{k}人數") for k in ("出席", *POSITIONS)}},
            "source_url": lyapi.item_url("vote", r["表決代碼"]),
        })
    return out


def replace_votes(conn, person_id, facts, fetched_at):
    keys = set()
    for f in facts:
        key = f"{f['key']}:{person_id}"
        keys.add(key)
        upsert_fact(conn, key, person_id, KIND, f["data"], f["source_url"], fetched_at, date=f["date"])
    for (k,) in conn.execute("SELECT fact_key FROM fact WHERE person_id = ? AND kind = ?", (person_id, KIND)).fetchall():
        if k not in keys:
            conn.execute("DELETE FROM fact WHERE fact_key = ?", (k,))


def run(conn):
    fetched_at = now_utc()
    linked = linked_legislators(conn)
    keep = {pid for pid, _ in linked}
    for (pid,) in conn.execute("SELECT DISTINCT person_id FROM fact WHERE kind = ?", (KIND,)).fetchall():
        if pid not in keep:
            conn.execute("DELETE FROM fact WHERE person_id = ? AND kind = ?", (pid, KIND))
    for person_id, name in linked:
        rows, _ = lyapi.fetch_all("votes", {"屆": lyapi.TERM, "投票委員": name})
        facts = vote_facts(rows, name)
        replace_votes(conn, person_id, facts, fetched_at)
        print(f"{name}（{person_id}）：記名表決 {len(facts)} 筆")


def count(conn):
    """只量筆數：每位已串接立委參與的第 11 屆表決數（limit=1，只讀 total）。"""
    for person_id, name in linked_legislators(conn):
        body = get_json(lyapi.list_url("votes", {"屆": lyapi.TERM, "投票委員": name}, 1, 1), headers=lyapi.headers())
        print(f"{name}（{person_id}）：{body.get('total')} 筆")


if __name__ == "__main__":
    from pathlib import Path

    from etl.db import open_db
    root = Path(__file__).resolve().parents[2]
    count(open_db(root / "data" / "civic.db", root / "data" / "civic.sql"))
    sys.exit(0)
