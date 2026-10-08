# 交接文件（新 session 從這裡開始）

> 最後更新：2026-10-08。新的工作階段請先讀完本文件，再讀 [README](../README.md)、[PLAN](PLAN.md) §6、§10。
> 本文件只記錄「現況、怎麼操作、接下來做什麼」，決策的理由在 README 與 PLAN，驗證細節在 [`validation/`](validation/)（重要的使用者決定都寫在各文件開頭的「已定案」）。

## 1. 現況快照

- **網站**：<https://brock0312.github.io/civic-lens/>（GitHub Pages）；10/05 起的變動都已上線。
- **原始碼**：<https://github.com/brock0312/civic-lens>（公開，main 為唯一分支；PR #1、#2 已合併）
- **選舉時程**：投票日 2026-11-28；選前上線目標 11/07；10/16 審定候選人、10/23 號次抽籤、11/12 公告市長名單、11/17 公告議員名單、11/25 前選舉公報上網。
- **網站範圍**：只呈現 2026 候選人（§3 第 9 條）；候選人中的現任者標「現任」並呈現問政。

| 範圍 | 已上線 | 尚未完成 |
|---|---|---|
| 全國 22 縣市 | 候選人 1,583 人、選區與名額、村里對照；地圖首頁 → 縣市頁 → 鄉鎮／里 → 選區；21 縣市長任職（V14 文案：宜蘭停職、新竹市停職後復職） | — |
| 現任標示＋2022 公報（L3-A） | **22 縣市全部完成**（10/06 補上雲林、澎湖、屏東、宜蘭、臺東、嘉義市）。公報有文字層者收政見與學經歷；雲林（錯碼）與屏東、宜蘭、臺東、澎湖整縣市只連原檔（無頁碼；屏東第 1 區分兩冊，`etl/bulletin2022.py` 的 `VOLUMES`）；嘉義市不爬名錄，以中選會 2022 當選人建任職（`basis=cec_2022`），標「2022 當選」；2022 年未當選者加註 | 澎湖莊光大（遞補，無 2022 選區）未建任職；臺東董昌華（補選）無 2022 公報 |
| 議會問政紀錄（L3-B） | **臺北**：書面質詢、口頭質詢影片、出缺勤、2022 公報、質詢摘要（第 1、2、3、5 次會期已核可）。**高雄**：質詢影片 3,624（深連結起點）、出缺勤（出席／請假／公差公假／缺席，官方統計表）。**臺中**：影片 3,900。**臺南**：影片 348（YouTube）。**新北**：出缺勤（出席／請假）、書面質詢掃描檔 339、影片清單 3,753（只連影音網首頁）。**花蓮**（10/08）：出缺勤（出席／請假，170 次大會）、口頭質詢答覆 1,350 與書面質詢 38（官方原文題目，`data/hua_withheld.csv` 依第三人規則擋 9 筆）、逐人質詢紀錄頁碼連結、影片 218（整場、未細分到個人） | 臺北摘要第 3、4 次會期；其他 16 縣市：下個 session 普查（§5 第 1 項）；桃園依第 10 條不做 |
| 立委 | 參選 2026 的現任立委 18 人（11 自動＋7 人工確認）：議案、IVOD 發言影片、書面質詢（API 只收錄第 11 屆第 1–3 會期） | 表決、出席（V5，未排） |
| 確定有罪判決 | 區塊與查詢入口（「尚未收錄經查證的確定有罪判決」） | 11/25 公報後才能做（V7） |
| 品質閘門 | `tests/test_invariants.py` 12 條資料不變式（生日、只收核可摘要、只呈現候選人、無「無前科」、出處完整等），CI 每次部署都跑 | — |

## 2. 架構與資料流

```
本機（臺灣網路）python3 -m etl.run
  └─ etl/sources/*（每個來源一支）→ SQLite → data/civic.sql（文字 dump，進 git）
git push origin main
  └─ GitHub Actions：test job（唯讀）通過 → deploy job 由 civic.sql 匯出 site/data → 只部署 site/
```

- **ETL 只能在本機跑**：臺北市議會全系統、內政部村里檔、中選會開票 JSON 都擋海外 IP，GitHub 機器抓不到。每日排程已停用，資料採**手動更新**（步驟見 README「資料更新」）。
- **來源**（`etl/run.py` 的 `SOURCES`，順序有依賴）：`tpe_districts`、`tpe_candidates`、`national_districts`、`national_legislators`、`national_candidates`、`national_heads`（縣市長任職＋`data/head_status.csv`）、`national_councilors`（議會官網現任名錄，縣市清單見 `ISOS`）、`khh_videos`、`txg_videos`、`tnn_videos`（高雄、臺中、臺南現任議員質詢影片）、`khh_attendance`、`nwt_book`（新北出缺勤與書面質詢）、`nwt_videos`（新北影片清單，只連影音網首頁，因單支網址依賴 session）、`national_bulletin_2022`（2022 公報政見與學經歷，縣市清單見 `ISOS`）、`tcc_councilors`、`tcc_interpellations`、`tcc_videos`、`tcc_attendance`、`tcc_summaries`、`tpe_bulletin_2022`、`ly_legislators`（立法院 API 第 11 屆名冊；人工確認表 `data/identity_legislators.csv`）、`ly_records`（只抓已串到候選人的立委）。立法院 API 共用函式在 `etl/lyapi.py`；本機可設環境變數 `LYAPI_TOKEN`（data.openfun.tw 的 Token，不進 repo）避免限流。
- **前端**：`site/`，純 HTML／CSS／vanilla JS，無 build、無依賴。設計語言為「報導式數據新聞」、單色、黨徽是全頁唯一的彩色。路由：`#/` 地圖、`#/c/<iso>` 縣市、`#/d/<id>` 選區、`#/p/<id>` 人物。選區判定、職稱等純函式在 `site/geo.js`；村里資料依縣市拆成 `data/villages/<iso>.json`，按需載入。有深度資料的縣市列在 `geo.js` 的 `DEEP_COUNTIES`（目前為 tpe、khh、txg、tnn、nwt），議會官網在 `COUNCIL_SITES`。村里名的造字已改用中選會寫法（`etl/moi.py` 的 `CEC_VILLNAMES`，21 筆）。測試：`node --test site/app.test.mjs`（一定要指定檔案）。
- **測試**：`python3 -m unittest`、`node --test site/app.test.mjs`。判斷是否通過一律看 exit code，不要只看經過 `grep`／`tail` 管線的輸出。

## 3. 一定要遵守的規則

1. **只推 main**，絕對不要 `git push --all`。新環境請先安裝 pre-push hook：`cp scripts/git-hooks/pre-push .git/hooks/ && chmod +x .git/hooks/pre-push`。它會擋下：推 main 以外的 branch、dump 含生日、未審閱通過的摘要檔。
2. **生日不進公開 dump**：`etl/db.py` 的 `dump()` 會清空；push 前用 README 的檢查指令再確認一次。
3. **質詢摘要必須審閱通過才上線**：`data/summaries/14-0N.json` 的 `review.status` 為 `approved` 才會被 ETL 收錄；待審的摘要檔**不要 commit**（repo 是公開的）。
4. **不轉載 council2026.taiwangogo.tw 的內容**，只放網站層級連結與揭露聲明；它只能當查證線索。
5. **不顯示「無前科」**；不評分、不排名；同名無法唯一確認身分時不顯示。**最怕把資料掛錯人**：對不上就不收，不要猜。
   **第三人規則（2026-10-07 使用者決定擴大）**：公開的文字（摘要正文、議題、引文）不得點名「非公職第三人＋違法／刑案」，也不得點名「非民選公務員（事務官，如處長、科長、股長）＋不當行為指控」；只能以職稱敘述官員在公開會議證實的事實，並避免職稱以外可識別的細節。對不上就 `drop_issue` 或刪掉該段。已公開 git 歷史中的 `cited_text` 不改寫歷史，有當事人要求再處理（同日使用者決定）。
6. **commit 身分**：repo 內 `user.email` 是 GitHub noreply；commit 訊息格式 `<type>: <description>`（type 只用 feat、fix、refactor、docs、test、chore、perf、ci），不加 AI 署名。
7. **記憶體**：使用者的電腦記憶體吃緊。同時最多 2 個 agent；不要同時跑多個會開 headless 瀏覽器的 agent；長時間批次用 `nohup` 在背景跑，不要讓 agent 坐等（agent 600 秒沒有進度會被中止）。
8. **暫存**：系統暫存區重開機會被清空；需要保留的快取放 `data/cache/`（已 gitignore）。
9. **網站只呈現 2026 候選人**（2026-10-03，全站一致含臺北）：候選人如果是現任議員或縣市長，標「現任」（同選區）或「現任＋職稱」（別的選區或職位）；沒有參選 2026 的現任者不出現在網站上。ETL 照常收集現任資料，只在 `etl/export.py` 與前端過濾；摘要批次也跳過沒參選者。
10. **需要對方授權的內容一律不做**（2026-10-05，使用者決定簡化流程）：報導者觀測站、桃園議會影片都已取消；遇到條款限制或需要書面同意的來源，直接跳過，不寄信、不擷取。
11. **身分人工確認**：審閱清單上的人由 Claude 初審、verifier 複核（附官方來源），通過才寫進 `data/identity_national.csv`（議員）或 `data/identity_legislators.csv`（立委），`confirmed_by` 照實寫「Claude 初審；verifier 複核」。

## 4. 常用操作

### 資料更新並上線
見 README「資料更新」。重點：`python3 -m unittest` → `python3 -m etl.run` → 生日檢查 → 只 commit `data/civic.sql` → `git push origin main`。
- **完整 ETL 很慢**（立法院 API 會限流，程式會自動退避重試；設環境變數 `LYAPI_TOKEN` 可減少）。只改了少數來源時，用**局部補跑**：從標準輸入執行（`python3 -u - <<'EOF'`，讓 `etl` 可匯入；放在 /tmp 的腳本要加 `PYTHONPATH=.`），`open_db` → 只跑該幾個來源（照 `etl/run.py` 的順序）→ `dump` → `export`。補跑前先 `cp data/civic.sql data/cache/civic.sql.bak-<名稱>`，補跑後用「排序後逐行比對」確認變動（`sort` 兩份 dump 再 `comm -3`；不要用 `diff` 看筆數，大量插入時會誤判成改動）。
- **局部補跑的陷阱**：`tpe_bulletin_2022` 要靠 `tcc_councilors` 先抓回議員生日（dump 不存生日），所以補跑臺北公報時一定要連 `tcc_councilors` 一起跑。
- **議會網站偶爾斷線**：`etl/rosters.py` 會對連線類錯誤重試 3 次；若仍失敗，該來源整批回滾（資料不會遺失，因為資料庫每次由上一份 dump 重建），重跑即可。
- **縣市長狀態重查**（V14 §5，每次上線前與每週一次，直到 2026-12-25）：`python3 scripts/check_head_status.py`。exit 1 代表需要人工確認，必要時更新 `data/head_status.csv` 再跑 ETL。最近一次：10/06 無變動。
- **上線前驗證**：非瑣碎的變動交給 verifier（抽樣對照原始 PDF／官網、確認沒有掛錯人、用一個 headless Chrome 看頁面含 375px 寬），通過才 push。

### 質詢摘要（NotebookLM，只做臺北）
- **登入**：只能在 Mac 的「終端機」App 執行 `notebooklm login --fresh`。用前先確認 `notebooklm auth check --test --json` 的 `token_fetch` 為 true。
- **每日額度**：約 40–50 次提問；額度用完時 `batch.py` 會自動停下，隔天用同一指令續跑：`nohup python3 scripts/summaries/batch.py 01 02 03 04 > data/cache/summaries_batch_0104.log 2>&1 &`（續跑前可先把舊 log 另存）。
- **流程**：批次輸出 `data/summaries/14-0N.json`（pending）→ verifier 抽樣審閱（至少 12 位議員，固定 seed，標準見 [S1](validation/S1-summaries-pilot.md)）→ 修訂寫進 `data/summaries/edits/14-0N.json` → `batch.py 0N --cached` 重建（不耗額度）→ review 設為 approved（by、at、note）→ commit 摘要與修訂檔 → 局部補跑 `tcc_summaries` → verifier → push。
- **修訂的教訓**：引文同時含議員與官員發言時，**不要只刪發言標籤**（會把官員的話誤歸議員），要刪整段引文，或刪整句；點名非公職第三人並提及違法、刑案的議題整題刪除（`drop_issue`）。
- **修訂動作**（`scripts/summaries/batch.py` 的 `apply_edits`，只能刪、不能加字）：`drop_issue`、`drop_response_sentence`、`drop_point_text`（議員段落逐字刪）、`drop_citation`（依 `page`＋必要時 `cited_prefix` 刪引用）。
- **引用原文不公開**（2026-10-07，法遵審查）：公開輸出的 citation 只留 `source_url`、`page`；完整 `cited_text` 只在 `data/cache/`（審閱用）。`tests/test_invariants.py` 會擋。第 3 次會期錯誤率約 11%，使用者決定**全數人工審閱**（不只抽樣）；涉及性騷擾、性侵、霸凌、弊案、懲處的議題要逐題全審，並交 security-executor 看法律風險。
- **已核可的會期不會被覆寫**：重跑已核可的會期時，輸出改寫到 `data/cache/transcripts/14-0N/pending.json`；審閱新增或變動的部分後，複製到 `data/summaries/14-0N.json`、設 approved、commit。
- **長期失敗者**：第 1 次會期 7 人（簡舒培、耿葳、苗博雅、許淑華、詹為元、郭昭巖、鍾佩玲）、第 2 次 2 人（許淑華、顏若芳）NotebookLM 一直逾時或加入來源失敗，批次每天會重試；若持續失敗就放著，不影響其他人上線。

## 5. 接下來的工作（依優先順序）

| # | 工作 | 下一步 | 參考 |
|---|---|---|---|
| 1 | **16 縣市議會問政紀錄（實作中）** | **花蓮 10/08 上線；下一個是新竹市。** 每個議會照花蓮模式（`etl/sources/hua_book.py`、`hua_videos.py`）；官方原文題目要交 verifier 全量掃第三人規則。官方原文題目一律顯示全文、不截斷（使用者 10/08 決定）。普查完成（[V16](validation/V16-council-records-16.md)，10/07 使用者全部照建議定案，見該文件開頭）。依序實作：花蓮 → 新竹市 → 臺東 → 金門 → 基隆 → 新竹縣 → 彰化 → 南投 → 連江 → 宜蘭 → 雲林 → 澎湖；嘉義市、嘉義縣、苗栗、屏東不做（robots 或無官方逐人紀錄）。每個議會：實作 → 局部補跑 → verifier → push；做完把縣市加進 `geo.js` 的 `DEEP_COUNTIES` 與縣市頁說明 | [V16](validation/V16-council-records-16.md)、[V15](validation/V15-council-records.md) |
| 2 | **臺北摘要第 4 次會期** | 第 3 次會期 10/07 全審後核可上線（49 處修訂）。第 4 次會期批次 10/07 跑完（ok 43、失敗 1），`data/summaries/14-04.json` pending 未 commit，照 §4 流程全數審閱後上線。兩項待決事項已於 10/07 決定（見 §3 第 5 條） | §4 |
| 3 | **選舉時程維運** | **10/16 審定後**：全國移除不合格候選人（`national_candidates`／`tpe_candidates` 改讀審定名單）；11/12、11/17 補號次；11/25 解析 2026 選舉公報（全國新人的政見、學經歷與生日，並用生日複核身分串接） | [V1](validation/V1-candidates-2026.md) |
| 4 | **L3-A 小尾巴（可選）** | 只連原檔的人物頁，「說過什麼」下的跳轉連結仍寫「2022 選舉公報政見與學經歷」，應改成原檔用語；嘉義市人物頁任職行出現兩個相同出處 [2][2]；公報中沒有文字對應的字會被抽成空白（例：林雪峰「台南玄空法 顧問」，原文有「寺」），現有檢查抓不到 | — |
| 5 | **確定有罪判決** | 11/25 公報後補生日核對；建 `kind=conviction` 的 ETL 與人工核可表；每筆由 Claude 初審、verifier 複核；上線前交 security-executor 法遵審查 | [V7](validation/V7-criminal-records.md) |
| 6 | **法遵** | 黨徽使用、判決顯示上線前的審查（security-executor） | PLAN §6 第 4 點、[公開前審查](validation/pre-publication-review.md) |
| 7 | 小事 | 14-05 dump 中有 3 筆沒參選者的摘要（不會匯出，可留）；新北 3 位原住民議員姓名在議會名單與本站格式不同（已能對上）；花蓮第 7 選區 2026 年確定為 1 席（公告） | — |

已取消：報導者觀測站、桃園議會影片（第 10 條）；新北與高雄不做 AI 摘要（使用者決定）。

## 6. 量能評估

- **剩餘工作**：第 4、5 天約 1 session；臺北摘要每個會期約 1 次 verifier 審閱（大約 40 萬 tokens，是最貴的環節）；選舉時程 10/16、11/12、11/17、11/25 各約 0.5–1 session；確定有罪判決約 1 session。
- **成本經驗（10/02–10/05）**：每輪「實作 → 局部補跑 → verifier → push」約 2–3 個 agent。verifier 每次都抓到真問題（掛錯欄位、連結失效、修訂誤歸屬、清理邏輯誤刪），**不要省略**。
- **省成本**：每個 session 只做一條工作線；機械性工作用 mech-executor；長批次用 `nohup`；只改少數來源就局部補跑，不跑完整 ETL；交接一律更新本文件。

## 7. 協作方式（給接手的 Claude）

- 主 session 負責規劃、判斷與最終審查；搜尋交給 scout，實作交給 executor／mech-executor，安全與法遵交給 security-executor，非瑣碎的完成品交給 verifier。
- agent 回報後就停掉（若還在背景執行）。
- 平行的前端工作用獨立 worktree；只 add 自己的檔案；遇到 index.lock 就等幾秒重試。
- 研究知識庫：本專案研究前不查，研究完成也不自動回寫；session 結束時一次列出可回寫的結論，問使用者要不要回寫（見 CLAUDE.md）。
