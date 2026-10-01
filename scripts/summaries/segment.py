"""從公報速記錄切出每位議員自己的質詢段落（質詢摘要 S1）。

用法：
  python3 scripts/summaries/segment.py 05 姓名 [姓名 ...]   切出指定議員
  python3 scripts/summaries/segment.py audit 05             整個會期逐份檢查切分（寫 audit.json）
  python3 scripts/summaries/segment.py demo                 自我檢查
輸入：fetch_transcripts.py 下載的 data/cache/transcripts/14-05/（index.json＋PDF）與 data/civic.db 的影片 fact。
輸出（每位議員一份，放在同一個 cache 目錄）：
  seg_<person_id>.txt   給 NotebookLM 的來源文字，每段標明發言人與公報頁碼
  seg_<person_id>.json  索引：各組出處（viewer 網址、頁碼）、日期、組別、影片深連結、每段發言在文字檔中的位置

切分規則（寧可少收，不收錯）：
  1. 只看 PDF 內「XX質詢第 N 組」標題到下一個組標題之間的內文（PDF 首尾頁常夾著相鄰組的內容）。
  2. 發言標籤是行首、以全形冒號結尾、不含標點、以議員或職稱結尾的一行（「李議員明賢：」「社會局姚局長淑文：」）。
     pdftotext 偶爾把標籤併到上一行行尾，行尾是本份其他地方出現過的標籤就拆開。
  3. 組員：公報表頭的「質詢議員」。表頭常有錯（姓名黏在一起、錯字、整段貼成別組名單），所以先用全屆議員名單校正，
     表頭組員全部沒有發言時改用影片分段（Segment_Read）裡組員發言最多的那一組。
  4. 逐段決定歸屬：組員議員發言 → 歸該議員；非組員的「X議員Y」（多為錯字或插話）→ 暫停歸屬；
     主席發言不收，也不改歸屬（主席插話後官員接著答，仍算原議員的質詢）；官員發言 → 歸目前的議員（暫停時不收）。
     同組議員交錯發言時，每位議員只拿到自己的發言與緊接其後的官員答復。
"""
import csv
import json
import pathlib
import re
import sqlite3
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "transcripts"
DB = ROOT / "data" / "civic.db"

# 第 1 次定期大會有一份公報表頭誤植為「市政總質詢質詢第 7 組」
GROUP_HEAD = re.compile(r"^\s*(市政總質詢(?:質詢)?|(\S+)部門質詢)第\s*(\d+)\s*組\s*$")
LABEL = re.compile(r"^(\S[^：:]{0,39}?)(?:答覆)?[：:]+\s*$")  # 偶有半形冒號「徐議員立信:」
ANNOTATION = re.compile(r"\s+註解\s*\[.*$")  # Word 註解殘留：「王議員閔生：   註解 [呂懿恬1]: ：」
DATE_MARK = re.compile(r"─+\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日\s*─+")
HEAD_DATE = re.compile(r"質詢日期：中華民國\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日")
ROSTER = re.compile(r"\S詢議員：(.*?)計\s*(\d+)\s*位", re.S)  # 公報偶有錯字「貿詢議員」
RUNNING_HEAD = re.compile(r"^\s*臺北市議會公報\s+第\s*\d+\s*卷\s+第\s*\d+\s*期\s*$")
PAGE_NO = re.compile(r"^\s*(\d+)\s*$")
PUNCT = re.compile(r"[，。、；？！「」『』…,.?!]")
ROLE_END = re.compile(
    r"(長|委員|委|經理|主任|秘書|參事|顧問|官|工程司|工程師|專員|技正|技士|編審|分析師|講師|選手|偵查佐|發言人|"
    r"督察|律師|教授|董事|先生|女士)[一-龥]{0,3}$"
)


def pages_of(pdf):
    """PDF → [(pdf 頁序, 公報頁碼, [行])]；去掉頁首「臺北市議會公報 第 N 卷」與頁尾頁碼。"""
    text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    out = []
    for i, page in enumerate(text.split("\f")):
        lines = [ANNOTATION.sub("", l) for l in page.splitlines() if l.strip()]
        if not lines:
            continue
        gaz_page = int(lines.pop().strip()) if PAGE_NO.match(lines[-1]) else None
        out.append((i + 1, gaz_page, [l for l in lines if not RUNNING_HEAD.match(l)]))
    return out


def label_of(line):
    """發言標籤行 → 發言人；不是標籤回 None。"""
    m = LABEL.match(line)
    if not m or PUNCT.search(m.group(1)):
        return None
    s = m.group(1).strip()
    if s.startswith("主席") or ("議員" in s and len(s) <= 8) or ROLE_END.search(s):
        return s
    return None


def split_merged(line, known):
    """pdftotext 偶爾把發言標籤併到上一行行尾（「…是否屬於重大陳處長英豪：」）：行尾是本份已知標籤就拆開。"""
    body = line.rstrip()
    if not body.endswith(("：", ":")):
        return None
    body = body.rstrip("：:")
    for label in sorted(known, key=len, reverse=True):
        if body.endswith(label) and len(body) > len(label):
            return body[: -len(label)], label
    return None


def name_forms(name):
    return {name + "議員"} | {name[:k] + "議員" + name[k:] for k in (1, 2) if len(name) > k}


def label_owner(label, roster):
    """發言標籤 → 組員姓名／'CHAIR'／'OTHER_COUNCILLOR'／None（官員）。"""
    if label.startswith("主席"):
        return "CHAIR"
    for name in roster:
        if label in name_forms(name):
            return name
    if "議員" in label:
        return "OTHER_COUNCILLOR"
    return None


def roc_date(m):
    return f"{int(m.group(1)) + 1911}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def normalize_roster(raw, known):
    """表頭「質詢議員」原文 → 姓名串列。處理姓名黏在一起（「張斯綱李明賢…」）、頓號分隔、一字之差的錯字（鐘小平）。"""
    out = []
    for tok in re.split(r"[\s、，]+", raw.replace("議員", "")):
        if not tok:
            continue
        if tok in known:
            out.append(tok)
            continue
        rest, parts = tok, []
        while rest:
            hit = next((n for n in sorted(known, key=len, reverse=True) if rest.startswith(n)), None)
            if not hit:
                break
            parts.append(hit)
            rest = rest[len(hit):]
        if parts and not rest:
            out += parts
            continue
        near = [n for n in known if len(n) == len(tok) and sum(a != b for a, b in zip(n, tok)) == 1]
        out.append(near[0] if len(near) == 1 else tok)
    return out


def parse_doc(pdf, group):
    """一份速記錄 PDF → {heading, dept, roster_raw, head_count, turns:[{speaker, date, pdf_page, gaz_page, text}]}。"""
    pages = pages_of(pdf)
    known = {label_of(l) for _, _, ls in pages for l in ls} - {None}
    turns, roster_raw, head_count, heading, dept, in_group, date, cur = [], None, None, None, None, False, None, None
    head_lines = []
    for pdf_page, gaz_page, lines in pages:
        for line in lines:
            h = GROUP_HEAD.match(line)
            if h:
                if in_group and roster_raw is not None:  # 下一組開始
                    return dict(heading=heading, dept=dept, roster_raw=roster_raw, head_count=head_count, turns=turns)
                in_group = int(h.group(3)) == group
                heading, dept, cur = re.sub(r"\s+", "", line), h.group(2), None
                continue
            if not in_group:
                continue
            if roster_raw is None:
                head_lines.append(line)
                joined = "\n".join(head_lines)
                r = ROSTER.search(joined)
                if r:
                    roster_raw, head_count = r.group(1), int(r.group(2))
                    hd = HEAD_DATE.search(joined)
                    date = roc_date(hd) if hd else None
                continue
            d = DATE_MARK.search(line)
            if d:
                date, cur = roc_date(d), None
                continue
            speaker = label_of(line)
            if speaker is None:
                merged = split_merged(line, known)
                if merged:
                    if cur is not None:
                        cur["text"] += merged[0].strip()
                    speaker = merged[1]
            if speaker:
                cur = dict(speaker=speaker, date=date, pdf_page=pdf_page, gaz_page=gaz_page, text="")
                turns.append(cur)
            elif cur is not None:
                cur["text"] += line.strip()
    if roster_raw is None:
        raise ValueError(f"{pdf.name} 找不到第 {group} 組的標題或表頭")
    return dict(heading=heading, dept=dept, roster_raw=roster_raw, head_count=head_count, turns=turns)


def doc_type_of(parsed):
    return "市政總質詢" if parsed["heading"].startswith("市政總質詢") else "部門質詢"


def dept_of(parsed):
    return {"財建": "財政建設"}.get(parsed["dept"], parsed["dept"])


def resolve_group(parsed, vgroups, known):
    """→ (組員, 組員來源, 對應的影片分段串列)。

    影片分段與公報的組別編號不一定一致（第 5 次定期大會某部門第 8、9 組互換），總質詢跨日時影片會切成兩段，
    所以影片用「組員重疊最多＋日期」對應，不用組別編號。"""
    header = normalize_roster(parsed["roster_raw"], known)
    dates = {t["date"] for t in parsed["turns"] if t["date"]}
    speakers = {n for n in known if any(t["speaker"] in name_forms(n) for t in parsed["turns"])}
    header_spoke = bool(set(header) & speakers)
    basis = set(header) if header_spoke else speakers
    same_kind = [g for g in vgroups if g["doc_type"] == doc_type_of(parsed) and g["dept"] == dept_of(parsed)]
    scored = [(len(basis & set(g["councillors"])), g) for g in same_kind]
    best = max((s for s, _ in scored), default=0)
    candidates = [g for s, g in scored if s == best and best > 0]
    # 公報日期偶有錯字（財政建設部門第 8 組寫成 113 年）：同日對不到時退回只比組員
    matched = [g for g in candidates if not dates or g["date"] in dates] or candidates
    if header_spoke:
        return header, "公報表頭", matched
    if matched:
        return matched[0]["councillors"], "影片分段（公報表頭組員皆無發言，疑似表頭貼錯）", matched
    return header, "公報表頭（組員皆無發言，也對不到影片分段）", matched


def attribute(turns, roster):
    """依切分規則 4，替每段發言標上 owner（標籤身分）與 attributed（歸屬議員；不收為 None）。回傳新串列，不改輸入。"""
    out, owner = [], None
    for t in turns:
        o = label_owner(t["speaker"], roster)
        if o == "CHAIR":
            out.append({**t, "owner": o, "attributed": None})
            continue
        if o == "OTHER_COUNCILLOR":
            owner = None
        elif o is not None:
            owner = o
        out.append({**t, "owner": o, "attributed": owner})
    return out


def load_identity():
    with open(ROOT / "data" / "identity.csv", newline="") as f:
        return {r["source_key"]: r["person_id"] for r in csv.DictReader(f) if r["source"] == "tcc14"}


def video_groups(session_label):
    """DB 的影片 fact（kind='interpellation'，ivideo:）→ [{video_id, date, doc_type, dept, group, councillors, links}]。"""
    conn = sqlite3.connect(f"file:{DB}?immutable=1", uri=True)
    rows = conn.execute(
        "SELECT person_id, date, source_url, data FROM fact WHERE kind = 'interpellation' "
        "AND fact_key LIKE 'ivideo:%' AND json_extract(data, '$.session') = ? ORDER BY date", (session_label,),
    ).fetchall()
    out = {}
    for person_id, date, url, data in rows:
        d = json.loads(data)
        g = out.setdefault((d["video_id"], d["group"]), {
            "video_id": d["video_id"], "date": date, "doc_type": d["doc_type"], "dept": d["dept"], "group": d["group"],
            "councillors": d["councillors"], "seekable": d["seekable"], "start_sec": d["start_sec"], "url": url, "persons": []})
        g["persons"].append(person_id)
    return list(out.values())


def known_names(identity, vgroups):
    return set(identity) | {n for g in vgroups for n in g["councillors"]}


def build(session, name, docs, identity, vgroups):
    person_id = identity[name]
    known = known_names(identity, vgroups)
    lines = [
        f"臺北市議會第14屆第{int(session)}次定期大會　{name}議員　口頭質詢速記錄節錄",
        "（節錄自臺北市議會公報速記錄。只收該議員本人的發言，以及緊接其後的市府官員答復；主席發言與同組其他議員的發言不收。"
        "每段開頭的〔公報第N頁〕是該段在公報上的起始頁碼。）",
        "",
    ]
    groups, spans = [], []
    for doc, parsed in docs:
        roster, roster_source, matched = resolve_group(parsed, vgroups, known)
        if name not in roster:
            continue
        turns = [t for t in attribute(parsed["turns"], roster) if t["attributed"] == name]
        own = [t for t in turns if t["owner"] == name]
        dates = sorted({t["date"] for t in parsed["turns"] if t["date"]})
        groups.append({
            "heading": parsed["heading"], "doc_type": doc_type_of(parsed), "dept": dept_of(parsed), "group": doc["group"],
            "dates": dates, "roster": roster, "roster_source": roster_source, "source_url": doc["viewer_url"],
            "pdf_pages": sorted({t["pdf_page"] for t in turns}),
            "gaz_pages": sorted({t["gaz_page"] for t in turns if t["gaz_page"]}),
            "own_turns": len(own), "official_turns": len(turns) - len(own), "own_chars": sum(len(t["text"]) for t in own),
            "videos": [{"date": g["date"], "url": g["url"], "video_group": g["group"], "group_size": len(g["councillors"]),
                        "seekable": g["seekable"], "start_sec": g["start_sec"]} for g in matched],
        })
        if not turns:
            continue
        lines += [f"【{parsed['heading']}　{'、'.join(dates)}】", f"出處：{doc['viewer_url']}", ""]
        for t in turns:
            start = sum(len(l) + 1 for l in lines)
            lines.append(f"〔公報第{t['gaz_page']}頁〕{t['speaker']}：{t['text']}")
            spans.append({"start": start, "end": start + len(lines[-1]), "speaker": t["speaker"], "date": t["date"],
                          "heading": parsed["heading"], "source_url": doc["viewer_url"],
                          "pdf_page": t["pdf_page"], "gaz_page": t["gaz_page"]})
        lines.append("")
    return person_id, "\n".join(lines), {"person_id": person_id, "name": name, "session": f"第14屆第{int(session)}次定期大會",
                                         "groups": groups, "spans": spans}


def load_docs(session):
    out_dir = CACHE / f"14-{session}"
    return [(d, parse_doc(out_dir / f"{d['viewer_id']}.pdf", d["group"]))
            for d in json.loads((out_dir / "index.json").read_text())]


def session_label(session):
    return f"第14屆第{session}次定期大會"  # DB 的 session 欄位是兩位數：「第14屆第05次定期大會」


def run(session, names):
    out_dir = CACHE / f"14-{session}"
    identity, docs, vgroups = load_identity(), load_docs(session), video_groups(session_label(session))
    for name in names:
        person_id, text, index = build(session, name, docs, identity, vgroups)
        (out_dir / f"seg_{person_id}.txt").write_text(text)
        (out_dir / f"seg_{person_id}.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
        g = index["groups"]
        print(f"{name} {person_id}：{len(g)} 組，本人發言 {sum(x['own_turns'] for x in g)} 段／"
              f"{sum(x['own_chars'] for x in g)} 字，官員答復 {sum(x['official_turns'] for x in g)} 段，文字檔 {len(text)} 字")


def audit(session):
    """整個會期逐份檢查切分：表頭 vs 影片組員、每位組員發言段數、交錯次數、非組員議員標籤、疑似漏抓的標籤。"""
    out_dir = CACHE / f"14-{session}"
    identity, vgroups = load_identity(), video_groups(session_label(session))
    known = known_names(identity, vgroups)
    rows = []
    for d, p in load_docs(session):
        roster, roster_source, matched = resolve_group(p, vgroups, known)
        att = attribute(p["turns"], roster)
        counts = {n: sum(t["owner"] == n for t in att) for n in roster}
        seq = [t["owner"] for t in att if t["owner"] in counts]
        changes = sum(a != b for a, b in zip(seq, seq[1:]))
        pdf = out_dir / f"{d['viewer_id']}.pdf"
        rows.append({
            "title": d["title"], "dates": sorted({t["date"] for t in p["turns"] if t["date"]}),
            "roster": roster, "roster_source": roster_source, "header_raw": re.sub(r"\s+", " ", p["roster_raw"]).strip(),
            "head_count": p["head_count"], "video_groups": [(g["date"], g["group"], g["councillors"]) for g in matched],
            "turns": counts,
            "interleave": changes - max(len(set(seq)) - 1, 0),  # 0＝依序輪流；>0＝同組議員交錯發言的次數
            "others": sorted({t["speaker"] for t in att if t["owner"] == "OTHER_COUNCILLOR"}),
            "unlabeled": sorted({l.strip() for _, _, ls in pages_of(pdf) for l in ls
                                 if l.rstrip().endswith(("：", ":")) and not l.startswith(" ") and not label_of(l)
                                 and not split_merged(l, {t["speaker"] for t in p["turns"]})}),
        })
    (out_dir / "audit.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    return rows


def demo():
    roster = ["張斯綱", "李傅中武"]
    assert label_owner("張議員斯綱", roster) == "張斯綱"
    assert label_owner("李傅議員中武", roster) == "李傅中武"
    assert label_owner("吳志剛議員", ["吳志剛"]) == "吳志剛"
    assert label_owner("主席（戴議長錫欽）", roster) == "CHAIR"
    assert label_owner("主席(陳議員賢蔚)", roster) == "CHAIR"
    assert label_owner("徐議員弘庭", roster) == "OTHER_COUNCILLOR"
    assert label_owner("社會局姚局長淑文", roster) is None
    for ok in ["社會局姚局長淑文：", "主席（戴議長錫欽）：", "李議員明賢：", "衛生局黃建華局長：", "許副總工程司敏能：",
               "原住民族事務委員會李副主委菊妹：", "財政局胡局長曉嵐：：", "2025 雙北世界壯年運動會執行辦公室張主任勝傑：",
               "都市更新處詹處長育齊答覆：", "徐議員立信:"]:
        assert label_of(ok), ok
    for bad in ["理由如下：", "局長，你說：", "具體 5 個建議如下：", "我具體 2 個建議：", "要求是：", "可能有兩個原因："]:
        assert not label_of(bad), bad
    assert label_of("都市更新處詹處長育齊答覆：") == "都市更新處詹處長育齊"
    assert split_merged("是否屬於重大陳處長英豪：", {"陳處長英豪"}) == ("是否屬於重大", "陳處長英豪")
    assert split_merged("市長與所有局處首長動動腦：", {"陳處長英豪"}) is None
    known = {"張斯綱", "李明賢", "鍾小平", "陳重文", "耿葳"}
    assert normalize_roster("張斯綱李明賢", known) == ["張斯綱", "李明賢"]
    assert normalize_roster("陳重文 鐘小平", known) == ["陳重文", "鍾小平"]
    assert normalize_roster("陳重文、耿葳", known) == ["陳重文", "耿葳"]
    speakers = ["張議員斯綱", "蔣市長萬安", "主席", "蔣市長萬安", "李傅議員中武", "姚局長淑文", "張議員斯綱",
                "徐議員弘庭", "姚局長淑文"]
    got = [t["attributed"] for t in attribute([{"speaker": s} for s in speakers], roster)]
    assert got == ["張斯綱", "張斯綱", None, "張斯綱", "李傅中武", "李傅中武", "張斯綱", None, None], got
    vg = [{"doc_type": "部門質詢", "dept": "交通", "group": 8, "date": "2025-05-22", "councillors": ["侯漢廷"]},
          {"doc_type": "部門質詢", "dept": "交通", "group": 9, "date": "2025-05-22", "councillors": ["吳世正", "郭昭巖"]}]
    parsed = {"heading": "交通部門質詢第8組", "dept": "交通", "roster_raw": "張斯綱",
              "turns": [{"speaker": "吳議員世正", "date": "2025-05-22"}]}
    roster2, src, matched = resolve_group(parsed, vg, {"張斯綱", "吳世正", "郭昭巖", "侯漢廷"})
    assert roster2 == ["吳世正", "郭昭巖"] and matched[0]["group"] == 9 and src.startswith("影片分段"), (roster2, src)
    print("demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    elif sys.argv[1] == "audit":
        audit(sys.argv[2])
    else:
        run(sys.argv[1], sys.argv[2:])
