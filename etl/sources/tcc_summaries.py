"""臺北市議員口頭質詢摘要（NotebookLM 依公報速記錄產生）。來源：repo 內的 data/summaries/14-0N.json，不連網。

data/summaries/ 由 scripts/summaries/batch.py 產生並 commit；每位議員每個會期一筆 fact。
上線閘門：只收 review.status 為 "approved" 的會期檔（batch 產生時一律是 pending，人工審閱後才改）。
只寫 identity.csv 裡 tcc14 有對照的議員。
"""
import json
from pathlib import Path

from etl.db import upsert_fact
from etl.sources.tcc_councilors import load_identity

SUMMARIES_DIR = Path(__file__).resolve().parents[2] / "data" / "summaries"


def run(conn, summaries_dir=SUMMARIES_DIR, identity=None):
    person_ids = {pid for pid, _ in (identity or load_identity()).values()}
    n = 0
    for path in sorted(Path(summaries_dir).glob("14-*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        status = (doc.get("review") or {}).get("status")
        if status != "approved":
            print(f"tcc_summaries：{path.name} 審閱狀態 {status or '（未標記）'}，未經 approved，跳過")
            continue
        for s in doc["summaries"]:
            if s["person_id"] not in person_ids or not s["sources"]:
                continue
            upsert_fact(
                conn, f"summary:{doc['session']}:{s['person_id']}", s["person_id"], "summary",
                {k: s[k] for k in ("issues", "sources", "status", "generator", "generated_at", "disclaimer")}
                | {"session": doc["label"]},
                s["sources"][0]["transcript_url"],
                s["generated_at"] or doc["generated_at"],  # no_speech 沒有產生時間，用該會期檔的時間
                date=doc["last_date"],
            )
            n += 1
    print(f"tcc_summaries：{n} 筆")
