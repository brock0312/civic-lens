# civic-lens 相關開源專案普查

> **勘誤（2026-09-28 verifier 檢核）**：各表「最後更新」欄原本取自 GitHub `updated_at`（star、metadata 異動也會更新），不代表程式有在維護。已校正的列會標註「程式最後 push」（`pushed_at`）；其餘未標註的列可能仍是 `updated_at`，使用前請以 `pushed_at` 重查。kiang/elections 的授權為 MIT。

調查日期：2026-09-28
方法：`gh search repos`（GitHub Search API）+ 已知 g0v／openfun 生態系 owner 巡覽。
排除範圍：g0v/councilor-voter-guide、g0v/twly-voter-guide、council2026.taiwangogo.tw（另有人負責）。
僅列出已用 `gh`/GitHub API 確認過 URL 真實存在的專案；未能確認的一律不收錄。

---

## 最值得用的前 10 名

| # | 專案 | URL | 一句用途 |
|---|------|-----|---------|
| 1 | ly.govapi.tw-v2 (openfunltd) | https://github.com/openfunltd/ly.govapi.tw-v2 | 立法院結構化 API 主力來源：立委、會議、質詢、表決、提案，civic-lens 立委資料的第一候選後端 |
| 2 | twcompany (openfunltd) | https://github.com/openfunltd/twcompany | 台灣統一編號/公司登記資料，176★，做「候選人本人+配偶+子女董監事關係」查核的資料底層 |
| 3 | company-graph (ronnywang) | https://github.com/ronnywang/company-graph | 公司關係圖產生器，可直接拿來畫董監事關聯網路 |
| 4 | tw-legal-rag (aa0101181514) | https://github.com/aa0101181514/tw-legal-rag | 2,250萬筆裁判書 + 行政函釋 + 憲法法庭裁判的 MCP/CLI，325★，做「法定公開前科」查詢的現成資料源 |
| 5 | twgeojson (ronnywang) | https://github.com/ronnywang/twgeojson | 台灣行政區域（含村里）疆界 GeoJSON（程式 2013 年後未更新，村里界過舊，PLAN §3 不採用） |
| 6 | taiwan-address-lookup (ronnywang) | https://github.com/ronnywang/taiwan-address-lookup | 地址轉經緯度 API（2017 年後未更新，PLAN §3 不採用） |
| 7 | CECDataSet (MISNUK) | https://github.com/MISNUK/CECDataSet | 中選會歷年選舉資料集（含地方選舉候選人/得票），選民輸入所在地後比對候選人名單用 |
| 8 | ardata (openfunltd) | https://github.com/openfunltd/ardata | 監察院政治獻金公開查閱平台，openfun 團隊維護中，做候選人政治獻金頁面可直接參考/借資料 |
| 9 | elections (kiang) | https://github.com/kiang/elections | 收集全台各層級選舉候選人個人資料的平台，政見/候選人資料庫可借鏡或串接 |
| 10 | pcc.g0v.ronny.tw (openfunltd) | https://github.com/openfunltd/pcc.g0v.ronny.tw | 標案資料 API，可用來查候選人相關公司是否承接政府標案（廉政面向延伸） |

---

## 分組清單

### A. 立法院資料（openfun／ronnywang／國會相關工具）

| 專案 | URL | 用途 | 最後更新 | ★ | 授權 | 對 civic-lens 用途 |
|---|---|---|---|---|---|---|
| openfunltd/ly.govapi.tw-v2 | https://github.com/openfunltd/ly.govapi.tw-v2 | 立法院開放資料 API v2（立委、會期、議案、質詢、表決） | 2026-08 | 11 | BSD-3 | **資料來源**：立委出席/質詢/表決主力後端 |
| openfunltd/ly.govapi.tw | https://github.com/openfunltd/ly.govapi.tw | 同上舊版/主 repo，持續更新 | 2026-09 | 0 | 無 | 資料來源，需比對與 v2 差異 |
| openfunltd/dataly-v2 | https://github.com/openfunltd/dataly-v2 | 立法院統合資料網 v2 | 2026-09 | 2 | 無 | 參考架構 |
| openfunltd/dataly-old-v1 | https://github.com/openfunltd/dataly-old-v1 | 立法院統合資料網舊版 | 2026-07 | 0 | MIT | 已被 v2 取代，僅供歷史參考 |
| openfunltd/lymeet.openfun.app | https://github.com/openfunltd/lymeet.openfun.app | 立法院會議資料展示平台 | 2025-01 | 3 | 無 | 參考 UI/資料串接方式 |
| openfunltd/lysayit-api | https://github.com/openfunltd/lysayit-api | 立法院逐字稿相關 API | 2025-01 | 2 | 無 | 逐字稿資料來源候選 |
| openfunltd/law-diff | https://github.com/openfunltd/law-diff | 法律修正前後比對 | 2026-07 | 20 | MIT | 政見兌現（修法追蹤）可參考 |
| openfunltd/lawtrace | https://github.com/openfunltd/lawtrace | 法案追蹤 | 2026-09 | 7 | BSD-3 | 提案/修法追蹤參考 |
| openfunltd/ly-tc-toolkit | https://github.com/openfunltd/ly-tc-toolkit | 立法院繁體中文處理工具 | 2025-04 | 1 | BSD-3 | 文字前處理工具 |
| openfunltd/chewing-cow | https://github.com/openfunltd/chewing-cow | 立法院開放資料長字串結構化解析 | 2024-08 | 0 | MIT | 公報/會議紀錄解析參考 |
| davidycliao/legisTaiwan | https://github.com/davidycliao/legisTaiwan | R 語言存取立法院 API 套件 | 2026-08 | 43 | Other | 參考 API 欄位定義，非直接可用（R語言） |
| ronnywang/TWLegislativeYuanData | https://github.com/ronnywang/TWLegislativeYuanData | 台灣立法院資料整理 | 2026-08 | 6 | 無 | 資料來源候選 |
| g0v/ruby_twly_crawler | https://github.com/g0v/ruby_twly_crawler | 立法院爬蟲，抓立委資訊 | 2026-08（近期有活動但內容久遠） | 5 | MIT | 舊專案，架構參考，**基本已停滯** |
| wspooong/LY-Transcription | https://github.com/wspooong/LY-Transcription | 下載立法院公報並轉 JSON | 2026-08 | 31 | 無 | **資料來源**：公報逐字稿轉結構化 |
| watchout-tw/question-parser | https://github.com/watchout-tw/question-parser | 立法院質詢資料解析 | 2015-08 | 5 | 無 | **已停止維護**，僅供解析邏輯參考 |
| nansenat16/tw-legis-log-parser | https://github.com/nansenat16/tw-legis-log-parser | 立法院議事錄分析 | 2023-01 | 6 | 無 | **已停止維護**，解析邏輯參考 |
| q10242/LegislatureVideoCalender | https://github.com/q10242/LegislatureVideoCalender | 立法院日期分類器（IVOD相關） | 2023-01 | 4 | 無 | **已停止維護**，IVOD 對應日期參考 |
| denkeni/CCWatch | https://github.com/denkeni/CCWatch | 立法院大小聲 App，質詢影片/聲量 App | 2026-09 | 15 | Unlicense | 質詢影片呈現方式參考，近期仍有活動 |
| cellvinchung/sayit_raw_data | https://github.com/cellvinchung/sayit_raw_data | 立委錄影與逐字稿原始資料 | 2024-12 | 0 | 無 | 逐字稿資料來源，**活躍度低** |
| mashbean/pocket-maple | https://github.com/mashbean/pocket-maple | 立法院公聽會書面意見封存（Cloudflare Worker） | 2026-09 | 0 | Other | 公聽會意見資料，較新專案 |

### B. 縣市議會資料（議會爬蟲／議事錄／影音）

| 專案 | URL | 用途 | 最後更新 | ★ | 授權 | 對 civic-lens 用途 |
|---|---|---|---|---|---|---|
| tainansprout/tainan-council-watch | https://github.com/tainansprout/tainan-council-watch | 台南議會觀測網 | 2023-01 | 2 | MIT | **資料來源／可 fork**：縣市議會層級觀測站範本，civic-lens 縣市議員資料可直接參考架構 |
| kiang/tainan.olc.tw | https://github.com/kiang/tainan.olc.tw | 源自台南市議員選舉，擴展為多項公益專案的平台 | 2026-09（近期活躍） | 4 | 無 | 縣市議會/選舉資料整合架構參考 |
| g0v/urbancode-commission | https://github.com/g0v/urbancode-commission | 開放都市計畫－都委會會議紀錄資料庫 | 2020-10 | 3 | 無 | **已停止維護**，會議紀錄資料庫結構參考（非議會本身但性質相近） |

**覆蓋度說明**：縣市議會（議事錄、議員出席/質詢影音）方向找到的現成開源專案很少，僅台南有明確的 council-watch 專案；六都及其他縣市議會的爬蟲/影音工具在 GitHub 搜尋中未見到活躍或成熟結果。此為 civic-lens 需要自行開發的重點缺口。

### C. 選舉資料（中選會／開票／候選人／選區地理）

| 專案 | URL | 用途 | 最後更新 | ★ | 授權 | 對 civic-lens 用途 |
|---|---|---|---|---|---|---|
| MISNUK/CECDataSet | https://github.com/MISNUK/CECDataSet | 中選會歷年選舉資料集 | 2016-07（程式最後 push） | 20 | 無 | **資料來源**：候選人/得票資料 |
| kiang/elections | https://github.com/kiang/elections | 收集全台各層級選舉候選人個人資料平台 | 2026-09 | 38 | MIT | **資料來源／可參考架構**：候選人資料庫 |
| kiang/db.cec.gov.tw | https://github.com/kiang/db.cec.gov.tw | 收集並提供台灣選舉開票結果存取 | 2026-05 | 8 | 無 | **資料來源**：開票結果資料庫 |
| kiang/vote2020 | https://github.com/kiang/vote2020 | 2020選舉監控中選會即時資料 | 2020-04 | 8 | 無 | **已停止維護**，即時開票監控架構參考 |
| ronnywang/vote2014 | https://github.com/ronnywang/vote2014 | 2014中選會界接 API | 2022-08（fork更新） | 2 | 無 | **已停止維護**，API 串接方式參考 |
| ronnywang/twgeojson | https://github.com/ronnywang/twgeojson | 台灣行政區域（含村里）疆界 | 2013-11（程式最後 push） | 47 | 無 | ~~資料來源~~：過舊，不採用 |
| ronnywang/taiwan-address-lookup | https://github.com/ronnywang/taiwan-address-lookup | 地址轉經緯度 API | 2017-03（程式最後 push） | 28 | 無 | ~~資料來源~~：過舊，不採用 |
| hychang32/twelect | https://github.com/hychang32/twelect | 台灣選舉結果村里層級地圖，抓中選會資料疊村里界，產生互動 HTML 地圖 | 2026-09 | 0 | MIT | 全新專案（2026-09），架構/程式碼可直接參考 |
| CindyLinz/BulletinCEC-LocateBlockFromPNG | https://github.com/CindyLinz/BulletinCEC-LocateBlockFromPNG | 從中選會競選公報底圖 PNG 找出候選人格子 | 2017-11 | 2 | MIT | **已停止維護**，選舉公報 OCR 前處理參考 |
| LiuYuWei/2022-local-election-dataset | https://github.com/LiuYuWei/2022-local-election-dataset | 2022縣市長選舉投票資料 | 2023-08 | 3 | 無 | 歷史資料快照，供比對 |
| ceshine/2020-taiwan-election-data | https://github.com/ceshine/2020-taiwan-election-data | 2020總統+立委選舉資料 | 2025-02 | 3 | CC0-1.0 | 歷史資料快照 |
| g0v-data/referendum-2018 | https://github.com/g0v-data/referendum-2018 | 2018公投開票資料週期性爬取 | 2020-05 | 0 | 無 | **已停止維護**，僅供歷史資料 |
| g0v-data/cec-crawler | https://github.com/g0v-data/cec-crawler | 中選會爬蟲 | 2016-01 | 0 | 無 | **已停止維護（陳舊）** |
| benblackcake/votespider | https://github.com/benblackcake/votespider | 中選會爬蟲測試 | 2019-03 | 3 | 無 | **已停止維護**，僅供參考 |

### D. 政見追蹤／政治人物資料庫

| 專案 | URL | 用途 | 最後更新 | ★ | 授權 | 對 civic-lens 用途 |
|---|---|---|---|---|---|---|
| kiang/elections | https://github.com/kiang/elections | （同上）收集全台各層級候選人個人資料 | 2026-09 | 38 | MIT | 候選人資料庫，可能已含政見欄位，需實查 schema |
| rex-chien/taiwan-2020-election-hustings | https://github.com/rex-chien/taiwan-2020-election-hustings | 用文字分析看懂政見發表會 | 2020-01 | 0 | GPL-3.0 | **已停止維護**，政見文字分析方法參考 |
| ronnywang/lagnews | https://github.com/ronnywang/lagnews | LagNews腿新聞（政治人物言行對照類） | 2021-06 | 15 | BSD-3 | **已停止維護**，政見/發言對照呈現方式參考 |

**覆蓋度說明**：g0v 系統性「政治人物 Who's Who」型資料庫（類似 EveryPolitician）在本次搜尋沒有找到現役、活躍的台灣版本；候選人政見兌現追蹤更是明顯缺口，civic-lens 在此方向幾乎需要自建。

### E. 政治獻金／財產申報（監察院陽光法案）

| 專案 | URL | 用途 | 最後更新 | ★ | 授權 | 對 civic-lens 用途 |
|---|---|---|---|---|---|---|
| openfunltd/ardata | https://github.com/openfunltd/ardata | 監察院政治獻金公開查閱平台 | 2025-04 | 0 | BSD-3 | **資料來源／可參考**：openfun 目前維護的政治獻金平台 |
| ctiml/campaign-finance.g0v.ctiml.tw | https://github.com/ctiml/campaign-finance.g0v.ctiml.tw | 政治獻金數位化，人工 OCR | 2025-09 | 37 | 無 | 政治獻金 OCR/資料化流程參考 |
| ronnywang/tw-campaign-finance | https://github.com/ronnywang/tw-campaign-finance | 台灣政治獻金資料 | 2024-03 | 9 | 無 | 資料來源候選 |
| ronnywang/sunshine.cy.gov.tw | https://github.com/ronnywang/sunshine.cy.gov.tw | 監察院陽光法案資料（政治獻金+財產申報） | 2014-12 | 2 | MIT | **已停止維護**，財產申報資料結構參考 |
| g0v/sunshine.cy | https://github.com/g0v/sunshine.cy | 金錢報－公職人員財產申報 | 2025-01 | 6 | CC0-1.0 | **資料來源**：財產申報，g0v 官方 org 下 |
| ronnywang/ardata.cy-2018 | https://github.com/ronnywang/ardata.cy-2018 | 2018年政治獻金申報資料快照 | 2019-08 | 4 | 無 | **已停止維護**，歷史資料 |
| ronnywang/2016-ly-money | https://github.com/ronnywang/2016-ly-money | 2016年立委政治獻金 | 2026-05（fork活動） | 1 | 無 | 歷史資料快照 |
| lackneets/campaign-finance | https://github.com/lackneets/campaign-finance | 政治獻金數位化資料統整&應用 | 2021-07 | 4 | 無 | **已停止維護**，資料應用層參考 |
| fuyei/cf-viz | https://github.com/fuyei/cf-viz | 政治獻金視覺化 | 2019-06 | 3 | 無 | **已停止維護**，視覺化呈現參考 |
| ronnywang/tw-campaign-finance-tools | https://github.com/ronnywang/tw-campaign-finance-tools | 處理政治獻金掃描檔的工具 | 2018-10 | 0 | 無 | **已停止維護**，OCR前處理參考 |

### F. 公司登記／公司關係圖（候選人+配偶+子女董監事）

| 專案 | URL | 用途 | 最後更新 | ★ | 授權 | 對 civic-lens 用途 |
|---|---|---|---|---|---|---|
| openfunltd/twcompany | https://github.com/openfunltd/twcompany | 台灣統一編號資料 | 2026-09 | 176 | 無 | **資料來源**：公司登記/統編主資料庫，最活躍且高星 |
| ronnywang/company-graph | https://github.com/ronnywang/company-graph | company-graph.g0v.ronny.tw 公司關係圖 | 2023-04（程式最後 push） | 67 | 無 | **可 fork**：董監事關係圖產生工具，直接對應需求 |
| ronnywang/fidb-crawler | https://github.com/ronnywang/fidb-crawler | 經濟部工業局工廠資料爬蟲 | 2024-06 | 15 | 無 | 工廠登記資料，公司關係查核輔助 |

### G. 裁判書（法定公開前科）

| 專案 | URL | 用途 | 最後更新 | ★ | 授權 | 對 civic-lens 用途 |
|---|---|---|---|---|---|---|
| aa0101181514/tw-legal-rag | https://github.com/aa0101181514/tw-legal-rag | 台灣法律 MCP 伺服器：2,250萬筆裁判書、行政函釋、憲法法庭裁判 | 2026-09 | 325 | Other | **資料來源**：目前最完整、最活躍的裁判書檢索工具，優先評估 |
| asgard-ai-platform/mcp-tw-judgment | https://github.com/asgard-ai-platform/mcp-tw-judgment | 司法院裁判書系統 MCP server | 2026-04 | 0 | MIT | 裁判書查詢 MCP，輕量替代方案 |
| yuzuEN/JudgementDigest | https://github.com/yuzuEN/JudgementDigest | 爬取、解析、匯出台灣裁判書 | 2026-09 | 3 | MIT | 爬蟲/解析邏輯參考，近期活躍 |
| kong0107/judgment | https://github.com/kong0107/judgment | 中華民國法院裁判書工具 | 2026-04 | 0 | Unlicense | 裁判書處理工具參考 |
| markxp/lawjddl | https://github.com/markxp/lawjddl | 從 law.judicial.gov.tw 下載裁判書的 CLI | 2026-05 | 0 | Other | 下載工具參考 |
| g0v-data/cons.judicial.gov.tw | https://github.com/g0v-data/cons.judicial.gov.tw | 憲法判決資料 | 2026-01 | 0 | 無 | 憲法法庭資料，補齊 tw-legal-rag 未涵蓋部分 |
| samttoo22-MewCat/judgement-scrawler | https://github.com/samttoo22-MewCat/judgement-scrawler | 司法院裁判書系統爬蟲（500筆以上） | 2026-02 | 6 | 無 | 爬蟲邏輯參考 |
| whiskyinsulo/Judicial_Judgements | https://github.com/whiskyinsulo/Judicial_Judgements | Judicial.gov.tw 裁判書開放資料 | 2026-02 | 6 | MIT | 資料格式參考 |
| kiang/bribes_data | https://github.com/kiang/bribes_data | 從裁判書中結構化萃取賄選案件資料 | 2020-01 | 0 | 無 | **已停止維護**，對「候選人前科」極相關的資料萃取方法參考 |
| BuzzAcademy/judicial-unformatted-data | https://github.com/BuzzAcademy/judicial-unformatted-data | 司法院裁判書原始資料 | 2023-12 | 1 | 無 | **已停止維護**，原始資料快照 |
| mt019/fjud-userscript | https://github.com/mt019/fjud-userscript | 快速跳轉司法院裁判書查詢的瀏覽器腳本 | 2026-08 | 0 | MIT | 使用者端輔助工具，非資料來源 |

### H. 政府標案（延伸：候選人相關公司承接標案查核）

| 專案 | URL | 用途 | 最後更新 | ★ | 授權 | 對 civic-lens 用途 |
|---|---|---|---|---|---|---|
| openfunltd/pcc.g0v.ronny.tw | https://github.com/openfunltd/pcc.g0v.ronny.tw | 政府電子採購網標案資料 API | 2026-09 | 38 | 無 | **資料來源**：候選人/配偶關聯公司標案查核 |
| openfunltd/pcc-viewer | https://github.com/openfunltd/pcc-viewer | 標案資料檢視前端 | 2026-07 | 17 | 無 | 標案資料呈現介面參考 |

### I. 國際專案（架構參考，簡短列出）

| 專案 | URL | 用途 | 對 civic-lens 用途 |
|---|---|---|---|
| mySociety TheyWorkForYou | https://www.mysociety.org/theyworkforyou/（原始碼於 mysociety GitHub org） | 英國國會議員發言/投票追蹤先驅專案，20年歷史 | 整體資訊架構（議員頁、發言全文檢索、投票紀錄）標竿參考 |
| Popolo Project / EveryPolitician 資料標準 | https://www.popoloproject.com/ | 政治人物/組織/職位的開放資料標準（JSON Schema） | civic-lens 資料模型（立委/議員/候選人 schema）可直接採用此標準，避免自創欄位 |
| OpenStates | https://github.com/openstates | 美國各州議會資料聚合平台（議員、法案、表決） | 多層級（聯邦/州/市）議會資料聚合的架構參考，對應台灣「立法院+縣市議會」雙層需求 |

---

## 缺口總結（供補齊研究方向參考）

1. **縣市議會出席/質詢/表決/影音**：僅台南有明確觀測站專案，六都及其餘縣市議會幾乎是空白，civic-lens 需自建爬蟲。
2. **政見兌現追蹤 / 政治人物 Who's Who**：無現役、系統性的台灣版 EveryPolitician，需自建或以 Popolo 標準為底新造。
3. **裁判書 → 候選人身份比對**：現有裁判書資料源（tw-legal-rag、mcp-tw-judgment）解決檢索問題，但「裁判書當事人 ↔ 候選人身份確認」的比對邏輯（同名同姓辨識）仍是空白，需自行開發並注意個資與公平性風險。
4. **公司關係圖延伸到候選人配偶/子女**：twcompany + company-graph 提供公司/董監事底層資料，但「候選人家族關係」比對層仍需自建。
