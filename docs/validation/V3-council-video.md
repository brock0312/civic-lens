# V3 驗證：臺北市議會第 14 屆口頭質詢影片

> **結論**：✅ **可做到「議員所屬質詢組」的起點，比 PLAN 預期的好**。`tccvideo.tcc.gov.tw` 背後有不需要 cookie 的 JSON 端點：一次 GET 就能列出全站 5,148 支影片，每支影片另有 `Read`（場次標題、時間、**各質詢組組員名單**、HLS 串流網址）與 `Segment_Read`（**各質詢組的起始秒數**）。影片頁網址 `…/Front/VideoContent/Index?id=<GUID>&num=<組別>` 跨 session、不帶 cookie 也能開，播放器會自動跳到該組的起點（headless Chrome 實測 `currentTime` = 該組起始秒數）。**但 `&num=` 只在分段名稱是「第N組」時有效**（抽測 21/21 成功）；15 支影片（2025-10～2026-08）的分段名稱寫成「第N質詢組」，`GetInPoint` 一律回 0（抽測 6/6），播放器從頭開始，這時要退回場次頁並在我們的頁面寫出「本組約從影片 1:25:13 開始」。另外 `Read.Content` 的組員是**排定表**（延期的組會同時出現在兩天），實際有質詢的組要以 `Segment_Read` 為準。**影片只切到「組」，沒有切到「人」**：單人組可以直接對到個人，多人組只能對到整組的開頭。議會官方 YouTube 頻道存在，但只有 3 支簡介影片，沒有任何質詢影片，不能當來源。
> **推薦 MVP 採用新的一層「(a′) 質詢組深連結」**：每位議員每一次口頭質詢記一筆，連到 `Index?id=…&num=…`（分段名稱為「第N質詢組」時改連 `Index?id=…` 並顯示起始時間），並註明「從該組開始播放；同組有 N 位議員，未細分到個人」。現任有對照的 51 人共 2,921 筆（每人 54–60 筆），其中 2,744 筆可用 `&num=` 直接跳轉。第 14 屆共 **264** 支口頭質詢影片、**953** 個質詢組，全量抓取約 **529** 次請求（每秒 1 次約 **10–12** 分鐘），每日增量 1–10 次。

調查日期：2026-09-28　原始檔：`<scratchpad>/v3/`（不進 repo）
所有請求都帶 `User-Agent: civic-lens-etl/0.1`（`www.tcc.gov.tw` 用 `Mozilla/5.0`，延用 M4 的做法），間隔 ≥ 1 秒。

## 總表

| # | 問題 | 答案 | 狀態 |
|---|---|---|---|
| 1a | tccvideo 怎麼列場次 | `GET /Front/Query/GetList`：不帶 cookie 時一次回傳**全站** 5,148 筆 JSON（2010-12-25 起）；帶查詢 cookie 可依日期、屆次、類別篩選。第 14 屆（2022-12-25 起）993 支，其中大會 413、委員會 580 | ✅ 實測 |
| 1b | 單支影片 URL | `https://tccvideo.tcc.gov.tw/Front/VideoContent/Index?id=<GUID>`，不帶 cookie 可開；加 `&num=<組別>` 會跳到該組起點（分段名稱為「第N組」時有效，「第N質詢組」時無效） | ✅ 實測（含 headless 播放器） |
| 1c | 逐位議員分段 | **沒有**。只有逐「質詢組」的分段與起始秒數（`Segment_Read`、`GetInPoint`）；264 支中 262 支有分段 | ✅ 實測 |
| 1d | JSON 端點 | `GetList`、`Read`、`Segment_Read`、`Videos_Read`、`GetInPoint`，全部 GET、不需 cookie、urllib 可重現 | ✅ 實測 |
| 2 | 議會 YouTube | 頻道 `@臺北市議會-110`（`UCwiE5sxWHSXD5qEBuAhyzkg`，3,270 訂閱）只有 3 支簡介影片；另一個同名頻道 `UCxiZ9VJ7drAV9dZjWLkio2w` 只有 2 支 2014 年的直播。**沒有質詢影片**。議會官網沒有連到任何 YouTube 頻道。YouTube 上的質詢影片都是媒體（台視、TVBS、udn…）的直播存檔，只收市政總質詢，且以市長為主角 | ✅ 實測 |
| 3 | 誰、哪天、哪一組 | 三個來源都拿得到：①tccvideo `Read.Content`（組別、組員、分鐘數，當天就有）；②議會官網「質詢分組表」`Grouping.aspx`（組別、日期、起訖時間、組員，排定表）；③公報 `gaz.tcc.gov.tw` 總質詢／業務質詢（組別、質詢日期、組員、公報原文，**落後數月**） | ✅ 實測 |
| 4 | 三層可行性 | (a) 逐人單支影片：❌ 不存在；**(a′) 質詢組深連結：✅ 推薦**；(b) 當日場次頁：✅；(c) 搜尋頁：⚠️ 搜尋靠 POST＋cookie，無法用單一網址帶條件，只能連首頁 | ✅ 實測 |
| 5 | 量 | 第 14 屆口頭質詢影片 264 支（市政總質詢 72、部門質詢 192），質詢組 953 個，全量 529 次請求 | ✅ 實測（全量跑過一次） |
| 6 | 條款 | 議會著作權聲明：同意任何網站連結，須標示本會名稱；內容可合理使用並註明出處。tccvideo 本身沒有條款頁、沒有 robots.txt（404）。**只連結、不轉存、不嵌入 HLS** | ✅ 實測 |

---

## 1. tccvideo.tcc.gov.tw

### 1.1 列出場次

首頁表單 `POST /Front/Query` 只是把查詢條件寫進 cookie（`js.cookie`：`ConditionType`、`StartDate`、`EndDate`、`VideoType`、`Category`、`MJ`、`MP`、`Keyword`…），再轉到結果頁；結果頁用 `GET /Front/Query/GetList` 取 JSON，**伺服器端讀的是這些 cookie**。

```
$ curl -sS -A "$UA" https://tccvideo.tcc.gov.tw/Front/Query/GetList -o gl0.json      # 不帶 cookie
200  → 5,148 筆，最新 2026/09/24，最早 2010/12/25「第十一屆就職典禮」；Url 不重複 5,148
$ curl -sS -A "$UA" -H 'Cookie: ConditionType=%E6%97%A5%E6%9C%9F; StartDate=2022%2F12%2F25; EndDate=2026%2F09%2F28; VideoType=%E5%A4%A7%E6%9C%83; Category=AL; …' …/Front/Query/GetList
200  → 73 筆（第 14 屆市政總質詢 72 筆，外加 1 筆「第14屆113年03月22日談話會」被歸在 AL 類）
```

一筆 `GetList`：

```json
{"Title":"第14屆第08次定期大會市政總質詢","Date":"2026/09/14 13:20~16:33","ViewCount":"495",
 "Url":"https://tccvideo.tcc.gov.tw/Front/VideoContent/Index?id=e989cdf2-2e02-49a7-8bef-6420f1e37d70",
 "Type":"大會","StartTime":"2026-09-14T13:20:00"}
```

類別代碼來自 `POST /Shared/DropDownList/GenCategory_Read`（要帶 `Content-Length`，空 body 即可，否則 411）：`AL` 市政總質詢、`QuesCI` 民政、`QuesEC` 財政建設、`QuesED` 教育、`QuesTR` 交通、`QuesPO` 警政衛生、`QuesCO` 工務、`Policy` 施政報告、`Prog` 市長專案報告、`Gen` 大會、`Talk` 談話會。委員會代碼來自 `Exams_Read`（`ExamCI`…`ExamProc`）。

**ETL 建議**：不帶 cookie 打一次 `GetList`，本地用 `StartTime >= 2022-12-25`、`Type == 大會`、標題含「市政總質詢」或「部門質詢」篩選。第 14 屆標題分布（大會 413 支）：市政總質詢 72、民政／財政建設／教育／交通／警政衛生／工務部門質詢各 32、其餘是一般大會、專案報告、成立大會、就職典禮、談話會。
風險：「不帶 cookie 回傳全部」是觀察到的行為，不是文件承諾。若日後改成預設只回近一個月，改帶 cookie 依類別查即可（已實測可行）。

### 1.2 單支影片頁與穩定性

```
$ curl -sS -A "$UA" -D - 'https://tccvideo.tcc.gov.tw/Front/VideoContent/Index?id=e989cdf2-2e02-49a7-8bef-6420f1e37d70'
HTTP/2 200   （沒有 Set-Cookie；頁面把 id 放進 VideoContentComponent.main(...) 後用 JS 取資料）
$ curl … 'Index?id=00000000-0000-0000-0000-000000000001'  → 302（不存在的 id 會被轉走）
$ curl … 'Read?id=00000000-0000-0000-0000-000000000001'   → 200，所有欄位 null
```

- id 是 GUID，出現在 `GetList`、首頁 `GetNewVideo`、`Videos_Read` 三個地方，值一致。
- 不帶 cookie、換 session 都能開（本次所有請求都沒帶 cookie）。
- 失效偵測：`Read?id=` 的 `Title` 變 null，或 `Index` 回 302。

### 1.3 分段、章節、時間碼

每支大會影片有「影片索引」分頁，資料來自 `Segment_Read`；**一個分段＝一個質詢組**。

```
$ curl -sS -A "$UA" 'https://tccvideo.tcc.gov.tw/Front/VideoContent/Read?id=36f899ab-94ec-4102-bdd5-a55fa89cdd22'
{"Title":"第14屆第08次定期大會市政總質詢","MeetTime":"2026/09/11 13:20~16:36",
 "Content":"第13質詢組：徐立信<br/>計1位時間40分鐘 <br/>第14質詢組：洪健益,劉耀仁<br/>計2位時間80分鐘 <br/>第15質詢組：侯漢廷<br/>計1位時間40分鐘 <br/>",
 "ProxyUrls":[{"src":"https://tccwowza.tcc.gov.tw:1935/vod/mp4:definst/1408定期大會/1408定期大會20260911132006_480_20260911163709.mp4/playlist.m3u8","label":"480p"}, {…720p}],
 "Type":"大會", …}
$ curl … 'Segment_Read?id=36f899ab-…'
[{"SegmentId":"…","VideoId":"36f899ab-…","Name":"第13組：徐立信","TimeText":"13:31:47","VideoTime":701.44,"IsOldQues":false,"Url":null},
 {"Name":"第14組：洪健益,劉耀仁","TimeText":"14:13:41","VideoTime":3215.07, …},
 {"Name":"第15組：侯漢廷","TimeText":"15:55:43","VideoTime":9337.65, …}]
$ curl … 'GetInPoint?id=36f899ab-…&quesNum=14'   → 3215.072821
$ curl … 'GetInPoint?id=36f899ab-…&quesNum=99'   → 0（不存在的組別回 0）
```

抽樣（部門質詢一天 3–4 組，市政總質詢一天 1–3 組）：

| 日期 | 場次 | 分段 |
|---|---|---|
| 2023-05-29 | 14-01 市政總質詢 | 第1組 4 人 @633s、第2組 3 人 @11498s |
| 2023-05-08 | 14-01 交通部門質詢 | 第1–4 組，@617/5467/10298/15161s |
| 2025-10-16 | 14-06 工務部門質詢 | 第5–8 組（第6組 5 人） |
| 2026-08-28 | 14-08 民政部門質詢 | 第14–16 組 |
| 2020-11-19 | 13-04 市政總質詢第21組 | 無分段（第 13 屆一組一支影片，`IsOldQues` 舊制） |

**深連結**：`Index?id=<GUID>&num=<組別>` 會把 `num` 放進頁面設定，播放器載入後呼叫 `GetInPoint` 並 `setCurrentTime`。以 headless Chrome（Playwright，全新 context、無 cookie）打開 `Index?id=36f899ab-…&num=14`，8 秒後 `video.currentTime = 3215.072821`、`readyState = 4`，與第 14 組起始秒數相同（自動播放被瀏覽器擋下，使用者按播放即從該組開始）。網路請求依序為 `Read` → `Videos_Read` → HLS `playlist.m3u8` → `Segment_Read` → `GetInPoint?quesNum=14` → `chunklist` → `.ts`，沒有其他隱藏端點。

**`&num=` 的失效條件**：`GetInPoint` 似乎用分段名稱「第N組」比對組別。全量 953 個分段中 895 個叫「第N組」、58 個（15 支影片，2025-10-14～2026-08-11）叫「第N質詢組」。

```
GetInPoint 抽測（對照 Segment_Read 的 VideoTime）：
  「第N組」   ：36f899ab num=13/14/15、367a01bd num=14、77105f63 num=2、d10d4fe7 num=2、747275ea num=5、7cd3e8b4 num=4、
               e989cdf2 num=16、1bbe22db num=6，另隨機 12 個 → 21/21 完全相同
  「第N質詢組」：de0ca551（07/28）num=4/5/7/10、a1b99608（08/11）num=7，另隨機 4 個 → 0/6，全部回 0
```

所以 ETL 規則是：分段名稱符合 `^第\d+組` 才加 `&num=`，否則只連場次頁，並用 `VideoTime` 在我們的頁面顯示「本組約從影片 h:mm:ss 開始」。這條規則是從觀察歸納的；ETL 也可以每組多打一次 `GetInPoint` 確認 > 0（多約 950 次請求）。

**排定 vs 實際**：`Read.Content` 是排定的分組（與議會「質詢分組表」相同），`Segment_Read` 才是實際有質詢的組。全量比對只有 1 支不一致，但正好說明差異：

```
2026/08/06 交通部門質詢  Content：第9、10、11、12、13 組   Segment：第9、11、12、13 組
2026/08/07 交通部門質詢  Content：第14、15、16、10 組     Segment：第14、15、16、10 組 @13300s（徐立信延到隔天）
```

另外有 23 組同時出現在兩支影片，大多是跨日續質詢，例如市政總質詢第 4 組 2026-09-01 的 Content 寫「計5位時間100分鐘 未完，尚餘 100 分鐘」，09-03 再從頭列一次，兩天都有分段。兩天都算一次質詢，fact 各記一筆。

**沒有逐位議員的時間碼**：多人組內各議員的起點，tccvideo 沒提供。質詢分組表有「每位議員 N 分鐘」，但實際發言順序與時間會變動（組內可互相讓時間），用平均切割會切錯，不建議。

### 1.4 JSON 端點一覽（全部不需 cookie）

| 端點 | 方法 | 用途 |
|---|---|---|
| `/Front/Query/GetList` | GET | 影片清單（不帶 cookie＝全站） |
| `/Front/VideoContent/Read?id=` | GET | 場次標題、時間、組別與組員（`Content`，HTML 字串）、HLS 網址 |
| `/Front/VideoContent/Segment_Read?id=` | GET | 各組起始時間（`VideoTime` 秒） |
| `/Front/VideoContent/GetInPoint?id=&quesNum=` | GET | 單一組的起始秒數 |
| `/Front/VideoContent/Videos_Read?id=` | GET | 同類的其他 5 支影片 |
| `/Front/Home/GetNewVideo` | GET | 首頁最新 4 支 |
| `/Front/Home/GetAgendaLive`、`GetExamLive` | GET | 今日直播狀態 |
| `/Shared/DropDownList/GenCategory_Read`、`Exams_Read` | POST（空 body） | 類別代碼 |

以上都用 Python `urllib`（`samples.json`、`crawl14.json`）或 curl 重現過。

## 2. 議會官方 YouTube 頻道

```
$ yt-dlp --flat-playlist 'https://www.youtube.com/results?search_query=臺北市議會&sp=EgIQAg%3D%3D'   # 頻道搜尋
臺北市議會 | UCwiE5sxWHSXD5qEBuAhyzkg | 3270 訂閱
臺北市議會 | UCxiZ9VJ7drAV9dZjWLkio2w | 5 訂閱
（其餘為議員個人頻道與「臺北市議會演哪齣？」等非官方頻道）
$ yt-dlp --flat-playlist https://www.youtube.com/channel/UCwiE5sxWHSXD5qEBuAhyzkg/videos
cPe-qYFb8P0 825s 第14屆臺北市議會簡介（2023-12-29 上傳）
VH10h86lZ2Y 850s 第13屆臺北市議會簡介
IvAgckCnze8 261s 第13屆臺北市議會圖書館簡介
…/streams → This channel does not have a streams tab；…/playlists → 沒有 playlists 分頁
$ curl -sS 'https://www.youtube.com/feeds/videos.xml?channel_id=UCwiE5sxWHSXD5qEBuAhyzkg'  → 200，3 個 <entry>
$ yt-dlp …/channel/UCxiZ9VJ7drAV9dZjWLkio2w/streams
hQ3q1JXOv44 9529s 臺北市議會第12屆議員宣誓就職典禮；WlYX_O0I0Ng 141s 20140324
```

- `UCwiE5sxWHSXD5qEBuAhyzkg`（handle `@臺北市議會-110`）的簡介文字是議會沿革，標籤「臺北市議會」，看起來是議會自己的頻道，但**議會官網首頁、tccvideo、live.tcc.gov.tw 都沒有連到任何 YouTube 頻道**（grep `youtube` 零筆），官方身分只能推定。
- 不論官方與否，**兩個頻道都沒有質詢影片**。RSS 只回 3 筆，本來就只有 3 支。
- tccvideo 首頁設定有 `"liveUseYoutube":true`，但 `liveUrl` 是空字串；`GetAgendaLive` 今天回「今日無議程」。直播時是否嵌 YouTube（嵌哪個頻道）**未實測**，需在開會日再看；即使有，也是直播，不是可逐場查的存檔。
- YouTube 上搜「臺北市議會 市政總質詢」前 15 筆全是媒體頻道（台視、TVBS、udn、民視、年代、壹電視…）的直播存檔，只涵蓋市政總質詢、以市長為主角、標題沒有組別與議員，**不採用**。
- YouTube Data API 需要 API key（Google Cloud 專案＋配額），本次未申請；以目前結果看也沒有必要。

## 3. 口頭質詢的「誰、哪天、哪一組」

| 來源 | 取得方式 | 欄位 | 時效 | 狀態 |
|---|---|---|---|---|
| ① tccvideo `Read.Content` | GET，無 cookie | 屆次會次（標題）、日期時間、組別、組員（逗號分隔）、人數、分鐘數；`Segment_Read` 另有起始秒數 | 影片上架即有（最新 2026-09-14） | ✅ |
| ② 議會官網「質詢分組表」`https://www.tcc.gov.tw/Grouping.aspx?n=13517` | 本會期：GET `&qtype=市政總質詢`／`民政部門`…；歷次：ASP.NET POST（`__VIEWSTATE`＋`CouncilAgenda_MeetExpire=14`、`CouncilAgenda_MeetSession=01`、`CouncilAgenda_QuesType=市政總質詢`） | 屆次會次、質詢性質、組別、日期（月日＋星期）、排定起訖時間、組員、人數、分鐘數、備註（登記人數、每人分鐘） | 會期開始前就排定 | ✅ |
| ③ 公報 `gaz.tcc.gov.tw` 總質詢／業務質詢 | GET＋cookie（見 M4） | 卷期、屆會次、組別、質詢日期、質詢對象、組員、分鐘數、速記錄全文、公報原文連結 | 落後數月（第 14 屆總質詢最新到 114-12-15，第 6 次定期大會） | ✅ |
| ④ 議事日程表（`ws.tcc.gov.tw/Download.ashx?...` .doc） | 下載 Word 檔 | 日期 → 當天議程（「質詢及答覆　財政建設部門」） | 會期前 | ✅ 但**沒有組別與組員** |

實測：

```
$ curl -sS -A 'Mozilla/5.0' 'https://www.tcc.gov.tw/Grouping.aspx?n=13517'        # 預設＝本會期民政部門
臺北市議會第14屆第08次定期大會 民政部門
14 08月28日(週五) 13:30 ~ 14:42 (72分) 闕枚莎 陳炳甫 吳志剛 徐弘庭 共 4 位 時間 72 分鐘
15 08月28日(週五) 14:43 ~ 15:19 (36分) 顏若芳 林延鳳 共 2 位 時間 36 分鐘
16 08月28日(週五) 15:30 ~ 16:42 (72分) 黃瀞瑩 陳宥丞 林珍羽 張志豪 共 4 位 時間 72 分鐘
備註 一、登記質詢議員共51人。二、…實際詢答時間﹕每位議員18分鐘。
$ python3 (POST 表單，14 屆 01 次 市政總質詢)  → 200
1 05月29日(週一) 13:30 ~ 16:10 (160分) 黃瀞瑩 陳宥丞 林珍羽 張志豪 共 4 位
2 05月29日(週一) 16:30 ~ 18:30 (120分) 顏若芳 林延鳳 趙怡翔 共 3 位 …
$ curl -sS -c jar -b jar 'https://gaz.tcc.gov.tw/search/gaz/gazSubCate/總質詢/result.html?sort=desc&sortField=date&pageSize=40&cst=S&se=14'
性質 facet：總質詢 107、業務質詢 610、速記錄 74 …
「市政總質詢第 14 組 質詢日期：中華民國 114 年 12 月 12 日 質詢對象：蔣市長萬安 質詢議員：侯漢廷 計 1 位 時間 40 分鐘」
```

三者一致：2026-08-28 民政部門第 14–16 組、2023-05-29 市政總質詢第 1–2 組，tccvideo 與分組表的組員完全相同。**ETL 只需要 ① tccvideo**：組員名單同時寫在分段名稱裡，不必跨來源比對日期與組別。注意 ① 的 `Content` 與 ② 都是**排定表**，延期的組會列在原訂日期；實際質詢日要看 `Segment_Read`（見 §1.3）。②可當交叉核對；③要連速記錄原文時再用。

## 4. 三層做法的可行性

| 層 | 內容 | 可行性 | 說明 |
|---|---|---|---|
| (a) | 每筆質詢附「該議員」單支影片 | ❌ | 第 14 屆沒有逐人影片，也沒有逐人時間碼（第 13 屆以前是一組一支，也不是一人一支） |
| **(a′)** | **每位議員每次口頭質詢，連到所屬質詢組的起點** `Index?id=…&num=…` | ✅ **推薦** | 單人組等於個人層級；多人組註明「同組 N 位議員，從本組開始播放」。2,921 筆中 2,744 筆（94%）可直接跳轉，其餘退回 (b)＋顯示起始時間 |
| (b) | 附當日場次頁 `Index?id=…`，註明「影片未細分到議員」 | ✅ | 就是 (a′) 拿掉 `&num=`；可當 (a′) 的降級（`num` 失效時） |
| (c) | 附 tccvideo 搜尋頁＋日期與會議名稱 | ⚠️ | 搜尋是 POST 表單＋cookie，沒有能帶條件的網址，只能連首頁 `https://tccvideo.tcc.gov.tw/` 讓使用者自己查。是 PLAN 說的「一定可行」，但體驗最差 |

**推薦 (a′)，實作量約 0.5–1 人日**（新增 `etl/sources/tcc_videos.py` 一支，約 100–150 行＋測試）：

1. `GET GetList`（1 次）→ 篩第 14 屆口頭質詢影片。
2. 每支影片 `GET Read` + `GET Segment_Read`（2 次），DB 已有的影片跳過。
3. **以 `Segment_Read` 為準**：分段 `Name` 用 `^第(\d+)(質詢)?組：(.+)$` 拆出組別與組員（逗號分隔，要 strip），`VideoTime` 是起始秒數。`Read.Content` 的正則 `第(\d+)質詢組：([^<]+)<br/>計(\d+)位時間(\d+)分鐘` 只用在沒有分段的影片（目前 2 支），並把該筆標成「排定名單」。組員以 `identity.csv`（`source=tcc14`，用姓名對照）換 `person_id`；對不到的名字（已離職議員）跳過，與 M4 一致。
4. 每位議員×每個分段寫一筆 fact。分段名稱是「第N組」就用 `&num=<組別>`；「第N質詢組」或沒有分段就退回 (b)。
5. 測試：`Segment_Read` 兩種名稱格式各一份 fixture、無分段的 `Read` 一份，驗證拆組、`&num` 規則、退回 (b)。

前端只要在人物卡的質詢列表多一種項目（「口頭質詢」＋播放連結＋「同組 N 位」說明），不必改架構。

## 5. 量與禮貌

全量跑過一次（`crawl.py`，每次請求間隔 1.1 秒）：

| 項目 | 數字 |
|---|---|
| 第 14 屆口頭質詢影片 | 264 支（市政總質詢 72、部門質詢 192；2023-04-17～2026-09-14），請求錯誤 0，每支都有 HLS 網址 |
| 有分段的影片 | 262 支；沒有分段的 2 支：2023-11-06 警政衛生部門質詢、2025-11-13 交通部門質詢（只能用 Content 的排定名單，退回 (b)） |
| 排定的組（Content） | 961 個（938 個不同的「會次×類別×組別」，其餘 23 個是跨日續質詢或延期） |
| 實際分段（Segment） | 953 個：「第N組」895、「第N質詢組」58 |
| 組的人數 | 1 人 92 組、2 人 203、3 人 226、4 人 292、5 人 148（以 Content 計） |
| 出現的議員 | 58 人；identity.csv 有對照的 51 人全都出現；沒有對照的 7 人都是已離職議員（吳沛憶、徐巧芯、李彥秀、王世堅、許家蓓、趙怡翔、陳政忠）；identity 中沒出現的 2 人是議長戴錫欽、副議長葉林傳（主持會議，不質詢） |
| 可寫入的 fact（以 Segment 計） | 2,921 筆，每人 54–60 筆；其中 2,744 筆可用 `&num=` 直接跳轉，91 筆是單人組 |

實際耗時：第一次回補的驗證抓取（每次請求間隔 1.1 秒）從 18:39 左右跑到 18:51，約 12 分鐘。

- **第一次回補**：`GetList` 1 次＋ 264 × 2 次 ≈ 529 次，間隔 1 秒約 10–12 分鐘。
- **每日增量**：`GetList` 1 次，比對 DB 沒有的 GUID，每支新影片 2 次；質詢期間一天最多 1–2 支，平常 0 支。
- 第 14 屆會期只剩第 8 次定期大會（115-07-15～115-10-02）尾聲；選前不會再有新的口頭質詢，回補一次後增量幾乎為零。
- 不要抓 HLS：本次只為確認影片可播，抓了 2 支影片的 `playlist.m3u8`＋`chunklist`（共 4 次），得到片長 18,945 秒與 11,754 秒，ETL 不需要。

## 6. 條款

`https://www.tcc.gov.tw/cp.aspx?n=13900`（著作權聲明，更新日期 110-09-28）：

> 一、著作權保護 1. 臺北市議會全球資訊網…上刊載之所有內容，除依著作權法第9條規定不得為著作權標的者外，均受著作權法之保護。2. 本會網站之內容，得依著作權法規定為合理使用；引用時，請註明出處。
> 二、本會網站之連結 1. 除連結將誤導使用或有誤導使用之虞者外，本會同意任何網站得連結至本會網站；連結時，並請標示本會名稱。

- tccvideo 頁面沒有自己的著作權或使用條款連結（grep「著作權／版權／隱私」零筆），頁尾只有「Copyright © 2020 Taipei City Council」。視為適用議會全球資訊網的聲明（同一機關；gaz 的聲明文字也相同，見 M4 §6）。
- `tccvideo.tcc.gov.tw/robots.txt` 404，沒有明文禁止自動化存取。
- **我們的做法**：只存詮釋資料（場次標題、日期、組別、組員、起始秒數、影片頁網址），**只連結 tccvideo 影片頁，不轉存影片、不在我們的頁面嵌入 HLS 串流**（`tccwowza.tcc.gov.tw:1935` 是議會的串流主機，嵌入會吃對方頻寬，聲明也只談連結）。連結旁標示「影片來源：臺北市議會議事影音」。
- 「多人組」連結要註明從該組開始、同組還有誰，避免被解讀成「這段影片是某議員個人的質詢」——這是聲明裡「連結將誤導使用」的例外條件，要避開。

## 7. 未解問題

1. 質詢組內各議員的個別起點：tccvideo 沒提供，只能等議會或靠速記錄全文推（不做）。
1b. `&num=` 對「第N質詢組」分段無效，原因是推論（名稱比對），不是文件記載；議會若修正或改名，規則要跟著調整。ETL 用 `GetInPoint` 抽驗即可發現。
1c. 沒有分段的 2 支影片只能用排定名單，無法確認組員當天確實有質詢。
2. `GetList` 不帶 cookie 回全站是觀察到的行為，不是承諾；ETL 要檢查筆數，驟減時改帶 cookie 分類查。
3. 施政報告質詢（市長施政報告與質詢及答覆）、專案報告質詢也是口頭質詢，但 tccvideo `Read.Content` 是否也有組別名單**未實測**。PLAN 只要求總質詢與部門質詢，MVP 不收。
4. 直播是否用 YouTube 嵌入、嵌哪個頻道：今天無議程，**未實測**。
5. `UCwiE5sxWHSXD5qEBuAhyzkg` 是否為議會官方：議會網站沒有連過去，只能推定；反正沒有質詢影片，不影響結論。
