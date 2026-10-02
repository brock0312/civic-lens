"""臺北以外 21 縣市長的任職（V14）：2022 當選人取自中選會開票 JSON，任職異動取自人工維護的 data/head_status.csv。

身分：用 etl.match 串到 2026 候選人；串不到或進審閱的，另建 person（不確定就不併人）。
臺北市長由 tpe_bulletin_2022 負責。
"""
import csv
import hashlib
import json
import time
from pathlib import Path

from etl.cec2022 import SOURCES, TICKETS, parse_candidates
from etl.db import upsert, upsert_fact
from etl.fetch import get_json, now_utc
from etl.match import match
from etl.sources.national_districts import COUNTIES

SOURCE = "cec_2022_head"
STATUS_PATH = Path(__file__).resolve().parents[2] / "data" / "head_status.csv"
EVENTS = {"suspended", "reinstated"}
VOTE_DATE = "2022-11-26"
TERM_START = "2022-12-25"  # 內政部 111-12-25 新聞稿：九合一與嘉義市長重行選舉當選人均於今日宣誓就職（V14 §1.5）
MOI_INAUGURATION = ("https://www.moi.gov.tw/News_Content.aspx?n=4&s=274773", "內政部 2022-12-25 新聞稿")
# 嘉義市長是 12/18 重行選舉（V14 §1.4）
CYI = {"elected_on": "2022-12-18", "election_note": "重行選舉",
       "source_label": "中選會「111年嘉義市長重行選舉」開票結果",
       "inauguration": ("https://www.chiayi.gov.tw/cp.aspx?n=446", "嘉義市政府歷任市長表")}
NAMES = dict(COUNTIES)


def load_status(path=STATUS_PATH):
    """head_status.csv → {iso: [異動, …]}，同一縣市依日期排序。格式不對就 raise。"""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for r in rows:
        if r["iso"] not in NAMES or r["iso"] == "tpe" or r["event"] not in EVENTS:
            raise ValueError(f"head_status.csv 縣市或事件不明：{r}")
        if not r["source_url"].startswith("http") or not r["source_label"] or not r["fetched_at"]:
            raise ValueError(f"head_status.csv 缺出處或擷取日：{r}")
        if r["event"] == "suspended" and not (r["acting_name"] and r["acting_position"] and r["acting_title"]):
            raise ValueError(f"head_status.csv 停止職務缺代理人：{r}")
        ev = {k: v for k, v in r.items() if k != "iso" and v}
        out[r["iso"]] = sorted([*out.get(r["iso"], []), ev], key=lambda e: e["date"])
    return out


def split(heads, candidates):
    """2022 當選人 → (iso → 2026 候選人 person_id 或 None, 進審閱的 iso)。只有 match 的 links 才串。"""
    recs = [{"key": h["iso"], "iso": h["iso"], "name": h["name"], "office": "mayor", "district_n": None} for h in heads]
    out = match(recs, candidates)
    links = {x["key"]: x["person_id"] for x in out["links"]}
    return {h["iso"]: links.get(h["iso"]) for h in heads}, [x["key"] for x in out["review"]]


def head_data(head, events):
    iso = head["iso"]
    extra = CYI if iso == "cyi" else {}
    inaug_url, inaug_label = extra.get("inauguration", MOI_INAUGURATION)
    data = {
        "office": f"{iso}_mayor", "district_id": f"{iso}-mayor", "title": f"{NAMES[iso]}長", "party": head["party"],
        "elected_on": extra.get("elected_on", VOTE_DATE),
        "source_label": extra.get("source_label", "中選會 2022 開票結果"),
        "inauguration_source_url": inaug_url, "inauguration_source_label": inaug_label,
    }
    if "election_note" in extra:
        data["election_note"] = extra["election_note"]
    if events:
        data["status_events"] = events
    return data


def fetch_heads():
    """[{iso, name, party, source_url}]，臺北以外 21 位；嘉義市取重行選舉檔（cec2022.SOURCES 已排除原檔）。"""
    heads = []
    for kind, path in SOURCES:
        if kind != "mayor":
            continue
        time.sleep(1.1)
        url = f"{TICKETS}/{path}"
        heads += [{**c, "source_url": url} for c in parse_candidates(get_json(url), kind)
                  if c["elected"] and c["iso"] != "tpe"]
    isos = [h["iso"] for h in heads]
    if len(isos) != 21 or len(set(isos)) != 21:
        raise ValueError(f"2022 縣市長當選人不是 21 縣市各一位：{sorted(isos)}")
    return heads


def person_id_for(conn, source_key):
    row = conn.execute(
        "SELECT person_id FROM person_source_id WHERE source = ? AND source_key = ?", (SOURCE, source_key)
    ).fetchone()
    if row:
        return row["person_id"]
    return "p" + hashlib.sha1(f"{SOURCE}:{source_key}".encode()).hexdigest()[:10]


def run(conn):
    fetched_at = now_utc()
    heads = fetch_heads()
    status = load_status()
    cands = [{"person_id": r["person_id"], "name": r["name"], "district_id": json.loads(r["data"])["district_id"]}
             for r in conn.execute("SELECT f.person_id, p.name, f.data FROM fact f JOIN person p USING (person_id) "
                                   "WHERE f.kind = 'candidacy'")]
    linked, review = split(heads, cands)
    for h in heads:
        source_key = f"{h['iso']}-mayor:{h['name']}"
        person_id = linked[h["iso"]]
        if person_id:
            verified_by = "auto: etl.match 唯一同名且同縣市（2022 縣市長當選人 vs 2026 候選人登記彙總表）"
        else:
            person_id = person_id_for(conn, source_key)
            verified_by = "auto: 2022 中選會開票 JSON 當選人，未串到 2026 候選人"
            upsert(conn, "person", {"person_id": person_id, "name": h["name"]}, ("person_id",))
        upsert(conn, "person_source_id",
               {"source": SOURCE, "source_key": source_key, "person_id": person_id, "verified_by": verified_by},
               ("source", "source_key"))
        upsert_fact(conn, f"office:{h['iso']}-mayor-2022:{person_id}", person_id, "office",
                    head_data(h, status.get(h["iso"], [])), h["source_url"], fetched_at, date=TERM_START)
    print(f"縣市長任職：串到 2026 候選人 {sum(1 for v in linked.values() if v)} 人，新建 "
          f"{sum(1 for v in linked.values() if not v)} 人；審閱 {review or '無'}；異動 {sorted(status)}")
