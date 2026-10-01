# 既有開源專案調查：councilor-voter-guide / twly-voter-guide / council2026.taiwangogo.tw

調查日期：2026-09-28。方法：`gh` CLI 讀取 repo metadata、`git clone --depth 1` 讀原始碼、`curl` 實測網站與爬蟲目標存活、WebFetch/WebSearch 讀取 taiwangogo 頁面與 JS bundle。已實測項目標註「✅實測」，未實測/查不到者標註「❓推測」或「—」。

## 比較總表

| 項目 | councilor-voter-guide (g0v) | twly-voter-guide (g0v) | council2026.taiwangogo.tw |
|---|---|---|---|
| 對象 | 縣市議員／縣市長 | 立法委員 | 議員／縣市長（僅前科面向） |
| 最後 commit | 2018-11-28 ✅實測 | 2018-08-21 ✅實測 | 無公開原始碼 repo，無法測 commit |
| 近一年活躍度 | 0 commits ✅實測 | 0 commits ✅實測 | 網站有更新（favicon 版本號 20260915、內文提及「更新至9/19」）✅實測，但無 repo 可查 |
| Stars / Forks | 106 / 47 ✅ | 64 / 27 ✅ | — |
| Open issues | 39 ✅ | 14 ✅ | — |
| 維運者 | thewayiam 等 g0v 志工，專案已無人維護 ✅ | thewayiam 等 g0v 志工，專案已無人維護 ✅ | 時代力量（代表「台灣前進」四黨聯盟）✅實測（頁尾/聯絡窗口） |
| 線上站存活 | http://councils.g0v.tw/ **逾時/掛掉** ✅實測 | http://vote.ly.g0v.tw/ **404** ✅實測 | https://council2026.taiwangogo.tw/ **200 存活** ✅實測 |
| 程式碼授權 | 無 LICENSE 檔 ✅實測（repo 內找不到 licenseInfo，GitHub API 回傳 null） | 同左，無 LICENSE ✅實測 | 無原始碼可查授權 — |
| 資料授權 | README 僅聲明「預設皆開源」原則，無正式授權條款 ✅實測 | 同左 ✅實測 | 網站僅一句「本人或授權代表」與案件說明無關，未見資料授權聲明 ✅實測 |
| 技術棧 | Django + PostgreSQL（後端／DB），Python 爬蟲（`crawler/`），2018 前端（`2018_frontend/`），Docker 化 ✅實測（讀原始碼） | Django + PostgreSQL + Haystack 搜尋 index，Docker Compose，含 Android App 子專案連結 ✅實測 | 純前端 SPA（`app.js`／`styles.css`），Cloudflare 託管，內嵌 JSON 匯出檔（非資料庫 API）✅實測 |
| 職位涵蓋 | 縣市議員、縣市長 | 立法委員 | 縣市議員、縣市長 |
| 縣市／屆期涵蓋 | `crawler/` 下有 22+ 個議會爬蟲目錄（tcc=台北市議會、kmc、ntp、tycc、hsinchucc…），資料含 2014/2018 屆候選人與議員 ✅實測（目錄與檔名證實），無 2022/2026 資料（專案已停更）| 全國立法院，屆期至 2018 年停止更新 ✅實測 | 全台 22 縣市（`districts.json` 內建每縣市選區），2026 選舉候選人 ✅實測 |
| 欄位涵蓋 | 議員基本資料、政治獻金（`data/political_contribution`）、候選人資料、部分縣市會議紀錄/提案（`crawl_bills.sh`/`crawl_suggestions.sh`）、大頭照 ✅實測；**無**質詢影片連結、無出席率統計程式碼證據 | 立委資料、法案(`bill`)、委員會(`committees`)、議程(`sittings`)、投票(`vote`)、發言立場(`standpoint`)、標籤(`commontag`) — 欄位設計上最接近civic-lens要的「提案/表決」，✅實測（目錄結構） | **僅刑事前科**：有罪/起訴中/行政罰/民事當選無效/家族接棒，含判決來源連結（`judgment.judicial.gov.tw`）；**不含**出席、質詢、提案表決、政見兌現、公司董監事關係 ✅實測（`export/people.json` 欄位） |
| 公司董監事關聯 | 未見 | 未見 | 未見（僅前科，非財產/公司關係） |
| 爬蟲存活測試 | 台北市議會 `crawler/tcc` 目標 URL（`www.tcc.gov.tw/Councilor_Main.aspx`、`obas_front.tcc.gov.tw`、`tccmis.tcc.gov.tw`）：主網域 `www.tcc.gov.tw` 現仍存在（DNS解析成功、https 200），但爬蟲寫死的舊版 `.aspx` 路徑逾時/掛掉，`tccmis.tcc.gov.tw` 已無法解析 DNS — **爬蟲程式碼已失效，需重寫** ✅實測 | 未逐一實測（README 顯示用 Docker + `local_db.dump` 匯入資料庫，爬蟲程式本身也依附立法院舊版網站結構，8年未更新，高機率同樣失效）❓推測 | 無爬蟲程式碼可查（資料以靜態 JSON 匯出方式提供，無法判斷後端爬蟲现况）— |
| 可下載 dump／API | repo 內含 `data/*.json`、候選人 xlsx 等靜態資料檔（2014/2018年，非即時 API）✅實測 | repo 內含 `local_db.dump`（PostgreSQL dump，同樣是舊資料，非即時 API）✅實測 | **有**：`/export/people.json`、`/export/districts.json`、`/export/taiwan-counties.json`（含 SVG 地圖座標）皆為公開可直接 curl 取得的靜態 JSON，回傳 200 且為合法 JSON ✅實測 | 
| civic-lens 可重用性 | 僅供「爬蟲邏輯／資料模型」參考，資料本身過舊（2014/2018）不可直接用；程式碼老舊（Python2 風格 Django、無 LICENSE）fork 成本高 | 資料模型（`bill`/`vote`/`standpoint`/`sittings`）設計思路值得參考，尤其是立委「提案/表決」資料結構最貼近我們的需求，但資料同樣停在2018，且無 LICENSE 不能確定能否重用程式碼 | **前科欄位可直接參考其資料結構與判決來源連結方式**，且是三者中唯一涵蓋 2026 屆期、唯一還在運作的；但範圍窄（只做前科，不做出席/質詢/提案/政見/公司關係），且無 GitHub repo、無明確授權聲明，法律上能否重製其 JSON 需先詢問維運者(時代力量/台灣前進) |
| 與 civic-lens 目標的差距 | 缺：影片連結、出席率、質詢逐字稿、政見兌現追蹤、公司董監事關聯；缺 2022/2026 最新屆期資料 | 缺：影片連結、政見兌現、公司董監事關聯；缺 2020/2024屆期後資料 | 缺：出席、質詢(+影片)、提案/表決、政見/兌現、公司董監事關聯（本人+配偶+未成年子女）；只做臺北等22縣市的議員/縣市長前科，立委未涵蓋 |

## 三個爬蟲目標存活實測明細

- `http://councils.g0v.tw/`（councilor-voter-guide 首頁）：連線逾時，網站已死。
- `http://vote.ly.g0v.tw/`（twly-voter-guide 首頁）：回傳 404，網站已死。
- `https://council2026.taiwangogo.tw/`：回傳 200，正常運作，SPA 架構（所有路徑皆 fallback 回 `index.html`，需靠已知的 `/export/*.json` 路徑取得資料）。
- `crawler/tcc`（台北市議會爬蟲，councilor-voter-guide 內）：舊版 ASP.NET 路徑（`Councilor_Main.aspx`）與內部子網域（`obas_front.tcc.gov.tw`、`tccmis.tcc.gov.tw`）皆已逾時或無法解析；台北市議會主網域本身仍活著且改版過，代表爬蟲需要針對新版網站結構整個重寫，不能沿用舊程式碼。

## 建議：自建 vs 重用

**結論：三個專案都不能直接拿來用；但各有不同程度的參考價值，整體建議「自建為主、局部重用」。**

理由：

1. **兩個 g0v 專案（councilor-voter-guide、twly-voter-guide）已死亡超過7年**：無commit、無LICENSE、線上站分別逾時/404、爬蟲目標網址（至少實測台北市議會）已失效。Fork 它們等於要重寫全部爬蟲＋升級整個技術棧（Python2時代Django、無測試、資料模型設計是2014年的認知），成本接近重新開發，而且法律上因無LICENSE，重製其舊資料集的合法性不明確（頂多當「範例/沿革參考」，不建議直接拿 data/ 內的舊JSON上線）。
   - **可重用的是「資料模型設計」與「屆期/爬蟲涵蓋範圍清單」**：twly-voter-guide 的 `bill`/`vote`/`standpoint`/`committees`/`sittings` 拆分，對「提案/表決」這塊的欄位設計值得參考；councilor-voter-guide 的 `crawler/` 目錄列出了全台各縣市議會的爬蟲入口點命名慣例，可以當作「civic-lens 需要對接哪些議會官網」的清單起點（但URL本身多半已失效，需重新踩點）。

2. **council2026.taiwangogo.tw 是活的、資料新（涵蓋2026選舉）、且有可直接下載的公開JSON（`/export/people.json`、`/export/districts.json`）**，但範圍窄——只做「法定公開前科」單一面向，且無原始碼repo、無明確授權聲明、維運者是特定政黨聯盟（時代力量/台灣前進），資料立場聲明雖標榜中立（「列名不代表有前科」），但終究是政黨背景營運，civic-lens若要引用其資料需：
   - 先聯繫維運者確認資料能否重製/連結引用（目前找不到公開授權條款，直接爬取後大量重製有法律風險）；
   - 若只做「連結出去」（deep link 到其頁面，不重製資料），風險低很多，且可以立即補足我們「法定公開前科」這塊欄位的缺口，不需要自己重做整個判決書爬蟲。

3. **civic-lens 核心需求（出席、質詢＋影片、提案/表決、政見兌現、公司董監事關係，且要跨全國立委＋北市議員/市長雙軌）三個專案都沒人做齊**，尤其「政見兌現追蹤」與「本人+配偶+未成年子女公司關係」在三者中完全找不到對應實作。這代表核心資料模型與大部分爬蟲仍需自建。

**具體建議**：
- 前科欄位：優先接觸 taiwangogo 維運者談資料使用/連結授權，若談不攏就走「連結引用」而非重製，不必自己重寫法院判決爬蟲。
- 議會/立院爬蟲：以 twly-voter-guide 與 councilor-voter-guide 的資料模型與爬蟲目標清單當「地圖」，逐一重新踩點現行官網（本次已證實至少台北市議會官網已改版，爬蟲需全部重寫），採自建。
- 出席/質詢影片/提案表決/政見兌現/公司關係：全部自建，市面上找不到對應的既有開源實作可以fork。
- 不建議 fork 任一 repo 當程式碼骨架——技術棧過舊（無測試、無LICENSE、Python2時代Django慣例），維護成本高於重寫。
