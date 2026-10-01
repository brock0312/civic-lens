# 交接文件（新 session 從這裡開始）

> 最後更新：2026-10-02。新的工作階段請先讀完本文件，再讀 [README](../README.md)、[PLAN](PLAN.md) §6、§10。
> 本文件只記錄「現況、怎麼操作、接下來做什麼」，決策的理由在 README 與 PLAN，驗證細節在 [`validation/`](validation/)。

## 1. 現況快照

- **網站**：<https://brock0312.github.io/civic-lens/>（GitHub Pages）
- **原始碼**：<https://github.com/brock0312/civic-lens>（公開，main 為唯一分支）
- **選舉時程**：投票日 2026-11-28；選前上線目標 11/07；10/16 審定候選人、10/23 號次抽籤、11/12 公告市長名單、11/17 公告議員名單、11/25 前選舉公報上網。

| 範圍 | 已上線 | 尚未完成 |
|---|---|---|
| 全國 22 縣市 | 2026 候選人名單（1,583 人）、選區與名額、村里對到議員／立委選區；**全國查詢前端**（2026-10-02）：首頁台灣地圖＋縣市清單 → 縣市頁（鄉鎮 → 跨選區時選里 → 原住民身分）→ 議員選區與縣市長；非臺北縣市標示「深度資料建置中」並連議會官網 | 21 縣市的深度資料（見 §5 的 L3-A、L3-B） |
| 臺北市議會 | 現任名錄與身分對照、書面質詢 2,473 筆、口頭質詢影片 2,918 筆（深連結到質詢組起點）、大會出缺勤 6,413 筆（出席率、請假率）、2022 公報政見與學經歷、市長任職、第 5 次定期大會質詢摘要（40 人） | 第 1–4 次定期大會摘要（批次進行中，log：`data/cache/summaries_batch_0104.log`）、第 5 次剩 8 人 |
| 其他 21 個議會 | 無 | 全部（見 §5 的 L3） |
| 立委 | 選區對照 | 名冊、質詢、提案、表決、出席（govapi，見 §5） |
| 確定有罪判決查詢 | 區塊與查詢入口（目前顯示「尚未收錄經查證的確定有罪判決」） | 查證流程與 ETL，最快 11/25 公報後才有可顯示的資料（見 [V7](validation/V7-criminal-records.md)） |

## 2. 架構與資料流

```
本機（臺灣網路）python3 -m etl.run
  └─ etl/sources/*（每個來源一支）→ SQLite → data/civic.sql（文字 dump，進 git）
git push origin main
  └─ GitHub Actions：test job（唯讀）通過 → deploy job 由 civic.sql 匯出 site/data → 只部署 site/
```

- **ETL 只能在本機跑**：臺北市議會全系統、內政部村里檔、中選會開票 JSON 都擋海外 IP，GitHub 機器抓不到。每日排程已停用，資料採**手動更新**（步驟見 README「資料更新」）。
- **來源**（`etl/run.py` 的 `SOURCES`，順序有依賴）：`tpe_districts`、`tpe_candidates`、`national_districts`、`national_legislators`、`national_candidates`、`tcc_councilors`、`tcc_interpellations`、`tcc_videos`、`tcc_attendance`、`tcc_summaries`、`tpe_bulletin_2022`。
- **前端**：`site/`，純 HTML／CSS／vanilla JS，無 build、無依賴。設計語言為「報導式數據新聞」、單色、黨徽是全頁唯一的彩色。路由：`#/` 地圖、`#/c/<iso>` 縣市、`#/d/<id>` 選區、`#/p/<id>` 人物。選區判定、職稱等純函式在 `site/geo.js`；村里資料依縣市拆成 `data/villages/<iso>.json`，按需載入。有深度資料的縣市列在 `geo.js` 的 `DEEP_COUNTIES`（目前只有 tpe），議會官網在 `COUNCIL_SITES`。村里名的造字已改用中選會寫法（`etl/moi.py` 的 `CEC_VILLNAMES`，21 筆）。測試：`node --test site/app.test.mjs`（一定要指定檔案）。
- **測試**：`python3 -m unittest`、`node --test site/app.test.mjs`。判斷是否通過一律看 exit code，不要只看經過 `grep`／`tail` 管線的輸出。

## 3. 一定要遵守的規則

1. **只推 main**，絕對不要 `git push --all`。新環境請先安裝 pre-push hook：`cp scripts/git-hooks/pre-push .git/hooks/ && chmod +x .git/hooks/pre-push`。它會擋下：推 main 以外的 branch、dump 含生日、未審閱通過的摘要檔。
2. **生日不進公開 dump**：`etl/db.py` 的 `dump()` 會清空；push 前用 README 的檢查指令再確認一次。
3. **質詢摘要必須審閱通過才上線**：`data/summaries/14-0N.json` 的 `review.status` 為 `approved` 才會被 ETL 收錄；待審的摘要檔**不要 commit**（repo 是公開的）。
4. **不轉載 council2026.taiwangogo.tw 的內容**，只放網站層級連結與揭露聲明；它只能當查證線索。
5. **不顯示「無前科」**；不評分、不排名；同名無法唯一確認身分時不顯示。
6. **commit 身分**：repo 內 `user.email` 是 GitHub noreply；commit 訊息格式 `<type>: <description>`，不加 AI 署名。
7. **記憶體**：使用者的電腦記憶體吃緊。不要同時跑多個會開 headless 瀏覽器的 agent；長時間批次用 `nohup` 在背景跑，不要讓 agent 坐等（agent 600 秒沒有進度會被中止）。
8. **暫存**：系統暫存區重開機會被清空；需要保留的快取放 `data/cache/`（已 gitignore）。

## 4. 常用操作

### 資料更新並上線
見 README「資料更新」。重點：`python3 -m unittest` → `python3 -m etl.run` → 生日檢查 → 只 commit `data/civic.sql` → `git push origin main`。

### 質詢摘要（NotebookLM）
- **登入**：只能在 Mac 的「終端機」App 執行 `notebooklm login --fresh`，登入後在終端機按 Enter。Claude Code 的 `!` 指令沒有 stdin，login 會失敗。用前先確認 `notebooklm auth check --test --json` 的 `token_fetch` 為 true。
- **每日額度**：一般方案約 40–50 次提問；額度用完時 NotebookLM 會回空白答案，`batch.py` 會自動停下且不寫快取，隔天用同一指令續跑。
- **流程**：
  1. `nohup python3 scripts/summaries/batch.py 01 02 03 04 > data/cache/summaries_batch.log 2>&1 &`（會依序抓速記錄、切分、送 NotebookLM、檢查過濾，輸出 `data/summaries/14-0N.json`，review 為 pending）
  2. 交給 verifier **抽樣審閱**（每會期至少 10 份，固定 seed），標準見 [S1](validation/S1-summaries-pilot.md) 與兩輪審閱的做法：歸屬、回應正確、沒有捏造、沒有扭曲、中立、引文頁碼。
  3. 有問題的議題或句子寫進 `data/summaries/edits/14-0N.json`（可稽核的人工修訂），再用 `batch.py 0N --cached` 重建（不消耗額度）。
  4. 把 `review` 改成 `approved`（by、at、note），commit 該會期摘要與修訂檔，跑 ETL、push。
- **已知陷阱**：NotebookLM 會把官員在別的議題的承諾放進「市府回應」；約 5–10% 議題的引文只是寒暄。程式已有同場次檢查、文字相似度偵測與相關性過濾（`RELEVANCE_MIN`，邊界很薄，換會期要重看分數分布），但**人工抽樣仍是必要的閘門**。
- **重建會把 review 改回 pending**：已核可的會期如果重建，要重新核可。

## 5. 接下來的工作（依優先順序）

| # | 工作 | 下一步 | 參考 |
|---|---|---|---|
| 1 | **摘要第 1–4 次會期** | 批次每天續跑；跑完一個會期就抽樣審閱、修訂、核可、上線。第 5 次剩 8 人（快取裡沒有回答）也要補跑 | §4 |
| 2 | **L3-A 各縣市基本深度** | 全國地圖前端已完成（10/02）。下一步：先把 2022 公報解析（`tpe_bulletin_2022`）通用化到其他 21 縣市，再做各議會現任名錄＋身分對照、首長任職；每天 5 縣市。縣市完成後加進 `site/geo.js` 的 `DEEP_COUNTIES`，並調整人物頁的空白說明 | §6、[V11](validation/V11-national-lists.md)、[V12](validation/V12-councils-survey.md) |
| 3 | **選舉時程維運** | 10/16 審定後移除不合格者（全國）；11/12、11/17 補號次；11/25 解析 2026 公報（全國新人的政見、學經歷與生日） | [V1](validation/V1-candidates-2026.md) |
| 4 | **立委全國** | govapi（`v2.ly.govapi.tw`）名冊、書面質詢、提案、表決、IVOD；出席欄位先做 V5 驗證 | PLAN §2、§7 |
| 5 | **其他議會（L3）** | 先完成 V12 普查（新北網站曾連不上、桃園與 16 縣市未查），依平台分組；高雄最容易（影片 API 可逐人、有出席統計表），臺中、臺南可做名錄與影片 | [V12](validation/V12-councils-survey.md) |
| 6 | **報導者觀測站議題標籤** | 使用者已同意：個人頁深連結，議題名稱與相關提案數原文照錄並標示出處（CC BY-NC-ND 3.0 TW） | README |
| 7 | **確定有罪判決** | 11/25 公報後補生日核對；建 `kind=conviction` 的 ETL 與人工核可表；每筆由 Claude 初審、verifier 複核 | [V7](validation/V7-criminal-records.md) |
| 8 | **法遵** | 黨徽使用、判決顯示上線前的審查（security-executor） | PLAN §6 第 4 點、[公開前審查](validation/pre-publication-review.md) |

## 6. 量能評估（不含 NotebookLM 摘要）

以「一個 session ≈ 一天、3–6 個 agent 回合、同時最多 1–2 個 agent」估算：

| 工作 | 性質 | 估計 |
|---|---|---|
| 全國地圖前端 | 一次性 | 0.5–1 session |
| L3-A 各縣市基本深度：議會現任名錄＋身分對照＋2022 公報政見學經歷＋首長任職 | 資料大多來自中選會，通用；名錄爬蟲每縣市一支但都很小 | 先 1–2 session 把 2022 公報解析器通用化，之後**每天 5 縣市可行**，21 縣市約 5 session |
| 立委全國 | 單一來源 | 1–2 session |
| V12 普查收尾 | 一次性 | 1 session |
| L3-B 各議會專屬深度：書面質詢、口頭質詢影片、出缺勤 | 每個議會系統不同，目前沒發現共用平台 | **每天 1–2 個議會**，21 個議會約 10–20 session；若 16 縣市有共用平台可再縮短 |
| 選舉時程維運 | 分散在 10/16–11/25 | 4–5 session |
| 確定有罪判決 | 11/25 之後 | 1 session |

- **合計約 25–35 個 session**（約 4–6 週）。
- **每天 5 縣市**：基本深度（L3-A）與前端做得到；議會專屬深度（L3-B）做不到，實際約每天 1–2 個議會。
- **建議排程**：先全國地圖＋L3-A 全部縣市（約 7–8 session，10/12 前）→ 立委 → L3-B 六都 → 其他縣市依 V12 分組；10/16、11/12、11/17、11/25 的時程工作優先插隊。
- **省成本**：每個 session 只做一條工作線；機械性工作用 mech-executor；長批次用 `nohup`；交接一律更新本文件。

## 7. 協作方式（給接手的 Claude）

- 主 session 負責規劃、判斷與最終審查；搜尋交給 scout，實作交給 executor／mech-executor，安全與法遵交給 security-executor，非瑣碎的完成品交給 verifier。
- agent 回報後就停掉（若還在背景執行）。
- 平行的前端工作用獨立 worktree；只 add 自己的檔案；遇到 index.lock 就等幾秒重試。
- 研究類工作完成後，依使用者的全域規則用 `kb.py inbox` 回寫研究知識庫。
