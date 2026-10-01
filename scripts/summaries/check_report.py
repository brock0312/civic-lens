"""解析 NotebookLM 回答、自動檢查，產出摘要 JSON 與審閱稿（質詢摘要 S1）。

用法：python3 scripts/summaries/check_report.py 05 <輸出目錄> 姓名 [姓名 ...]
輸入：cache 裡的 seg_<person_id>.txt／.json（segment.py）與 nlm_<person_id>.json（summarize.py）。
輸出：<輸出目錄>/summaries_pilot.json、<輸出目錄>/review.md

自動檢查（不通過的摘要標出來，不丟掉）：
  1. 引文定位：每個 cited_text 都要在該議員的切分文字裡找得到，找不到標「引文無法定位」；有〔公報第N頁〕標記時只在該頁比對，
     候選位置不只一個（不同頁或不同場次）也算無法定位。短答（少於 8 個字）不算佐證。
  2. 禁用詞：媒體式評價動詞。
  3. 每個議題至少 1 條引文。
  4. 人名：只能是該議員本人，或其段落裡出現過的官員（以全屆議員名單＋全會期官員發言標籤比對；
     中央官員、民眾等其他人名無法自動偵測，要人工看）。
  5. 引文相關性（relevance）：議題最相關的引文與議員訴求幾乎沒有共同用字時，整個議題移除。
"""
import bisect
import json
import math
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


# 比對前要忽略的標記：切分時加的頁碼「〔公報第566頁〕」，以及公報的書名號「<藥事法>」（NotebookLM 的 cited_text 會把
# <…> 當成 HTML 標籤整段吃掉，試做中李明賢 [37] 因此對不到）
IGNORED = re.compile(r"〔公報第\d+頁〕|<[^<>\n]{0,40}>")


def squash(s):
    """去掉 IGNORED 標記與所有空白 → (比對用字串, 每個字在原文的位置)。"""
    blanked = IGNORED.sub(lambda m: " " * len(m.group()), s or "")
    keep = [i for i, ch in enumerate(blanked) if not ch.isspace()]
    return "".join(blanked[i] for i in keep), keep


PAGE_MARK = re.compile(r"〔公報第(\d+)頁〕")
MIN_EVIDENCE_CHARS = 8  # 去掉頁碼標記與發言人標籤後少於 8 個字（「是。」「好。」「謝謝。」）不算佐證


def locate(cited, seg_text, spans):
    """cited_text → (是否定位成功, 所在 span)。比對時忽略空白與 IGNORED 標記；NotebookLM 用「…」省略時，各段須依序出現。

    cited_text 帶〔公報第N頁〕時以標記為錨點：只接受涵蓋範圍內有這些頁碼的出現位置，回傳第 N 頁那段。
    沒有標記時退回全文比對。不論哪種，候選位置落在不同頁或不同場次就判定無法定位，不取第一個。"""
    hay, where = squash(seg_text)
    pieces = [p for p in re.split(r"…+|\.{3,}", squash(cited)[0]) if p]
    if not pieces:
        return False, None
    pages = [int(n) for n in PAGE_MARK.findall(cited)]
    starts = [s["start"] for s in spans]
    found = {}
    i = hay.find(pieces[0])
    while i >= 0:
        pos = i + len(pieces[0])
        for p in pieces[1:]:
            j = hay.find(p, pos)
            if j < 0:
                break
            pos = j + len(p)
        else:
            lo, hi = where[i], where[pos - 1]
            touched = [s for s in spans[max(bisect.bisect_right(starts, lo) - 1, 0):bisect.bisect_right(starts, hi)]
                       if s["end"] > lo]
            if pages:
                anchor = next((s for s in touched if s["gaz_page"] == pages[0]), None)
                if anchor and set(pages) <= {s["gaz_page"] for s in touched}:
                    found.setdefault((anchor["source_url"], anchor["gaz_page"]), anchor)
            elif touched and touched[0]["start"] <= lo < touched[0]["end"]:
                found.setdefault((touched[0]["source_url"], touched[0]["gaz_page"]), touched[0])
        i = hay.find(pieces[0], i + 1)
    if len(found) != 1:
        return False, None
    return True, next(iter(found.values()))


def is_short(cited, speakers):
    """去掉頁碼標記、發言人標籤與標點後少於 MIN_EVIDENCE_CHARS 個字 → 短答，不算佐證。"""
    text = re.sub(r"\s", "", PAGE_MARK.sub("", cited))
    for sp in sorted(speakers, key=len, reverse=True):
        text = text.replace(f"{sp}：", "").replace(f"{sp}:", "")
    return len(re.findall(r"[^\W_]", text)) < MIN_EVIDENCE_CHARS


def official_names(labels):
    """官員發言標籤 → 姓名（「交通局謝局長銘鴻」→ 謝銘鴻）。

    只取姓名：提示詞要求官員只寫職稱，所以「秘書處處長」「謝局長」這類職稱不算違規，不檢查。
    姓取第一個職稱前的字，名取最後一個職稱後的 1–2 字（「李秘書長兼秘書處處長泰興」→ 李泰興）。"""
    titles = "|".join(TITLES)
    out = set()
    for label in labels:
        surname = re.search(rf"([一-龥])(?:{titles})", label)
        given = re.search(rf"(?:{titles})([一-龥]{{1,2}})$", label)
        if surname and given:
            out.add(surname.group(1) + given.group(1))
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


def doc_of(c):
    """引文 → 所在速記錄（一份 PDF＝同一場、同一組）。"""
    return c["source_url"].split("#")[0]


def fields_of(c):
    return set(c.get("fields") or [c.get("field")])


# 回應文字比對：NotebookLM 會把官員在其他場次的承諾寫進回應，卻引用本場次的段落（審閱抓到柳采葳、林珍羽各一例），
# 只看引文出處抓不到，所以再用字元雙字組比對每一句回應最像哪一段發言。
ROLE_WORDS = re.compile(r"局長|院長|市長|主任|處長|科長|副|表示|說明|會|將|並|持續|相關|臺北市立|聯合醫院|警察局|教育局|衛生局|社會局")
ELSEWHERE_MIN = 0.4  # 其他場次某段發言涵蓋這句回應的雙字組比例下限
ELSEWHERE_MARGIN = 0.15  # 且要比同場次最像的一段高出這麼多
ELSEWHERE_MIN_BIGRAMS = 3  # 去掉職稱等套語後雙字組太少的句子不判斷


def bigrams(text):
    t = re.sub(r"[\W_]", "", text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def response_elsewhere(response, docs, seg_text, spans):
    """回應裡最像其他場次發言的句子 → [(句子, 該場次標題, 頁碼)]。docs：議員訴求引文所在的速記錄。

    ponytail: 雙字組涵蓋率是粗略的啟發式，門檻依第 5 次會期 223 段回應調出（抓到 3 段，人工看都是錯置）；
    誤判時只會多移除回應、不會留下錯的回應。要更準得改成逐句要求官員答復的引文。"""
    turns = [(s["source_url"], s["heading"], s["gaz_page"], bigrams(seg_text[s["start"]:s["end"]])) for s in spans]
    out = []
    for sent in (t for t in re.split(r"[。；]", response) if t.strip()):
        b = bigrams(ROLE_WORDS.sub("", sent))
        if len(b) < ELSEWHERE_MIN_BIGRAMS:
            continue
        score = lambda t: len(b & t[3]) / len(b)  # noqa: E731
        same = max((score(t) for t in turns if t[0] in docs), default=0)
        best = max(turns, key=score, default=None)
        if best and best[0] not in docs and score(best) >= ELSEWHERE_MIN and score(best) - same >= ELSEWHERE_MARGIN:
            out.append((sent, best[1], best[2]))
    return out


# 引文相關性：NotebookLM 偶爾把無關或只有寒暄的段落當成議員訴求的引文（第 5 次會期第二輪審閱抓到 8 個議題）。
RELEVANCE_MIN = 8.2  # 議題最相關的一條引文，與訴求共有雙字組的 IDF 總和下限


def bigram_idf(texts):
    """會期全部發言段落 → 雙字組 IDF 函式（log(段落數 / (1 + 出現段落數))，不小於 0）。"""
    texts = list(texts)
    df = {}
    for t in texts:
        for b in bigrams(t):
            df[b] = df.get(b, 0) + 1
    return lambda b: max(math.log(len(texts) / (1 + df.get(b, 0))), 0)


def relevance(issue, citations, idf):
    """議員訴求（議題名稱＋議員欄位）與每條引文本文（去掉頁碼標記與發言人標籤）共有雙字組的 IDF 總和，取最高的一條。

    ponytail: 字面重疊的啟發式，IDF 讓「謝謝」「這個」「局長」這類寒暄、附和詞自動趨近 0，不另列停用詞。
    上限：抓不到「引文用字和訴求相同、但內容不支持訴求」的議題（第 5 次會期的李柏毅人口對策委員會，分數 29），
    也會誤殺改寫幅度大的正常議題；門檻依第 5 次會期 8 個人工確認的薄弱議題（抓到 7 個）與 88 個審閱通過的議題（誤殺 0）調出，
    最近的反例只高 0.1（汪志冰土地登記錯置 8.3），換會期要重看分布。要更準得改成逐條引文的語意判斷。"""
    claim = bigrams(issue["topic"] + "".join(issue["councilor_points"]))
    def score(c):  # noqa: E306
        body = re.sub(r"^\s*[^：:\n]{2,20}[：:]", "", PAGE_MARK.sub("", c["cited_text"]).strip())
        return sum(idf(b) for b in bigrams(body) & claim)
    return max((score(c) for c in citations), default=0)


def filter_citations(summary, seg_text=None, spans=None, idf=None):
    """量產後處理，回傳 (新摘要, 報告)；不改輸入。
      - 空引文不保留；無法定位的引文不輸出（沒有頁碼可連）；短答（is_short）不算佐證，也不輸出。
      - 市府回應的引文必須和議員訴求的有效引文出自同一份速記錄；有任何一條來自其他場次，整段回應移除
        （response 設為 None、response_removed 為 True，只佐證該回應的引文一併移除）。
        議員訴求沒有引文時以議題的引文代替。有給 seg_text、spans 時，回應裡有句子最像其他場次的發言（response_elsewhere）
        也整段移除。
      - 議員訴求的引文跨多份速記錄可以接受，只記進報告。
      - 沒有有效引文的議題整個移除。有給 idf（bigram_idf）時，有效引文與訴求的相關性（relevance）低於 RELEVANCE_MIN 的議題
        也整個移除，記進 irrelevant_issues。議題全被移除時，新摘要的 issues 是空的，由呼叫端決定不輸出。"""
    issues, removed, unlocated, short, responses, multi, irrelevant, empty = [], [], [], [], [], [], [], 0
    for issue in summary["issues"]:
        cites = [c for c in issue["citations"] if c["cited_text"].strip()]
        empty += len(issue["citations"]) - len(cites)
        unlocated += [f"議題「{issue['topic']}」[{c['n']}]：{c['cited_text'][:60]}" for c in cites if not c["located"]]
        short += [f"議題「{issue['topic']}」[{c['n']}]：{c['cited_text'][:60]}"
                  for c in cites if c["located"] and c.get("short")]
        valid = [c for c in cites if c["located"] and not c.get("short")]
        claim = [c for c in valid if "councilor" in fields_of(c)] or [c for c in valid if "topic" in fields_of(c)]
        claim_docs = {doc_of(c) for c in claim}
        response, dropped = issue["response"], False
        foreign = [c for c in valid if "response" in fields_of(c) and doc_of(c) not in claim_docs]
        elsewhere = response_elsewhere(response, claim_docs, seg_text, spans) if response and seg_text else []
        if response and (foreign or elsewhere):
            response, dropped = None, True
            valid = [c for c in valid if fields_of(c) != {"response"}]
            why = ("引文出自 " + "、".join(sorted({c.get('heading') or doc_of(c) for c in foreign})) if foreign else
                   "；".join(f"「{t[:30]}」最像 {h} 公報第{p}頁" for t, h, p in elsewhere))
        if not valid:  # 議題整個移除時，回應與跨場次只記在 removed_issues
            removed.append(issue["topic"])
            continue
        score = relevance(issue, valid, idf) if idf else None
        if score is not None and score < RELEVANCE_MIN:
            irrelevant.append({"topic": issue["topic"], "score": round(score, 1)})
            continue
        if dropped:
            responses.append(f"議題「{issue['topic']}」：{issue['response'][:60]}（{why}）")
        if len(claim_docs) > 1:
            multi.append(issue["topic"])
        issues.append({**issue, "response": response, "response_removed": dropped, "citations": valid})
    report = {"empty_citations": empty, "unlocated_citations": unlocated, "short_citations": short,
              "removed_responses": responses, "multi_session_claims": multi, "removed_issues": removed,
              "irrelevant_issues": irrelevant}
    return {**summary, "issues": issues}, report


def summary_text(summary):
    parts = []
    for i in summary["issues"]:
        parts += [i["topic"], *i["councilor_points"], i["response"] or ""]
    return "\n".join(parts)


def sources_of(seg_index):
    """切分索引的各組 → 出處清單（速記錄頁碼連結、影片）。"""
    return [{
        "heading": g["heading"], "doc_type": g["doc_type"], "dept": g["dept"], "group": g["group"],
        "dates": g["dates"], "transcript_url": g["source_url"],
        "transcript_pages": g["gaz_pages"], "pdf_pages": g["pdf_pages"],
        "transcript_page_url": f"{g['source_url']}#page={g['pdf_pages'][0]}" if g["pdf_pages"] else g["source_url"],
        "videos": g["videos"], "roster": g["roster"], "roster_source": g["roster_source"],
        "own_turns": g["own_turns"],
    } for g in seg_index["groups"]]


def build_summary(nlm, seg_text, seg_index):
    refs = {}
    for r in nlm["references"]:
        refs.setdefault(r.get("citation_number"), []).append(r)
    speakers = {s["speaker"] for s in seg_index["spans"]}
    issues = []
    for it in parse_answer(nlm["answer"]):
        cites, seen = [], {}
        fields = [("topic", it["topic_marks"])] + [("councilor", m) for _, m in it["councilor_points"]]
        if it["response"]:
            fields.append(("response", it["response"][1]))
        for field, marks in fields:
            for n in marks:
                for r in refs.get(n, []):
                    key = (n, r.get("cited_text"))
                    if key in seen:  # 同一條引文被多個欄位引用：記下所有欄位（市府回應的同場次檢查要用）
                        if field not in seen[key]["fields"]:
                            seen[key]["fields"].append(field)
                        continue
                    ok, span = locate(r.get("cited_text") or "", seg_text, seg_index["spans"])
                    own_source = r.get("source_id") == nlm["source_id"]
                    cites.append({
                        "n": n, "field": field, "fields": [field], "cited_text": r.get("cited_text") or "",
                        "short": is_short(r.get("cited_text") or "", speakers),
                        "located": ok and own_source, "source_id_ok": own_source,
                        "source_url": f"{span['source_url']}#page={span['pdf_page']}" if span else None,
                        "page": span["gaz_page"] if span else None, "pdf_page": span["pdf_page"] if span else None,
                        "speaker": span["speaker"] if span else None, "heading": span["heading"] if span else None,
                        "date": span["date"] if span else None,
                    })
                    seen[key] = cites[-1]
        issues.append({
            "topic": it["topic"],
            "councilor_points": [t for t, _ in it["councilor_points"]],
            "response": it["response"][0] if it["response"] else None,
            "citations": cites,
        })
    return {
        "person_id": seg_index["person_id"], "name": seg_index["name"], "session": seg_index["session"],
        "issues": issues, "sources": sources_of(seg_index), "generator": "NotebookLM", "generated_at": nlm["asked_at"],
        "disclaimer": DISCLAIMER,
        "notebooklm": {"notebook_id": nlm["notebook_id"], "source_id": nlm["source_id"], "ask_sec": nlm["ask_sec"]},
    }


def checked(summary, seg_text, seg_index, session_labels, identity, idf=None):
    """過濾引文＋自動檢查 → 附上 check（problems 含被移除的議題與無法定位的引文）的新摘要。"""
    s, f = filter_citations(summary, seg_text, seg_index["spans"], idf)
    problems = [f"議題「{t}」沒有可定位的引文，已移除" for t in f["removed_issues"]]
    problems += [f"議題「{x['topic']}」的引文未佐證議員訴求（相關性 {x['score']}），已移除" for x in f["irrelevant_issues"]]
    problems += [f"引文無法定位，已移除（{u}）" for u in f["unlocated_citations"]]
    problems += [f"市府回應出自其他場次，整段回應已移除（{r}）" for r in f["removed_responses"]]
    problems += check(s, seg_text, seg_index, session_labels, identity)
    return {**s, "check": {"problems": problems, "passed": not problems, "filter": f}}


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
            out.append(f"- 市府回應：{'（出自其他場次，已移除）' if i.get('response_removed') else i['response'] or '（無）'}")
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
    docs = load_docs(session)
    session_labels = {t["speaker"] for _, p in docs for t in p["turns"]}
    idf = bigram_idf(t["text"] for _, p in docs for t in p["turns"])
    summaries = []
    for name in names:
        pid = identity[name]
        seg_text = (cache / f"seg_{pid}.txt").read_text()
        seg_index = json.loads((cache / f"seg_{pid}.json").read_text())
        nlm = json.loads((cache / f"nlm_{pid}.json").read_text())
        s = checked(build_summary(nlm, seg_text, seg_index), seg_text, seg_index, session_labels, identity, idf)
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
    spans = [{"start": 3, "end": 25, "speaker": "李議員明賢", "gaz_page": 5, "source_url": "A"},
             {"start": 26, "end": 50, "speaker": "交通局謝局長銘鴻", "gaz_page": 6, "source_url": "A"}]
    assert locate("請問電梯何時完工", seg, spans)[1]["gaz_page"] == 5
    assert locate("交通局謝局長銘鴻：年底…完工", seg, spans)[1]["gaz_page"] == 6
    assert locate("明年完工", seg, spans) == (False, None)
    assert official_names(["交通局謝局長銘鴻", "蔣市長萬安"]) == {"謝銘鴻", "蔣萬安"}
    assert official_names(["李秘書長兼秘書處處長泰興"]) == {"李泰興"}  # 不再產生「處處長」
    seg2 = "〔公報第566頁〕李議員明賢：除了違反<食品安全衛生管理法>第 28 條，\n〔公報第567頁〕還有嗎？"
    spans2 = [{"start": 0, "end": 40, "gaz_page": 566, "source_url": "A"},
              {"start": 41, "end": 60, "gaz_page": 567, "source_url": "A"}]
    assert locate("〔公報第566頁〕李議員明賢：除了違反第28條，", seg2, spans2)[1]["gaz_page"] == 566
    assert locate("第 28 條，還有嗎", seg2, spans2)[0]  # 跨頁碼標記
    # 短答在兩份速記錄都出現：有頁碼標記時取標記那頁，沒有標記時候選不只一個 → 無法定位
    seg3 = "〔公報第698頁〕湯局長志民：對。\n〔公報第1924頁〕湯局長志民：對。\n"
    spans3 = [{"start": 0, "end": 16, "gaz_page": 698, "source_url": "A"},
              {"start": 17, "end": 34, "gaz_page": 1924, "source_url": "B"}]
    assert locate("〔公報第1924頁〕湯局長志民：對。", seg3, spans3)[1]["source_url"] == "B"
    assert locate("湯局長志民：對。", seg3, spans3) == (False, None)
    assert locate("〔公報第5頁〕湯局長志民：對。", seg3, spans3) == (False, None)
    assert is_short("〔公報第576頁〕張議員斯綱：好，謝謝市長。", {"張議員斯綱"})
    assert not is_short("〔公報第576頁〕張議員斯綱：請問電梯何時完工？", {"張議員斯綱"})
    cite = lambda text, ok: {"n": 1, "cited_text": text, "located": ok}  # noqa: E731
    s, f = filter_citations({"issues": [
        {"topic": "甲", "response": None, "citations": [cite("", False), cite("原文", True)]},
        {"topic": "乙", "response": None, "citations": [cite("", False), cite("對不到", False)]},
    ]})
    assert [i["topic"] for i in s["issues"]] == ["甲"] and len(s["issues"][0]["citations"]) == 1, s
    assert f["empty_citations"] == 2 and f["removed_issues"] == ["乙"] and len(f["unlocated_citations"]) == 1, f
    c = lambda fields, url, short=False: {"n": 1, "cited_text": "x", "located": True, "short": short,  # noqa: E731
                                          "fields": fields, "source_url": url + "#page=1"}
    s, f = filter_citations({"issues": [
        {"topic": "跨場次回應", "response": "局長說明", "citations": [c(["councilor"], "A"), c(["response"], "B")]},
        {"topic": "同場次回應", "response": "局長說明", "citations": [c(["councilor"], "A"), c(["response"], "A"),
                                                                c(["councilor"], "C")]},
        {"topic": "只剩短答", "response": None, "citations": [c(["councilor"], "A", short=True)]},
    ]})
    a, b = s["issues"]
    assert a["response"] is None and a["response_removed"] and a["citations"] == [c(["councilor"], "A")], a
    assert b["response"] == "局長說明" and not b["response_removed"] and len(b["citations"]) == 3, b
    assert len(f["removed_responses"]) == 1 and f["multi_session_claims"] == ["同場次回應"], f
    assert f["removed_issues"] == ["只剩短答"] and len(f["short_citations"]) == 1, f
    seg4 = "〔公報第1頁〕李議員明賢：護病比要改善。\n〔公報第9頁〕柳議員采葳：請警察局提出警政數位資料建立知識庫計畫案。\n"
    spans4 = [{"start": 0, "end": 19, "gaz_page": 1, "source_url": "A", "heading": "甲組"},
              {"start": 20, "end": 53, "gaz_page": 9, "source_url": "B", "heading": "乙組"}]
    assert response_elsewhere("局長說明會改善護病比。警察局局長表示會提出警政數位資料知識庫計畫案", {"A"}, seg4, spans4) \
        == [("警察局局長表示會提出警政數位資料知識庫計畫案", "乙組", 9)]
    assert response_elsewhere("局長說明會改善護病比", {"A"}, seg4, spans4) == []
    print("demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        run(sys.argv[1], sys.argv[2], sys.argv[3:])
