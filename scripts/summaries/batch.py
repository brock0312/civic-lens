"""質詢摘要量產：第14屆各定期大會，每位議員一份 NotebookLM 摘要。

用法：
  python3 scripts/summaries/batch.py                     第 1–5 次定期大會全部議員
  python3 scripts/summaries/batch.py 05                  只跑第 5 次
  python3 scripts/summaries/batch.py 05 --names 甲 乙    只跑指定議員（驗證用；輸出檔只含這些人）
  python3 scripts/summaries/batch.py 05 --cached         只用 cache 重新檢查與輸出：不抓速記錄、不呼叫 NotebookLM，
                                                          沒有快取回答的議員記為失敗
前置：`notebooklm auth check --test --json` 的 token_fetch 為 true。

每個會期依序：抓速記錄（fetch_transcripts）→ 切分（segment）→ NotebookLM 摘要（summarize）→ 檢查與過濾（check_report）→ 輸出。
  - 可中斷續跑：切分檔、NotebookLM 來源與回答都留在 cache（data/cache/transcripts/14-0N/），已完成的議員直接沿用。
  - 一位議員失敗不中斷整批，記進報告；NotebookLM 登入失效（SystemExit）才整批停下。
  - 整個會期速記錄裡沒有本人發言的議員輸出 status 'no_speech'，不送 NotebookLM。
  - 過濾後沒有議題的摘要不輸出，列進報告。
  - 輸出檔的 review 一律是 pending；人工審閱通過改成 approved 後，ETL（etl/sources/tcc_summaries.py）才會收。
輸出：
  data/summaries/14-0N.json                    要 commit 的資料：摘要、引文（source_url、頁碼、cited_text）、出處清單
  data/cache/transcripts/14-0N/batch_report.json 檢查報告（失敗、被移除的議題、空引文數、自動檢查問題）
  data/cache/transcripts/14-0N/review.md         審閱稿
"""
import json
import pathlib
import sys
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import fetch_transcripts  # noqa: E402
import summarize  # noqa: E402
from check_report import DISCLAIMER, build_summary, checked, review_md, sources_of  # noqa: E402
from segment import (  # noqa: E402
    CACHE, ROOT, build, known_names, load_docs, load_identity, resolve_group, session_label, video_groups,
)

SESSIONS = ["01", "02", "03", "04", "05"]  # 第 6–8 次公報速記錄還沒刊完
OUT = ROOT / "data" / "summaries"


def public_summary(s):
    """內部摘要 → 要 commit 的欄位（不含速記錄全文、cache 路徑、notebook id）。"""
    return {
        "person_id": s["person_id"], "name": s["name"], "status": "ok",
        "issues": [{
            "topic": i["topic"], "councilor_points": i["councilor_points"], "response": i["response"],
            "response_removed": i["response_removed"],
            "citations": [{"source_url": c["source_url"], "page": c["page"], "cited_text": c["cited_text"]}
                          for c in i["citations"]],
        } for i in s["issues"]],
        "sources": public_sources(s["sources"]),
        "generator": s["generator"], "generated_at": s["generated_at"], "disclaimer": s["disclaimer"],
    }


def public_sources(sources):
    """出處清單（check_report.sources_of）→ 公開欄位；videos 只留對應用的鍵（日期＋影片組別），
    前端據此找同日期、同組別的影片 fact。影片組別取自切分時以組員重疊對應的結果，
    公報與影片編號互換的組（第 5 次交通第 8、9 組）也對得上。"""
    return [{
        "heading": g["heading"], "doc_type": g["doc_type"], "dept": g["dept"], "group": g["group"], "dates": g["dates"],
        "transcript_url": g["transcript_url"], "transcript_page_url": g["transcript_page_url"],
        "transcript_pages": g["transcript_pages"],
        "videos": [{"date": v["date"], "group": v["video_group"]} for v in g["videos"]],
    } for g in sources]


def no_speech(index):
    return {"person_id": index["person_id"], "name": index["name"], "status": "no_speech", "issues": [],
            "sources": public_sources(sources_of(index)), "generator": None, "generated_at": None,
            "disclaimer": DISCLAIMER}


def process(session, name, ctx):
    """一位議員 → ('ok', 內部摘要) / ('no_speech', 公開紀錄) / ('dropped', 內部摘要)。失敗時 raise。"""
    cache = CACHE / f"14-{session}"
    pid = ctx["identity"][name]
    seg_txt, seg_json = cache / f"seg_{pid}.txt", cache / f"seg_{pid}.json"
    if not seg_json.exists():  # 已切分的沿用：NotebookLM 回答的引文位置對應的是當時的切分檔
        _, text, index = build(session, name, ctx["docs"], ctx["identity"], ctx["vgroups"])
        seg_txt.write_text(text)
        seg_json.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    index = json.loads(seg_json.read_text())
    if not index["spans"]:
        return "no_speech", no_speech(index)
    if ctx["cached"]:
        if not (cache / f"nlm_{pid}.json").exists():
            raise FileNotFoundError(f"沒有快取的 NotebookLM 回答 nlm_{pid}.json（--cached 不呼叫 NotebookLM）")
    else:
        ctx["state"] = summarize.summarize_one(session, name, pid, ctx["state"])
    nlm = json.loads((cache / f"nlm_{pid}.json").read_text())
    seg_text = seg_txt.read_text()
    s = checked(build_summary(nlm, seg_text, index), seg_text, index, ctx["labels"], ctx["identity"])
    return ("ok" if s["issues"] else "dropped"), s


def run_session(session, only=None, cached=False):
    tag = f"14-{session}"
    if not cached:
        fetch_transcripts.run(session)
    identity, docs, vgroups = load_identity(), load_docs(session), video_groups(session_label(session))
    known = known_names(identity, vgroups)
    scheduled = {n for _, p in docs for n in resolve_group(p, vgroups, known)[0]}
    names = sorted(scheduled & set(identity)) if only is None else only
    dates = [g["date"] for g in vgroups] or [t["date"] for _, p in docs for t in p["turns"] if t["date"]]
    ctx = {"identity": identity, "docs": docs, "vgroups": vgroups, "state": summarize.load_state(session), "cached": cached,
           "labels": {t["speaker"] for _, p in docs for t in p["turns"]}}
    records, internal, report = [], [], {"session": tag, "ok": [], "no_speech": [], "dropped": [], "failed": [],
                                         "filter": {}, "problems": {}}
    for k, name in enumerate(names, 1):
        try:
            status, rec = process(session, name, ctx)
        except Exception as e:  # noqa: BLE001  一位失敗不影響下一位；SystemExit（登入失效）照樣中止
            report["failed"].append({"name": name, "error": f"{type(e).__name__}: {e}"})
            print(f"[{tag} {k}/{len(names)}] {name}：失敗 {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            continue
        report[status].append(name)
        if status == "no_speech":
            records.append(rec)
            print(f"[{tag} {k}/{len(names)}] {name}：no_speech（速記錄中無本人發言，未送 NotebookLM）", flush=True)
            continue
        f = rec["check"]["filter"]
        report["filter"][name] = f
        report["problems"][name] = rec["check"]["problems"]
        internal.append(rec)
        if status == "ok":
            records.append(public_summary(rec))
        print(f"[{tag} {k}/{len(names)}] {name}：{'ok' if status == 'ok' else '不輸出（過濾後沒有議題）'} "
              f"{len(rec['issues'])} 議題，空引文 {f['empty_citations']}、無法定位 {len(f['unlocated_citations'])}、"
              f"短答 {len(f['short_citations'])}、移除回應 {len(f['removed_responses'])}、"
              f"移除議題 {len(f['removed_issues'])}、檢查問題 {len(rec['check']['problems'])}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    stamps = [r["generated_at"] for r in records if r["generated_at"]]
    (OUT / f"{tag}.json").write_text(json.dumps({
        "session": tag, "label": f"第14屆第{int(session)}次定期大會", "last_date": max(dates) if dates else None,
        "generator": "NotebookLM", "generated_at": max(stamps) if stamps else None, "disclaimer": DISCLAIMER,
        "review": {"status": "pending", "by": None, "at": None, "note": None},
        "summaries": records,
    }, ensure_ascii=False, indent=1) + "\n")
    cache = CACHE / tag
    report["totals"] = {k: sum(len(f[k]) for f in report["filter"].values()) for k in (
        "unlocated_citations", "short_citations", "removed_responses", "multi_session_claims", "removed_issues")}
    (cache / "batch_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    if internal:
        (cache / "review.md").write_text(review_md(internal))
    print(f"{tag} 完成：ok {len(report['ok'])}、no_speech {len(report['no_speech'])}、"
          f"不輸出 {len(report['dropped'])}、失敗 {len(report['failed'])} → {OUT / f'{tag}.json'}；{report['totals']}", flush=True)
    return report


def main(argv):
    only = None
    cached = "--cached" in argv
    argv = [a for a in argv if a != "--cached"]
    if "--names" in argv:
        i = argv.index("--names")
        argv, only = argv[:i], argv[i + 1:]
    sessions = argv or SESSIONS
    failed = False
    for session in sessions:
        try:
            report = run_session(session, only, cached)
            failed |= bool(report["failed"])
        except Exception:  # noqa: BLE001  一個會期抓取或解析失敗，繼續下一個會期
            print(f"14-{session} 整個會期失敗：", flush=True)
            traceback.print_exc()
            failed = True
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
