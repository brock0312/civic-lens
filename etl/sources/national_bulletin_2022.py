"""2022 選舉公報（議員與縣市長）的政見與學經歷，掛到有任職 fact 且登記 2026 參選的現任者（L3-A）。臺北由 tpe_bulletin_2022 負責。
網站只呈現 2026 候選人（2026-10-03 使用者決定），沒參選的現任者不處理，先前寫給他們的公報 facts 由 run() 最後的清理刪掉。

切格與關卡都在 etl.bulletin_grid.process()（身分必須和中選會開票完全一致、欄位必須是 -raw 子字串、圖片／亂碼／看不見的字丟欄）。
這裡只做串接：任職 fact 的人 → 同縣市、同選區的 2022 候選人（姓名一致）→ 號次 → 公報切出的列。

- facts 格式照臺北（platform、profile；學經歷用同一套 split_items 接行與條列）；另寫 kind=bulletin：
  對到公報檔的人一律記下原檔網址與頁碼，政見或學經歷沒收到時前端只放原檔連結（使用者 2026-10-02 決定）。
- 姓名只差異體字（黄／黃）的人只放原檔連結，不寫政見（同一決定）。
- 同一份 PDF 出現在兩個目錄（新北市長檔＝議員第 12 區檔、臺中市長檔含第 1 區）：市長取市長檔、議員取議員檔，同一人只寫一次。
"""
import json
import time
from pathlib import Path

from etl.bulletin2022 import _req, file_map
from etl.bulletin_grid import B_FAMILY, NO_TEXT_FILES, NO_TEXT_LAYER, cut_pages, cut_pages_b, process
from etl.cec2022 import SOURCES, TICKETS, parse_candidates
from etl.db import upsert_fact
from etl.fetch import get_json, now_utc
from etl.match import VARIANTS, han
from etl.sources.national_districts import COUNTIES
from etl.sources.tpe_bulletin_2022 import ELECTION, VOTE_DATE, bulletin_url, norm_name, split_items, write_bulletin_facts

ROOT = Path(__file__).resolve().parents[2]
PDF_ROOT = ROOT / "data" / "cache" / "bulletin2022"
INDEX = ROOT / "tests" / "fixtures" / "bulletin2022_index.json"
ISOS = ["nwt", "tao", "txg", "tnn", "khh", "kee", "cyq", "nan", "mia", "hua", "cha", "hsq", "hsz", "kin", "lie"]
NAMES = dict(COUNTIES)
KINDS = ("platform", "profile", "bulletin")
_VAR = str.maketrans(VARIANTS)


# ---------- 純函式 ----------

def own_dir(path, office):
    """檔案所在目錄和職位相符：03直轄市長／04縣市長 的市長、議員目錄的議員。"""
    return ("長/" in path.split("111年")[0]) == (office == "mayor")


def file_for(files, office, n):
    """涵蓋該選區的公報檔路徑，職位相符的目錄優先；沒有回 None。files：file_map 的列。"""
    hits = [f["path"] for f in files if [office, n] in f["districts"]]
    return next((p for p in hits if own_dir(p, office)), hits[0] if hits else None)


def pick_rows(results):
    """[(path, process 的 rows)] → {(office, district_n, cand_no): (path, row)}；同一人出現在多檔，取職位相符目錄的那份。"""
    out = {}
    for path, rows in results:
        for r in rows:
            k = (r["office"], r["district_n"], r["cand_no"])
            if k not in out or (own_dir(path, r["office"]) and not own_dir(out[k][0], r["office"])):
                out[k] = (path, r)
    return out


def to_cand(row):
    """process 的列 → write_bulletin_facts 的 cand（platform 文字；education、experience 為條列，None 表示不收）。
    學經歷照臺北整組收或整組不收：兩欄都要通過關卡，只有「空白」（候選人沒填）視為空清單；兩欄都空就不收。"""
    dropped = row["dropped"]
    edu, exp = (split_items(row[f].split("\n")) if row[f] else [] for f in ("education", "experience"))
    ok = all(row[f] is not None or dropped.get(f) == "空白" for f in ("education", "experience")) and (edu or exp)
    return {"platform": row["platform"], "education": edu if ok else None, "experience": exp if ok else None}


def match_cec(name, cands):
    """任職者姓名 → (同選區 2022 候選人, 是否可寫政見, 原因)。
    完整姓名一致，或漢字部分一致（原住民姓名拼音詞序各來源不同）且同選區唯一 → 可寫；只差異體字 → 只放原檔連結。"""
    for same, full in ((lambda c: norm_name(c["name"]) == norm_name(name), True),
                       (lambda c: han(c["name"]) == han(name), True),
                       (lambda c: han(c["name"]).translate(_VAR) == han(name).translate(_VAR), False)):
        hits = [c for c in cands if same(c)]
        if len(hits) == 1:
            return hits[0], full, None if full else f"姓名異體字（開票 {hits[0]['name']}）"
        if hits:
            return None, False, f"同選區 2022 同名候選人 {len(hits)} 人"
    return None, False, "同選區 2022 候選人沒有此人"


def plan_person(person, cec, files, picked):
    """一位任職者 → {status: full|link|missing, path, page, cand, reason}。cec：{(iso, office, n): {號次: 候選人}}。"""
    key = (person["iso"], person["office"], person["district_n"])
    c, full, why = match_cec(person["name"], list(cec.get(key, {}).values()))
    if c is None:
        return {"status": "missing", "reason": why}
    hit = picked.get((person["office"], person["district_n"], c["cand_no"]))
    path = hit[0] if hit else file_for(files, person["office"], person["district_n"])
    if path is None:
        return {"status": "missing", "reason": "沒有涵蓋此選區的公報檔"}
    if hit and full:
        return {"status": "full", "path": path, "page": hit[1]["page"], "cand": to_cand(hit[1]), "reason": None}
    reason = why or (NO_TEXT_FILES.get(path) and f"無文字層（{NO_TEXT_FILES[path]}）") or "公報列未通過身分關卡"
    return {"status": "link", "path": path, "page": hit[1]["page"] if hit else None, "reason": reason}


# ---------- 讀取 ----------

def pdf_path(path):
    p = PDF_ROOT / path
    if not p.exists():  # 快取優先；缺檔才下載（_req：civic-lens-etl UA、間隔 ≥1.1 秒）
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_req(bulletin_url(path)))
    return p


def fetch_cec():
    out = {}
    for kind, path in SOURCES:
        time.sleep(1.1)
        for c in parse_candidates(get_json(f"{TICKETS}/{path}"), kind):
            if c["iso"] in ISOS:
                out.setdefault((c["iso"], "mayor" if kind == "mayor" else "councilor", c["district_n"]), {})[c["cand_no"]] = c
    return out


def load_targets(conn, iso):
    """有任職 fact 的議員（national_councilors）與市長（national_heads），且有 2026 candidacy fact。"""
    rows = conn.execute(
        "SELECT f.person_id, p.name, f.data FROM fact f JOIN person p USING (person_id) "
        "WHERE f.kind = 'office' AND (f.fact_key LIKE ? OR f.fact_key LIKE ?) "
        "AND EXISTS (SELECT 1 FROM fact c WHERE c.person_id = f.person_id AND c.kind = 'candidacy') ORDER BY f.fact_key",
        (f"office:{iso}-council-2022:%", f"office:{iso}-mayor-2022:%"),
    ).fetchall()
    out = []
    for person_id, name, data in rows:
        d = json.loads(data)
        mayor = d["office"].endswith("_mayor")
        out.append({"person_id": person_id, "name": name, "iso": iso, "office": "mayor" if mayor else "councilor",
                    "district_n": None if mayor else int(d["district_id"].rsplit("-", 1)[1]),
                    "office_code": d["office"], "district_id": d["district_id"]})
    return out


def run(conn):
    fetched_at = now_utc()
    cec = fetch_cec()
    all_files = [f for f in file_map(json.loads(INDEX.read_text(encoding="utf-8"))) if f["iso"] in ISOS]
    written_keys, urls = set(), set()
    for iso in ISOS:
        county = NAMES[iso]
        files = [f for f in all_files if f["iso"] == iso]
        results = []
        for f in files:
            urls.add(bulletin_url(f["path"]))
            if county in NO_TEXT_LAYER or f["path"] in NO_TEXT_FILES:
                continue
            cutter = cut_pages_b if county in B_FAMILY else cut_pages
            rep = process(pdf_path(f["path"]), iso, f["districts"], cec, cutter)
            results.append((f["path"], rep["rows"]))
        picked = pick_rows(results)
        targets = load_targets(conn, iso)
        n = {"platform": 0, "profile": 0, "link": 0}
        missing, links = [], []
        for t in targets:
            plan = plan_person(t, cec, files, picked)
            if plan["status"] == "missing":
                missing.append(f"{t['name']}（{t['district_id']}：{plan['reason']}）")
                continue
            url = bulletin_url(plan["path"])
            data = {"election": ELECTION, "office": t["office_code"], "district_id": t["district_id"], "title": "2022 選舉公報"}
            if plan["page"]:
                data["page"] = plan["page"]
            key = f"bulletin:{ELECTION}:{t['person_id']}"
            upsert_fact(conn, key, t["person_id"], "bulletin", data, url, fetched_at, date=VOTE_DATE)
            written_keys.add(key)
            written = []
            if plan["status"] == "full":
                written = write_bulletin_facts(conn, t["person_id"], plan["cand"], t["office_code"], t["district_id"],
                                               url, fetched_at)
                written_keys.update(f"{k}:{ELECTION}:{t['person_id']}" for k in written)
                for k in written:
                    n[k] += 1
            if not written:
                n["link"] += 1
                links.append(f"{t['name']}（{plan['reason'] or '政見與學經歷欄都未收'}）")
        print(f"{iso} 公報：對象 {len(targets)} 人，政見 {n['platform']}、學經歷 {n['profile']}、"
              f"只有原檔連結 {n['link']}、找不到 {len(missing)}", flush=True)
        for m in missing:
            print(f"  找不到 {m}")
        print(f"  只有原檔連結：{'、'.join(links) or '無'}")
    # 公報是定稿，但任職名單會變：這幾份公報寫出、本次沒寫到的 facts（離職、改串他人）刪掉
    marks = ",".join("?" * len(KINDS))
    stale = [k for (k, u) in conn.execute(f"SELECT fact_key, source_url FROM fact WHERE kind IN ({marks})", KINDS)
             if u in urls and k not in written_keys]
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    print(f"公報：刪除不再寫入的 facts {len(stale)} 筆", flush=True)
