"""解析 NotebookLM 回答、自動檢查，產出摘要 JSON 與審閱稿（質詢摘要 S1）。

用法：python3 scripts/summaries/check_report.py 05 <輸出目錄> 姓名 [姓名 ...]
輸入：cache 裡的 seg_<person_id>.txt／.json（segment.py）與 nlm_<person_id>.json（summarize.py）。
輸出：<輸出目錄>/summaries_pilot.json、<輸出目錄>/review.md

自動檢查（不通過的摘要標出來，不丟掉）：
  1. 引文定位：每個 cited_text 都要在該議員的切分文字裡找得到，找不到標「引文無法定位」。
  2. 禁用詞：媒體式評價動詞。
  3. 每個議題至少 1 條引文。
  4. 人名：只能是該議員本人，或其段落裡出現過的官員（以全屆議員名單＋全會期官員發言標籤比對；
     中央官員、民眾等其他人名無法自動偵測，要人工看）。
"""
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "transcripts"
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from segment import load_docs, load_identity  # noqa: E402

DISCLAIMER = "質詢摘要為AI產出，僅供參考用途，詳細事實以原質詢速記錄與影片為準"  # 使用者已確認（2026-10-01）
BANNED = ["痛批", "砲轟", "怒嗆", "狠批", "打臉", "嗆", "轟", "酸"]
MARK = re.compile(r"\[(\d+(?:\s*[-–,，]\s*\d+)*)\]")
TOPIC = re.compile(r"^\s*(?:#+\s*)?(?:\*\*)?\s*議題\s*[：:]\s*(.+?)(?:\*\*)?\s*$")
FIELD = re.compile(r"^\s*[-*]\s*(?:\*\*)?\s*(議員|市府回應)\s*(?:\*\*)?\s*[：:]\s*(?:\*\*)?\s*(.*)$")
TITLES = ["副總工程司", "總工程司", "副主任委員", "主任委員", "副秘書長", "秘書長", "主任秘書", "副總經理", "總經理", "董事長",
          "執行長", "副市長", "市長", "副局長", "局長", "副處長", "處長", "副主委", "主委", "大隊長", "分局長", "隊長", "署長",
          "副主任", "主任", "發言人", "參事", "專員", "技正", "總工程師", "工程司"]


def numbers(marks):
    """「1, 2」「3-5」→ [1, 2]、[3, 4, 5]。"""
    out = []
    for part in re.split(r"\s*[,，]\s*", marks):
        lo, _, hi = re.sub(r"\s", "", part).replace("–", "-").partition("-")
        out += list(range(int(lo), int(hi) + 1)) if hi else [int(lo)]
    return out


def parse_answer(answer):
    """NotebookLM 回答（固定格式，含 [n] 引文標記）→ [{topic, councilor_points:[(文字, [n])], response:(文字, [n])|None}]。"""
    issues, cur = [], None
    for line in answer.splitlines():
        t = TOPIC.match(line)
        if t:
            cur = {"topic": MARK.sub("", t.group(1)).strip(), "councilor_points": [], "response": None,
                   "topic_marks": [n for m in MARK.findall(t.group(1)) for n in numbers(m)]}
            issues.append(cur)
            continue
        f = FIELD.match(line)
        if f and cur is not None:
            text = f.group(2).strip().rstrip("*").strip()
            marks = [n for m in MARK.findall(text) for n in numbers(m)]
            clean = re.sub(r"\s+([，。；、])", r"\1", MARK.sub("", text)).strip()
            if f.group(1) == "議員":
                cur["councilor_points"].append((clean, marks))
            elif clean not in ("無", "無。", ""):
                cur["response"] = (clean, marks)
        elif cur is not None and line.strip() and cur["councilor_points"]:  # 換行續寫：併到上一個欄位
            text = line.strip()
            marks = [n for m in MARK.findall(text) for n in numbers(m)]
            target = "response" if cur["response"] else None
            if target:
                cur["response"] = (cur["response"][0] + MARK.sub("", text), cur["response"][1] + marks)
            else:
                last = cur["councilor_points"][-1]
                cur["councilor_points"][-1] = (last[0] + MARK.sub("", text), last[1] + marks)
    return issues


def norm(s):
    return re.sub(r"\s+", "", s or "")


def locate(cited, seg_text, spans):
    """cited_text → (是否定位成功, 所在 span)。比對時忽略空白；NotebookLM 用「…」省略時，各段須依序出現。"""
    hay = norm(seg_text)
    pieces = [p for p in re.split(r"…+|\.{3,}", norm(cited)) if p]
    if not pieces:
        return False, None
    pos, first = 0, None
    for p in pieces:
        i = hay.find(p, pos)
        if i < 0:
            return False, None
        first = i if first is None else first
        pos = i + len(p)
    # 把去空白後的位置換回原文位置
    raw_pos, k = 0, -1
    for raw_pos, ch in enumerate(seg_text):
        if not ch.isspace():
            k += 1
            if k == first:
                break
    span = next((s for s in spans if s["start"] <= raw_pos < s["end"]), None)
    return True, span


def official_names(labels):
    """官員發言標籤 → 可能出現在摘要裡的稱呼（姓名「謝銘鴻」、姓＋職稱「謝局長」）。"""
    out = set()
    for label in labels:
        for title in TITLES:
            m = re.search(rf"([一-龥]){title}([一-龥]{{1,2}})$", label)
            if m:
                out |= {m.group(1) + m.group(2), m.group(1) + title}
                break
    return out


def check(summary, seg_text, seg_index, session_labels, identity):
    name = summary["name"]
    problems = []
    body = summary_text(summary)
    for issue in summary["issues"]:
        if not issue["citations"]:
            problems.append(f"議題「{issue['topic']}」沒有引文")
        for c in issue["citations"]:
            if not c["located"]:
                problems.append(f"引文無法定位（議題「{issue['topic']}」[{c['n']}]）：{c['cited_text'][:60]}")
    for w in BANNED:
        for m in re.finditer(w, body):
            problems.append(f"禁用詞「{w}」：…{body[max(0, m.start() - 12):m.end() + 12]}…")
    for other in sorted(set(identity) - {name}):
        if other in body:
            problems.append(f"提到其他議員：{other}")
    own_labels = {s["speaker"] for s in seg_index["spans"]}
    allowed = official_names(own_labels)
    for nm in sorted(official_names(session_labels) - allowed):
        if nm in body:
            problems.append(f"提到段落裡沒有出現的官員：{nm}")
    return problems


def summary_text(summary):
    parts = []
    for i in summary["issues"]:
        parts += [i["topic"], *i["councilor_points"], i["response"] or ""]
    return "\n".join(parts)


def build_summary(nlm, seg_text, seg_index):
    refs = {}
    for r in nlm["references"]:
        refs.setdefault(r.get("citation_number"), []).append(r)
    issues = []
    for it in parse_answer(nlm["answer"]):
        cites, seen = [], set()
        fields = [("topic", it["topic_marks"])] + [("councilor", m) for _, m in it["councilor_points"]]
        if it["response"]:
            fields.append(("response", it["response"][1]))
        for field, marks in fields:
            for n in marks:
                for r in refs.get(n, []):
                    key = (n, r.get("cited_text"))
                    if key in seen:
                        continue
                    seen.add(key)
                    ok, span = locate(r.get("cited_text") or "", seg_text, seg_index["spans"])
                    own_source = r.get("source_id") == nlm["source_id"]
                    cites.append({
                        "n": n, "field": field, "cited_text": r.get("cited_text") or "",
                        "located": ok and own_source, "source_id_ok": own_source,
                        "source_url": f"{span['source_url']}#page={span['pdf_page']}" if span else None,
                        "page": span["gaz_page"] if span else None, "pdf_page": span["pdf_page"] if span else None,
                        "speaker": span["speaker"] if span else None, "heading": span["heading"] if span else None,
                        "date": span["date"] if span else None,
                    })
        issues.append({
            "topic": it["topic"],
            "councilor_points": [t for t, _ in it["councilor_points"]],
            "response": it["response"][0] if it["response"] else None,
            "citations": cites,
        })
    sources = []
    for g in seg_index["groups"]:
        sources.append({
            "heading": g["heading"], "doc_type": g["doc_type"], "dept": g["dept"], "group": g["group"],
            "dates": g["dates"], "transcript_url": g["source_url"],
            "transcript_pages": g["gaz_pages"], "pdf_pages": g["pdf_pages"],
            "transcript_page_url": f"{g['source_url']}#page={g['pdf_pages'][0]}" if g["pdf_pages"] else g["source_url"],
            "videos": g["videos"], "roster": g["roster"], "roster_source": g["roster_source"],
            "own_turns": g["own_turns"],
        })
    return {
        "person_id": seg_index["person_id"], "name": seg_index["name"], "session": seg_index["session"],
        "issues": issues, "sources": sources, "generator": "NotebookLM", "generated_at": nlm["asked_at"],
        "disclaimer": DISCLAIMER,
        "notebooklm": {"notebook_id": nlm["notebook_id"], "source_id": nlm["source_id"], "ask_sec": nlm["ask_sec"]},
    }


def review_md(summaries):
    out = [f"# 質詢摘要試做審閱稿（{summaries[0]['session']}，{len(summaries)} 位議員）", "",
           f"產生時間：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}　產生器：NotebookLM　",
           f"聲明（每則摘要旁顯示）：「{DISCLAIMER}」", "",
           "| 議員 | 議題數 | 引文數 | 無法定位 | 自動檢查 |", "|---|---|---|---|---|"]
    for s in summaries:
        c = [x for i in s["issues"] for x in i["citations"]]
        out.append(f"| {s['name']} | {len(s['issues'])} | {len(c)} | {sum(not x['located'] for x in c)} | "
                   f"{'通過' if not s['check']['problems'] else '⚠ ' + str(len(s['check']['problems'])) + ' 項'} |")
    for s in summaries:
        out += ["", "---", "", f"## {s['name']}（{s['person_id']}）", "",
                f"> {s['disclaimer']}", "", "### 自動檢查", ""]
        out += [f"- ⚠ {p}" for p in s["check"]["problems"]] or ["- 全部通過"]
        out += ["", "### 摘要", ""]
        for k, i in enumerate(s["issues"], 1):
            out += [f"**{k}. {i['topic']}**", ""]
            out += [f"- 議員：{p}" for p in i["councilor_points"]]
            out.append(f"- 市府回應：{i['response'] or '（無）'}")
            out += ["", "<details><summary>引文（" + str(len(i["citations"])) + " 條）</summary>", ""]
            for c in i["citations"]:
                where = (f"[{c['heading']} 公報第{c['page']}頁]({c['source_url']})　{c['speaker']}"
                         if c["source_url"] else "**引文無法定位**")
                out.append(f"- [{c['n']}]（{ {'topic': '議題', 'councilor': '議員', 'response': '回應'}[c['field']] }）"
                           f"{where}：「{c['cited_text'][:300]}{'…' if len(c['cited_text']) > 300 else ''}」")
            out += ["", "</details>", ""]
        out += ["### 原質詢出處", "", "| 場次 | 日期 | 速記錄 | 影片 | 本人發言段數 |", "|---|---|---|---|---|"]
        for src in s["sources"]:
            pages = src["transcript_pages"]
            page_txt = f"公報第{pages[0]}–{pages[-1]}頁" if pages else "（無發言）"
            vids = "、".join(
                f"[{v['date']} 第{v['video_group']}組]({v['url']})" + ("" if v["seekable"] else f"（從 {int(v['start_sec'] // 60)} 分起）")
                for v in src["videos"]) or "（對不到影片）"
            extra = "" if src["roster_source"] == "公報表頭" else f"；組員來源：{src['roster_source']}"
            out.append(f"| {src['heading']}（同組 {len(src['roster'])} 人{extra}） | {'、'.join(src['dates'])} | "
                       f"[{page_txt}]({src['transcript_page_url']}) | {vids} | {src['own_turns']} |")
    return "\n".join(out) + "\n"


def run(session, out_dir, names):
    cache = CACHE / f"14-{session}"
    identity = load_identity()
    session_labels = {t["speaker"] for _, p in load_docs(session) for t in p["turns"]}
    summaries = []
    for name in names:
        pid = identity[name]
        seg_text = (cache / f"seg_{pid}.txt").read_text()
        seg_index = json.loads((cache / f"seg_{pid}.json").read_text())
        nlm = json.loads((cache / f"nlm_{pid}.json").read_text())
        s = build_summary(nlm, seg_text, seg_index)
        s["check"] = {"problems": check(s, seg_text, seg_index, session_labels, identity)}
        s["check"]["passed"] = not s["check"]["problems"]
        summaries.append(s)
        print(name, "議題", len(s["issues"]), "問題", len(s["check"]["problems"]))
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summaries_pilot.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=1))
    (out_dir / "review.md").write_text(review_md(summaries))


def demo():
    ans = ("### 議題：捷運站無障礙設施\n- 議員：詢問電梯進度 [1, 2]。\n- 市府回應：交通局局長說明將於年底完工 [3-4]。\n"
           "### 議題：公園管理\n- 議員：要求改善照明 [5]\n- 市府回應：無\n")
    got = parse_answer(ans)
    assert [i["topic"] for i in got] == ["捷運站無障礙設施", "公園管理"], got
    assert got[0]["councilor_points"] == [("詢問電梯進度。", [1, 2])], got[0]
    assert got[0]["response"] == ("交通局局長說明將於年底完工。", [3, 4]) and got[1]["response"] is None, got
    seg = "標題\n〔公報第5頁〕李議員明賢：請問 電梯 何時完工？\n〔公報第6頁〕交通局謝局長銘鴻：年底完工。\n"
    spans = [{"start": 3, "end": 25, "speaker": "李議員明賢", "gaz_page": 5},
             {"start": 26, "end": 50, "speaker": "交通局謝局長銘鴻", "gaz_page": 6}]
    assert locate("請問電梯何時完工", seg, spans)[1]["gaz_page"] == 5
    assert locate("交通局謝局長銘鴻：年底…完工", seg, spans)[1]["gaz_page"] == 6
    assert locate("明年完工", seg, spans) == (False, None)
    assert official_names(["交通局謝局長銘鴻", "蔣市長萬安"]) == {"謝銘鴻", "謝局長", "蔣萬安", "蔣市長"}
    print("demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        run(sys.argv[1], sys.argv[2], sys.argv[3:])
