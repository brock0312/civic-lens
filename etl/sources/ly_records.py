"""立法院問政紀錄（立法院 API），只抓已串到 2026 候選人的現任立委（網站只呈現候選人，也避免 dump 膨脹）。

三種 fact，都只列事實與原始出處，不計分、不排名：
- ly_interpellation：/interpellations（立法院公報「質詢事項」，書面質詢性質；口頭質詢是否涵蓋未確認，見 docs/data-sources/legislative-yuan.md）
- ly_video：/ivods 的委員發言片段（影片種類 Clip），連 ivod.ly.gov.tw 官方播放頁
- ly_bill：/bills 列名「提案人」的議案（不含只列名連署的）
出席（/meets，V5 未驗證）與表決（/votes）尚未收錄。

每次重抓一位委員就整批取代該委員這三種 fact；任何一個端點失敗就 raise，run.py 會 rollback，不會只更新一半。
"""
import json

from etl import lyapi
from etl.fetch import now_utc
from etl.db import upsert_fact
from etl.sources.ly_legislators import FACT_PREFIX

KINDS = ("ly_interpellation", "ly_video", "ly_bill")
# /bills 列表預設不輸出「提案日期」（只在單筆有），要用 output_fields 指定（2026-10-03 對實際回應確認）
BILL_FIELDS = ["議案編號", "議案名稱", "議案類別", "議案狀態", "提案人", "提案日期"]


def interpellation_facts(rows, name):
    out = []
    for r in rows:
        names = r.get("質詢委員") or []
        if isinstance(names, str):
            names = [names]
        if name not in names or not r.get("質詢編號"):
            continue
        out.append({
            "key": f"ly_interpellation:{r['質詢編號']}",
            "date": lyapi.to_date(r.get("刊登日期") or r.get("會議日期")),
            "data": {"title": (r.get("事由") or "").strip(), "no": r["質詢編號"], "meet_id": r.get("會議代碼"),
                     "session": r.get("會期"), "co_legislators": [n for n in names if n != name],
                     "page_start": r.get("質詢起始頁"), "page_end": r.get("質詢結束頁")},
            "source_url": lyapi.item_url("interpellation", r["質詢編號"]),
        })
    return out


def video_facts(rows, name):
    out = []
    for r in rows:
        url = str(r.get("IVOD_URL") or "").replace("http://", "https://", 1)
        if r.get("委員名稱") != name or not r.get("IVOD_ID") or not url.startswith("https://"):
            continue
        meet = r.get("會議資料") or {}
        out.append({
            "key": f"ly_video:{r['IVOD_ID']}",
            "date": lyapi.to_date(r.get("日期") or r.get("會議時間")),
            "data": {"title": (meet.get("標題") or r.get("會議名稱") or "").strip(), "ivod_id": r["IVOD_ID"],
                     "meet_id": meet.get("會議代碼"), "speech_time": r.get("委員發言時間"),
                     "committees": meet.get("委員會代碼:str") or []},
            "source_url": url,
        })
    return out


def bill_facts(rows, name):
    out = []
    for r in rows:
        proposers = r.get("提案人") or []
        if isinstance(proposers, str):
            proposers = [proposers]
        if name not in proposers or not r.get("議案編號"):
            continue
        out.append({
            "key": f"ly_bill:{r['議案編號']}",
            "date": lyapi.to_date(r.get("提案日期")),
            "data": {"title": (r.get("議案名稱") or "").strip(), "bill_no": r["議案編號"],
                     "category": r.get("議案類別"), "status": r.get("議案狀態")},
            "source_url": lyapi.item_url("bill", r["議案編號"]),
        })
    return out


def linked_legislators(conn):
    """已串到 2026 候選人的現任立委：[(person_id, 立法院姓名)]。"""
    return [(pid, json.loads(data)["ly_name"]) for pid, data in conn.execute(
        "SELECT o.person_id, o.data FROM fact o WHERE o.fact_key LIKE ? AND EXISTS "
        "(SELECT 1 FROM fact c WHERE c.person_id = o.person_id AND c.kind = 'candidacy') ORDER BY o.person_id",
        (f"{FACT_PREFIX}%",))]


def fetch_person(name, fetch_all=lyapi.fetch_all):
    term = {"屆": lyapi.TERM}
    inter, _ = fetch_all("interpellations", {**term, "質詢委員": name})
    ivods, _ = fetch_all("ivods", {**term, "委員名稱": name, "影片種類": "Clip"})
    bills, _ = fetch_all("bills", {**term, "提案人": name, "output_fields": BILL_FIELDS})
    return interpellation_facts(inter, name) + video_facts(ivods, name) + bill_facts(bills, name)


def replace_facts(conn, person_id, facts, fetched_at):
    keys = set()
    for f in facts:
        key = f"{f['key']}:{person_id}"
        keys.add(key)
        upsert_fact(conn, key, person_id, f["key"].split(":")[0], f["data"], f["source_url"], fetched_at, date=f["date"])
    marks = ",".join("?" * len(KINDS))
    for (k,) in conn.execute(f"SELECT fact_key FROM fact WHERE person_id = ? AND kind IN ({marks})",
                             (person_id, *KINDS)).fetchall():
        if k not in keys:
            conn.execute("DELETE FROM fact WHERE fact_key = ?", (k,))


def run(conn):
    fetched_at = now_utc()
    linked = linked_legislators(conn)
    # 串接撤銷（或不再參選）的人：舊的立法院紀錄不能留在候選人身上
    marks = ",".join("?" * len(KINDS))
    keep = {pid for pid, _ in linked}
    for (pid,) in conn.execute(f"SELECT DISTINCT person_id FROM fact WHERE kind IN ({marks})", KINDS).fetchall():
        if pid not in keep:
            conn.execute(f"DELETE FROM fact WHERE person_id = ? AND kind IN ({marks})", (pid, *KINDS))
    for person_id, name in linked:
        facts = fetch_person(name)
        replace_facts(conn, person_id, facts, fetched_at)
        n = {k: sum(1 for f in facts if f["key"].startswith(f"{k}:")) for k in KINDS}
        print(f"{name}（{person_id}）：質詢 {n['ly_interpellation']}、影片 {n['ly_video']}、提案 {n['ly_bill']}")
