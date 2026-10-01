"""用 NotebookLM 產生質詢摘要（質詢摘要 S1）。

用法：python3 scripts/summaries/summarize.py 05 姓名 [姓名 ...]
前置：segment.py 已產生 seg_<person_id>.txt；`notebooklm auth check --test` 通過。
做法：
  - 一個會期一個 notebook（標題見 NOTEBOOK_TITLE），每位議員的切分文字檔是一個獨立來源。
    一個 notebook 最多 MAX_SOURCES 個來源（Standard 方案 50），滿了就另建「…（2）」。只用本程式建立、記在狀態檔裡的 notebook。
  - 每次提問都用 `-s <source_id>` 只讀該議員的來源，並用新的 conversation id（-c 隨機 UUID），
    避免 CLI 預設接續上一輪對話而混入別人的內容。
  - 狀態（notebook／來源 id）與原始回答存在 cache：notebooklm.json、nlm_<person_id>.json，可中斷後續跑。
輸出：nlm_<person_id>.json（原始回答＋引文），供 check_report.py 解析與檢查。
"""
import json
import pathlib
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "transcripts"
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from segment import load_identity  # noqa: E402

NOTEBOOKLM = "notebooklm"
NOTEBOOK_TITLE = "civic-lens 質詢摘要 第14屆第{n}次定期大會"
ASK_INTERVAL = 20  # 秒；兩次提問之間
RATE_LIMIT_WAIT = 600  # 秒；技能文件：遇到 "No result found for RPC ID" 等速率限制等 5–10 分鐘再試
RATE_LIMIT_RETRIES = 3
MAX_SOURCES = 50  # 每個 notebook 的來源上限（Standard 方案）

PROMPT = """請只根據這份來源（{name}議員在臺北市議會第14屆第{n}次定期大會的口頭質詢速記錄節錄）整理質詢摘要。

輸出要求：
1. 列出 3 到 6 個議題，依該議題在來源中的篇幅由多到少排列。
2. 每個議題嚴格依照下列格式，不要輸出標題、前言、結語或其他內容：
### 議題：（中性的名詞短語，例如「捷運站無障礙設施改善」）
- 議員：（{name}議員提出的問題或訴求，用轉述，一到三句）
- 市府回應：（回應者職稱加上回應要點，例如「交通局局長說明……」；來源中沒有市府回應就只寫「無」）
3. 只根據來源內容，不推測動機，不加評價。動詞只用中性的詞，例如詢問、要求、建議、指出、說明、表示。
   不得自行加上評價性的形容（例如「缺乏誠意」「消極」）；要描述議員的評價時，必須用引號引用議員原話。
4. 不要使用痛批、砲轟、怒嗆、狠批、打臉、嗆、轟、酸等媒體式的評價用語。
5. 市府回應只能寫和該議題同一段質詢中（同一場次、同一組）官員對該議題的答復；官員在其他場次或其他議題的說明、承諾不要放進來。
6. 來源沒有出現的數字不要寫。每一句（包括議員與市府回應的每一句）都要附上來源引文。
7. 人名只能寫{name}議員本人；市府官員一律只寫職稱（例如「交通局局長」），不寫姓名。"""


def cli(*args, retries=RATE_LIMIT_RETRIES):
    """呼叫 notebooklm CLI（--json），回傳解析後的 dict。速率限制時等待後重試，最多 retries 次。"""
    for attempt in range(retries + 1):
        p = subprocess.run([NOTEBOOKLM, *args, "--json"], capture_output=True, text=True)
        out = p.stdout.strip()
        try:
            data = json.loads(out) if out else {}
        except json.JSONDecodeError:
            data = {"error": True, "message": out[:500]}
        if p.returncode == 0 and not data.get("error"):
            return data
        msg = f"{data.get('message', '')} {p.stderr.strip()[:500]}"
        if "Authentication" in msg or "login" in msg:
            raise SystemExit(f"NotebookLM 登入失效，請先執行 `notebooklm login`：{msg}")
        if attempt < retries and ("RPC" in msg or "rate" in msg.lower() or "429" in msg):
            print(f"速率限制，等待 {RATE_LIMIT_WAIT} 秒後重試：{msg}", flush=True)
            time.sleep(RATE_LIMIT_WAIT)
            continue
        raise RuntimeError(f"notebooklm {' '.join(args[:2])} 失敗：{msg}")


def load_state(session):
    """notebooklm.json → state；舊格式（單一 notebook_id）轉成 notebooks 清單，每個來源記上所屬 notebook。"""
    path = CACHE / f"14-{session}" / "notebooklm.json"
    state = json.loads(path.read_text()) if path.exists() else {}
    notebooks = state.get("notebooks") or ([{"id": state["notebook_id"], "title": state["notebook_title"],
                                             "created_at": state.get("created_at")}] if "notebook_id" in state else [])
    sources = {pid: {"notebook_id": notebooks[0]["id"], "ready": True, **src} if notebooks else src
               for pid, src in state.get("sources", {}).items()}
    return {"notebooks": notebooks, "sources": sources}


def save_state(session, state):
    (CACHE / f"14-{session}" / "notebooklm.json").write_text(json.dumps(state, ensure_ascii=False, indent=1))


def pick_notebook(session, state):
    """最後一個 notebook 還有空位就用它，否則新建一個。回傳 (notebook id, 新 state)。"""
    nbs = state["notebooks"]
    if nbs and sum(s["notebook_id"] == nbs[-1]["id"] for s in state["sources"].values()) < MAX_SOURCES:
        return nbs[-1]["id"], state
    title = NOTEBOOK_TITLE.format(n=int(session)) + (f"（{len(nbs) + 1}）" if nbs else "")
    nb = cli("create", title)["notebook"]
    print("建立 notebook", nb["id"], nb["title"], flush=True)
    state = {**state, "notebooks": [*nbs, {"id": nb["id"], "title": nb["title"], "created_at": now()}]}
    save_state(session, state)
    return nb["id"], state


def summarize_one(session, name, person_id, state):
    """上傳來源（若尚未上傳）並提問（若尚無回答）。回傳新 state；失敗時 raise。"""
    out_dir = CACHE / f"14-{session}"
    n = int(session)
    seg = out_dir / f"seg_{person_id}.txt"
    src = state["sources"].get(person_id)
    if src is None:
        nb_id, state = pick_notebook(session, state)
        # 以檔案上傳，來源標題＝檔名（CLI 的 --type text 會把路徑字串本身當內容上傳，不能用）
        upload = out_dir / "upload" / f"{name}_第14屆第{n}次定期大會_質詢速記錄節錄.txt"
        upload.parent.mkdir(exist_ok=True)
        upload.write_text(seg.read_text())
        added = cli("source", "add", str(upload), "-n", nb_id)["source"]
        # 先記下來源（未就緒），中斷後續跑時不會重複上傳、也不會讓來源數算錯
        src = {"source_id": added["id"], "notebook_id": nb_id, "title": upload.name, "chars": len(seg.read_text()),
               "ready": False}
        state = {**state, "sources": {**state["sources"], person_id: src}}
        save_state(session, state)
    if not src.get("ready"):
        t0 = time.monotonic()
        wait = subprocess.run([NOTEBOOKLM, "source", "wait", src["source_id"], "-n", src["notebook_id"],
                               "--timeout", "600"], capture_output=True, text=True)
        if wait.returncode != 0:
            raise RuntimeError(f"{name} 來源處理失敗：{wait.stdout[-300:]} {wait.stderr[-300:]}")
        src = {**src, "ready": True, "upload_sec": round(time.monotonic() - t0, 1)}
        state = {**state, "sources": {**state["sources"], person_id: src}}
        save_state(session, state)
        print(f"{name} 來源 {src['source_id']}（{src['upload_sec']} 秒）", flush=True)
    answer_path = out_dir / f"nlm_{person_id}.json"
    if answer_path.exists():
        return state
    nb_id, source_id = src["notebook_id"], src["source_id"]
    t0 = time.monotonic()
    res = cli("ask", PROMPT.format(name=name, n=n), "-n", nb_id, "-s", source_id, "-c", str(uuid.uuid4()))
    # 空白回答（實測約 3 秒就回）＝已達每日提問上限：不寫快取、整批停下，隔天用同一指令續跑
    # ponytail: 以「回答為空」判斷額度用完；若 NotebookLM 改回明確錯誤訊息，改在 cli() 裡判斷
    if not res["answer"].strip():
        raise SystemExit(f"{name}：NotebookLM 回傳空白回答，可能已達每日提問上限；已停止，明天用同一指令續跑")
    answer_path.write_text(json.dumps({
        "person_id": person_id, "name": name, "notebook_id": nb_id, "source_id": source_id,
        "prompt": PROMPT.format(name=name, n=n), "asked_at": now(), "ask_sec": round(time.monotonic() - t0, 1),
        "answer": res["answer"], "references": res.get("references", []),
    }, ensure_ascii=False, indent=1))
    foreign = {r["source_id"] for r in res.get("references", [])} - {source_id}
    print(f"{name} 回答 {len(res['answer'])} 字、引文 {len(res.get('references', []))} 條、"
          f"{round(time.monotonic() - t0, 1)} 秒" + (f"；⚠ 引到其他來源 {foreign}" if foreign else ""), flush=True)
    time.sleep(ASK_INTERVAL)
    return state


def run(session, names):
    identity = load_identity()
    state = load_state(session)
    for name in names:
        state = summarize_one(session, name, identity[name], state)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def demo():
    global cli, save_state
    real = cli, save_state
    created = []
    cli = lambda *a: created.append(a[1]) or {"notebook": {"id": f"nb{len(created) + 1}", "title": a[1]}}  # noqa: E731
    save_state = lambda *a: None  # noqa: E731
    try:
        full = {"notebooks": [{"id": "nb1", "title": "t"}],
                "sources": {f"p{i}": {"notebook_id": "nb1"} for i in range(MAX_SOURCES)}}
        nb, st = pick_notebook("05", full)
        assert nb == "nb2" and created == [NOTEBOOK_TITLE.format(n=5) + "（2）"] and len(st["notebooks"]) == 2, created
        assert pick_notebook("05", {**full, "sources": {"p0": {"notebook_id": "nb1"}}})[0] == "nb1"
    finally:
        cli, save_state = real
    print("demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        run(sys.argv[1], sys.argv[2:])
