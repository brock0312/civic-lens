"""用 NotebookLM 產生質詢摘要（質詢摘要 S1）。

用法：python3 scripts/summaries/summarize.py 05 姓名 [姓名 ...]
前置：segment.py 已產生 seg_<person_id>.txt；`notebooklm auth check --test` 通過。
做法：
  - 一個會期一個 notebook（標題見 NOTEBOOK_TITLE），每位議員的切分文字檔是一個獨立來源。
    ponytail: 一個 notebook 最多 50 個來源（Standard 方案），全屆 53 人時同一會期要拆成兩個 notebook。
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

PROMPT = """請只根據這份來源（{name}議員在臺北市議會第14屆第{n}次定期大會的口頭質詢速記錄節錄）整理質詢摘要。

輸出要求：
1. 列出 3 到 6 個議題，依該議題在來源中的篇幅由多到少排列。
2. 每個議題嚴格依照下列格式，不要輸出標題、前言、結語或其他內容：
### 議題：（中性的名詞短語，例如「捷運站無障礙設施改善」）
- 議員：（{name}議員提出的問題或訴求，用轉述，一到三句）
- 市府回應：（回應者職稱加上回應要點，例如「交通局局長說明……」；來源中沒有市府回應就只寫「無」）
3. 只根據來源內容，不推測動機，不加評價。動詞只用中性的詞，例如詢問、要求、建議、指出、說明、表示。
4. 不要使用痛批、砲轟、怒嗆、狠批、打臉、嗆、轟、酸等媒體式的評價用語。
5. 來源沒有出現的數字不要寫。每一句都要附上來源引文。
6. 人名只能寫{name}議員本人；市府官員一律只寫職稱（例如「交通局局長」），不寫姓名。"""


def cli(*args, retries=1):
    """呼叫 notebooklm CLI（--json），回傳解析後的 dict。速率限制時等待後重試一次。"""
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


def run(session, names):
    out_dir = CACHE / f"14-{session}"
    state_path = out_dir / "notebooklm.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"sources": {}}
    save = lambda: state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1))  # noqa: E731
    n = int(session)
    if "notebook_id" not in state:
        nb = cli("create", NOTEBOOK_TITLE.format(n=n))["notebook"]
        state.update(notebook_id=nb["id"], notebook_title=nb["title"], created_at=now())
        save()
        print("建立 notebook", nb["id"], nb["title"], flush=True)
    nb_id = state["notebook_id"]
    identity = load_identity()
    for name in names:
        person_id = identity[name]
        seg = out_dir / f"seg_{person_id}.txt"
        if person_id not in state["sources"]:
            t0 = time.monotonic()
            # 以檔案上傳，來源標題＝檔名（CLI 的 --type text 會把路徑字串本身當內容上傳，不能用）
            upload = out_dir / "upload" / f"{name}_第14屆第{n}次定期大會_質詢速記錄節錄.txt"
            upload.parent.mkdir(exist_ok=True)
            upload.write_text(seg.read_text())
            title = upload.name
            src = cli("source", "add", str(upload), "-n", nb_id)["source"]
            wait = subprocess.run([NOTEBOOKLM, "source", "wait", src["id"], "-n", nb_id, "--timeout", "600"],
                                  capture_output=True, text=True)
            if wait.returncode != 0:
                raise RuntimeError(f"{name} 來源處理失敗：{wait.stdout[-300:]} {wait.stderr[-300:]}")
            state["sources"][person_id] = {"source_id": src["id"], "title": title, "chars": len(seg.read_text()),
                                           "upload_sec": round(time.monotonic() - t0, 1)}
            save()
            print(f"{name} 來源 {src['id']}（{state['sources'][person_id]['upload_sec']} 秒）", flush=True)
        answer_path = out_dir / f"nlm_{person_id}.json"
        if answer_path.exists():
            continue
        source_id = state["sources"][person_id]["source_id"]
        t0 = time.monotonic()
        res = cli("ask", PROMPT.format(name=name, n=n), "-n", nb_id, "-s", source_id, "-c", str(uuid.uuid4()))
        answer_path.write_text(json.dumps({
            "person_id": person_id, "name": name, "notebook_id": nb_id, "source_id": source_id,
            "prompt": PROMPT.format(name=name, n=n), "asked_at": now(), "ask_sec": round(time.monotonic() - t0, 1),
            "answer": res["answer"], "references": res.get("references", []),
        }, ensure_ascii=False, indent=1))
        foreign = {r["source_id"] for r in res.get("references", [])} - {source_id}
        print(f"{name} 回答 {len(res['answer'])} 字、引文 {len(res.get('references', []))} 條、"
              f"{round(time.monotonic() - t0, 1)} 秒" + (f"；⚠ 引到其他來源 {foreign}" if foreign else ""), flush=True)
        time.sleep(ASK_INTERVAL)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2:])
