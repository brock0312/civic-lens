# V12 普查：其他 21 個縣市議會的資料系統

> **狀態：階段性收尾（2026-09-30 暫停），尚未完成。** 目前只查了五都中的 4 個（高雄、臺中、臺南較深，桃園只看了首頁），新北連不上，16 個縣市還沒開始。總表中沒有實測的格子一律標「未實測」。
> **目前看到的重點**：
> - **高雄**是目前最好打通的議會：影片有逐位議員的 in/out 秒數（JSON），出缺勤有逐次會議、逐人的統計表，市政總質詢是一人一個時段。
> - **臺中**的影片是逐位議員的剪輯，議事錄是逐句 JSON，而且每句都標了發言人。但書面質詢系統沒找到，出缺勤也還沒找到。
> - **臺南**的議事影音可以依議員篩選，影片是逐人的 YouTube 影片。
> - 書面質詢還沒有任何一個議會打通到臺北 gaz 那樣的程度。

調查日期：2026-09-30　原始檔：`<scratchpad>/v12/`（不進 repo；`log.tsv` 記了每次請求的時間、HTTP 狀態、大小與網址，共 88 筆）
所有請求都是序列發送，每次之前先等 1.1 秒（`f.sh`、`sess.py`）。UA 用 `Mozilla/5.0 (Macintosh) civic-lens-survey/0.1`。沒有抓影片串流。

比較基準是臺北（M4、V3）：
- 名錄：一頁 HTML，個人頁有生日。
- 書面質詢：gaz 可用 GET 依議員查，每份有穩定的 viewer URL。
- 影片：tccvideo JSON，可以深連結到質詢組起點，但沒有細分到個人。
- 出缺勤：V4 驗證中。

---

## 進度（2026-09-30 暫停）

| 狀態 | 議會 | 說明 |
|---|---|---|
| **已調查（主要項目有實測）** | 高雄市議會 | 名錄、質詢、影片、出缺勤、著作權都實測過；只剩 YouTube 沒查，書面質詢也還沒打到逐筆 |
| **部分調查** | 臺中市議會 | 名錄、影片、議事錄 API 實測過；書面質詢和出缺勤沒找到；著作權聲明頁沒有讀 |
| **部分調查** | 臺南市議會 | 名錄、影片（依議員篩選）實測過；書面質詢、出缺勤（議事錄 PDF 內容）、YouTube 頻道內容都沒實測 |
| **部分調查（只到首頁）** | 桃園市議會 | 只從首頁抓出各系統的網址，都還沒打開 |
| **連線失敗** | 新北市議會 | `www.ntp.gov.tw` 的 TCP 與 TLS 握手成功，但伺服器不回 HTTP 回應，3 次都逾時；`vod.ntp.gov.tw` 只回 IIS 預設頁 |
| **未調查** | 基隆市、新竹市、新竹縣、苗栗縣、彰化縣、南投縣、雲林縣、嘉義市、嘉義縣、屏東縣、宜蘭縣、花蓮縣、臺東縣、澎湖縣、金門縣、連江縣（16 個） | 完全沒發請求 |

## 總表（21 議會 × 5 項）

圖例：
- ✅：能用程式穩定取得，已實測。
- ⚠️：資料存在但有限制（需要 POST 或 ViewState、只有 PDF、只到整組、沒打到逐筆等），已實測。
- ❌：實測後判斷沒有，或沒找到。
- 未實測：還沒查。

| 議會 | 1 名錄 | 2 書面質詢 | 3 口頭質詢影片 | 4 出缺勤 | 5 著作權／robots |
|---|---|---|---|---|---|
| 新北市 | 未實測（站台無回應） | 未實測 | 未實測 | 未實測 | 未實測 |
| 桃園市 | 未實測（只知網址） | 未實測 | 未實測（只知網址） | 未實測（只知議事錄網址） | 未實測（只知聲明頁網址） |
| 臺中市 | ✅ 有黨籍，無生日 | ❌ 沒找到書面質詢系統（口頭質詢逐句議事錄 ✅） | ✅ 逐位議員剪輯 | 未實測（附錄沒有統計表） | ⚠️ VOD 頁尾寫「未經授權不得轉載」；robots 404 或空白 |
| 臺南市 | ✅ 有黨籍，無生日（抽 1 人） | 未實測 | ✅ 可依議員篩選，逐人 YouTube 影片 | 未實測（議事錄 PDF 有穩定網址） | ⚠️ 影音有轉錄責任聲明；沒有 robots（轉到 blank.asp） |
| 高雄市 | ✅ 有黨籍，無生日 | ⚠️ 公報有「議員質詢書面答復」類別，但沒打到逐筆 | ✅ 逐位議員影片，附 in/out 秒數 | ✅ 逐次會議、逐人的出席統計表（PDF） | ⚠️ 限個人、非商業使用；robots 404 |
| 基隆市 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 新竹市 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 新竹縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 苗栗縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 彰化縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 南投縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 雲林縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 嘉義市 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 嘉義縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 屏東縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 宜蘭縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 花蓮縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 臺東縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 澎湖縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 金門縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |
| 連江縣 | 未實測 | 未實測 | 未實測 | 未實測 | 未實測 |

議會官方 YouTube 頻道：五個都還沒用 yt-dlp 實測。臺南官網首頁連到 `UCdA-WnlDKDfJol0SJhsf63g`，議事影音頁也直接嵌這些影片，所以臺南的頻道可以認定是官方的，但頻道內容本身還沒查。

## 平台分組（初步，只根據 4 個議會）

目前**沒有發現兩個議會共用同一套議事系統**。已看到的系統特徵：

| 特徵 | 議會 | 證據 |
|---|---|---|
| `cp.aspx?n=`、`News_Content.aspx?n=&sms=&s=` 形式的全球資訊網 CMS | 高雄（`www.kcc.gov.tw`）、臺北（`www.tcc.gov.tw/cp.aspx?n=13898`，見 M4） | 網址樣式相同，推測是同一系列的政府網站 CMS；**廠商沒有確認**。這套只管全球資訊網，議事系統兩邊不同（臺北是 gaz／tccvideo，高雄是 cissearch／ivod） |
| ASP.NET WebForms 議事查詢（`__VIEWSTATE`、`__doPostBack`） | 高雄 `cissearch.kcc.gov.tw`、桃園 `www.tycc.gov.tw/TC/*.aspx`（首頁看得到 ViewState） | 只是技術相同，沒有證據顯示是同一家廠商 |
| 古典 ASP＋iframe | 臺中 `www.tccc.gov.tw/main.asp?uno=`（內容放在 `wb_*.asp` iframe）、臺中 `vod.tccc.gov.tw`（頁尾載入 `top-one.com.tw/counter` 計數器）、臺南 `www.tncc.gov.tw/*.asp?orcaid=<GUID>` | 臺中與臺南的網址樣式不同 |
| Nuxt 3＋PrimeVue SPA，後面是 `/api/*` JSON | 臺中 `yishi.tccc.gov.tw` | `__NUXT_DATA__`、`/assets/entry-*.js` |
| Vue 2 SPA，後面是 `/cms/public/api/*` JSON | 高雄 `ivod.kcc.gov.tw` | `static/js/app.*.js`，`apiURL=location.host+"/cms/public/api"` |
| YouTube 嵌入 | 臺南議事影音 | `youtube.com/embed/<id>` |

**分組結論要等 16 縣市普查完才能下**。縣市議會常見的共用廠商議事系統，這次還沒看到樣本。

---

## 高雄市議會（已調查）

### 1. 名錄 ✅

```
$ f.sh 'https://www.kcc.gov.tw/Member_List3.aspx?n=39&sms=9028'        → 200 147947 B
  15 個選區區塊（<h4>第 <span>01</span> 選區</h4>＋行政區清單），不重複的 msn 共 65 個（應選 65 席）
  <a href="MemberInfo_New.aspx?n=39&sms=9028&msn=2171" title="林富寶(另開視窗)">
$ f.sh 'https://www.kcc.gov.tw/MemberInfo_New.aspx?n=39&sms=9028&msn=2171'  → 200
  「政黨： 民主進步黨 聯絡電話：… 學歷：… 經歷：…」；沒有「出生」或「生日」
$ f.sh https://ivod.kcc.gov.tw/cms/public/api/getMembers                  → 200 application/json，64 筆
  {"gid":"80","title":"邱俊憲議員","regionName":"第05選區","politicalName":"民主進步黨",…}
```

- 選區、黨籍、個人頁都有，**沒有生日**。
- iVOD 的 `getMembers` 是 JSON 名錄（64 筆，比 65 席少 1 筆，原因沒查）。
- 議事系統裡的議員編號是 `0704055` 這種格式（第 4 屆＋流水號），出現在市政總質詢表的 `hidCouncilorFullName`。

### 2. 書面質詢 ⚠️（沒打到逐筆）；口頭質詢文字紀錄 ✅

系統是 `cissearch.kcc.gov.tw`，高雄市議會的「議事資訊整合查詢系統」，用 ASP.NET WebForms 寫成。

- **書面質詢**：
  - 首頁「質詢資料 → 書面質詢」的連結是 `BulletinDraft/Default.aspx?bulletintypecode=BD97798A6018A8FD&…`，GET 回來是「尚無任何資料!」。
  - 在譯文稿庫用 POST 查類別 `27 議員質詢書面答復` 和 `07 議員質詢事項答復`，也都是 0 筆。
  - 公報庫（`Bulletin/Default.aspx`）的「資料分類」有「議員質詢書面答復」，所以書面質詢應該收在公報裡，但**還沒查到逐筆清單**。
  - 議事錄內文可以看到「以上兩位議員採書面質詢，請各位局處收到質詢內容後，7 天內函復議員」，表示高雄的書面質詢是當場改採書面。
- **口頭質詢（逐人）**：公報議事錄是**依議員切段**，例如「民政部門業務質詢及答復（邱俊憲）」。每段有穩定網址，不需要 cookie 就能開：

```
$ sess.py POST Bulletin/Default.aspx（ddlSession=0704，txtKeyword="書面質詢 黃捷"）→ 200，轉到 Scan3.aspx?type=1
  <a href="View.aspx?scan=1&BulletinSN=243386&pages=6359#pdfStart">民政部門業務質詢及答復─第4屆第5次定期大會第15次會議</a>
  【議事錄】第4屆第5次定期大會 各部門業務質詢及答復 卷期：第45卷第3期 起始頁次P.6359 … 民政部門業務質詢及答復（邱俊憲）
$ f.sh 'https://cissearch.kcc.gov.tw/System/Bulletin/View.aspx?scan=1&BulletinSN=243386&pages=6359'   （不帶 cookie）→ 200
  <iframe src='Pdfview.aspx?file=~/Upload/Attachment/公報資料/高雄市議會/45卷/3期/45卷3期06323起頁06410迄頁.pdf&page=37'>
```

- **譯文稿**：`BulletinDraft/Default.aspx` GET 會列出最新 10 筆，全部 665 筆，共 67 頁。每筆有日期、類別、名稱、**質詢者名單**，附件是穩定的 GET 網址：
  - 例：`/Common/FileDownload.ashx?path=/Upload/Attachment/BulletinDraft/6256/&filename=<uuid>.pdf&filerename=…`
  - 市政總質詢的譯文稿名稱還會寫頁碼，例如「黃捷議員p34」。
  - 用 POST 選 `ddlCouncilor=黃捷`，回傳 34 筆。
- **市政總質詢是一人一個時段**：`MunicipalQuestion/Default.aspx` 列出第 8 次定期大會的時段，例如「115/09/30 9:00~9:50 李順進、10:00~10:50 湯詠瑜 …」，每格 50 分鐘、一位議員。這和臺北「整組 4 人」不同。

### 3. 口頭質詢影片 ✅（逐位議員，附秒數）

`ivod.kcc.gov.tw` 是 Vue SPA，API 的根網址是 `/cms/public/api`。以下都是 GET、不帶 cookie：

```
$ f.sh https://ivod.kcc.gov.tw/cms/public/api/getConvertVideoList/1/20            → 200 JSON（最新 20 支）
$ f.sh https://ivod.kcc.gov.tw/cms/public/api/getConvertVideoMemberList/80/1/12   → 200 JSON
  {"videoQuestion":[{"videoId":"19316","title":"115-09-21 14:29:59 第4屆第8次定期會 交通部門業務報告與質詢",
     "videoLength":"00:53:07","source":"202609KCC0408R1150921142959VIDEOmp4","ownerName":"邱俊憲議員"}, …12 筆],
   "videoActivity":[],"videoChoice":[],"videoTop":{…}}
$ f.sh https://ivod.kcc.gov.tw/cms/public/api/getConvertVideoData/80/202609KCC0408R1150921142959VIDEOmp4 → 200 JSON
  "mark_list":[{"convert_video_id":"19316","in":"927","out":"1925","position":"議員","name":"邱俊憲"},
               {"convert_video_id":"19316","in":"1929","out":"2033","position":"議員","name":"邱俊憲"}]
$ f.sh https://ivod.kcc.gov.tw/watch/80/202609KCC0408R1150921142959VIDEOmp4      → 200（SPA 外殼 550 B）
```

- 每位議員有自己的 `videoQuestion` 清單，影片的 `mark_list` 給**該議員發言的 in/out 秒數**。這比臺北 V3 的「質詢組起點」細，可以做到逐人。
- 影片頁網址是 `https://ivod.kcc.gov.tw/watch/<gid>/<source>`（SPA 路由 `/watch/:gid/:source`）。**播放器會不會自動跳到 in 點沒有實測**（要用 headless 瀏覽器，做法同 V3）。
- 其他端點（從 bundle 取出，**沒有實測**）：`getConvertVideoSearch`、`getConvertVideoCateList`、`getMeetingList/<id>`、`getSearchSpeakers`。
- YouTube：未實測。

### 4. 出缺勤 ✅（逐次會議、逐人）

公報附錄有「議員出席情形統計表」，第 4 屆每個會期一份：

```
$ sess.py POST Bulletin/Default.aspx（ddlSession=0704，txtKeyword=出席情形統計表）→ 200，17 筆：
  第4屆成立大會、第1–10次臨時會、第1–6次定期大會 議員出席情形統計表（還沒有第 7、8 次定期大會）
  例：View.aspx?scan=1&BulletinSN=243650&pages=16714,16715
$ f.sh '…/Upload/Attachment/公報資料/高雄市議會/46卷/5期/46卷5期16714起頁16715迄頁.pdf'  → 200 application/pdf 389259 B
$ pdftotext -layout → 「十八、第 4 屆第 9 次臨時會議員出席情形統計表」
  直行姓名（康裕成、曾俊傑、林富寶…），每次會議一列 ○／△，
  合計列有出席、請假、病假、公假…（例：白喬茵 出席 1、請假 6）
```

- PDF 有文字層，但姓名是**直排**（一欄一人），解析時要依欄位位置對齊。這不難，只是要寫專用的解析程式。
- 最新兩個定期大會（第 7、8 次）的統計表還沒刊出。公報大約落後一個會期。

### 5. 著作權與 robots ⚠️

```
$ f.sh 'https://www.kcc.gov.tw/cp.aspx?n=104'   → 200
  「使用者下載或拷貝網站的內容或服務僅供個人、非商業用途之使用…不可變更、發行、播送、轉賣、重製、改作、散布…以賺取利益。」
$ f.sh https://www.kcc.gov.tw/robots.txt        → 404
$ f.sh https://cissearch.kcc.gov.tw/robots.txt  → 404
$ f.sh https://ivod.kcc.gov.tw/robots.txt       → 200，但內容是 SPA 外殼，等於沒有 robots
```

聲明比臺北嚴格：沒有「同意連結」條款，重製限個人、非商業使用。cissearch 自己也有著作權聲明頁（`/System/StaticPages/CopyrightNotice.aspx`），**還沒讀**。我們只存詮釋資料並連回原站，應該可以接受，但上線前要再讀 cissearch 的聲明。

---

## 臺中市議會（部分調查）

### 1. 名錄 ✅（有黨籍，無生日）

`main.asp?uno=16` 只是外框，名單放在 iframe `wb_introduction01.asp` 裡。

```
$ f.sh https://www.tccc.gov.tw/wb_introduction01.asp   → 200
  「第一選區 大甲區、大安區、外埔區 楊啓邦 施志昌 李文傑 第二選區 … 第十七選區 山地原住民 朱元宏」，17 個選區
  個人頁連結 main.asp?uno=14&cno=<n>，不重複 62 個（應選 65 席，差額原因沒查）
$ f.sh 'https://www.tccc.gov.tw/wb_introduction02.asp?uno=&cno=10'   → 200
  「第三選區議員吳瓊華 現任 直轄市第四屆議員 黨藉 中國國民黨 … 學歷 … 經歷 … 政見 1.…」；沒有生日
```

### 2. 書面質詢 ❌（沒找到）；口頭質詢逐句議事錄 ✅

- `yishi.tccc.gov.tw` 是議事系統（Nuxt SPA）：
  - 模組有議案（proposals）、議事錄（proceedings）、會議紀錄（meeting-records）、舊議事錄檢索（minutes-search）、法規。
  - 1.49 MB 的 entry bundle 和議事錄頁的 chunk 都 **grep 不到「書面」**。
  - 全球資訊網首頁也沒有書面質詢的連結。
  - **暫時判斷臺中沒有公開的書面質詢系統**。書面質詢可能收在議事錄 PDF（`/api/ProceedingsBackWeb/FrontDownload`）裡，沒有實測。
- 議事錄 JSON，GET、不需要登入：

```
$ f.sh 'https://yishi.tccc.gov.tw/api/ProceedingsBackWeb/FrontList?pageSize=5&pageNumber=1'   → 200，totalCount 965536
$ f.sh 'https://yishi.tccc.gov.tw/api/Common/GetMeetingType'   → 200（市政總質詢 b2c3d4e5-…、業務質詢 c2d3e4f5-…、大會、附錄…）
$ f.sh '…/FrontList?pageSize=5&pageNumber=1&meetingTypeId=b2c3d4e5-f6a7-8901-b2c3-d4e5f6a78901'   → 200，totalCount 273195
  {"proceedingsId":"e8e08c09-…","sessionDisplay":"第4屆第7次定期會","meetingTypeName":"市政總質詢",
   "content":"謝謝主席。我們盧市長所帶領的市府團隊…","date":"2026-05-27T01:12:00","speaker":"沈議員佑蓮"}
$ f.sh '…/FrontList?…&term=4&meetingTypeId=…'   → 400 "The value '4' is not valid for Term."
$ f.sh 'https://yishi.tccc.gov.tw/api/Common/GetAllCouncilMemberName'   → 401「未登入」
$ f.sh '…/api/Proposal/FrontList?pageSize=3&pageNumber=1'   → 200，totalCount 15270（議案，有 sponsor 與 jointSignatory）
```

- 每一筆是一段發言，`speaker` 的格式是「沈議員佑蓮」，所以可以得到「哪位議員在哪天的哪種質詢發過言」。`content` 只有前段，全文沒查。
- 屆別篩選的參數格式沒試出來（`term=4` 會回 400），要再從前端 chunk 找。
- 議員提案（`Proposal/FrontList`）是另一個可以逐人歸屬的來源，不在這次範圍。

### 3. 口頭質詢影片 ✅（逐位議員剪輯）

以下都不帶 cookie（`f.sh` 不保留 cookie）：

```
$ f.sh 'https://vod.tccc.gov.tw/wb_news01.asp?url=91'   → 200
  「蔡成圭 議員 第4屆第8次定期會 市政總質詢 2026-09-29 …
    陳俞融 議員 第4屆第8次定期會 市政總質詢(陳俞融、陳淑華等議員聯合質詢) 2026-09-29」
  連結 index.asp?url=92&ano=14846&pageno=1
$ f.sh 'https://vod.tccc.gov.tw/wb_news02.asp?url=92&ano=14846&pageno=1'   → 200
  「林德宇 議員 第4屆第8次定期會 市政總質詢(林德宇、曾威等議員聯合質詢) 會議日期： 2026-09-29 影片長度： 00:50」
  播放器路徑 player/ncm/vod/vod0128vh-67eb/04A08+_08_11509xx+_1150929_1110_8_13_03_2_1
$ f.sh 'https://vod.tccc.gov.tw/wb_name02.asp?url=22&cno=24'   → 200（陳淑華個人清單，分頁 1–4＋，
  含市政總質詢與各部門「業務質詢：…部分」）
```

- 每位議員每一次質詢是一支獨立影片，網址 `https://vod.tccc.gov.tw/index.asp?url=92&ano=<n>` 是整數 ID。
- 聯合質詢時，同一場會替每位議員各放一支影片，標題寫出「(A、B等議員聯合質詢)」。
- 格式是 HTML，要解析；沒有 JSON。
- 臺中議會官方 YouTube：未實測。

### 4. 出缺勤：未實測

- 議事錄附錄（`meetingTypeId=a4b5c6d7-…`）共 55 筆，只有委員名單、座席表、議事日程表、質詢順序表等，**沒有出席統計表**。
- 大會議事錄的 `FrontDetail` 參數沒試出來（`proceedingsId=` 回 `data:null`）。
- 議事錄 PDF 裡有沒有出席名單，沒有實測。

### 5. 著作權與 robots ⚠️

```
$ f.sh https://www.tccc.gov.tw/robots.txt      → 404
$ f.sh https://vod.tccc.gov.tw/robots.txt      → 404
$ f.sh https://yishi.tccc.gov.tw/robots.txt    → 200，2 bytes（空白）
vod 頁尾：「本網站之所有版權屬臺中市議會所有，未經授權不得轉載。」
```

`www.tccc.gov.tw` 的著作權聲明頁沒有找到或讀取（未實測）。只連結、不轉載影片，應該不衝突。

---

## 臺南市議會（部分調查）

### 1. 名錄 ✅（有黨籍；抽 1 人沒有生日）

```
$ f.sh 'https://www.tncc.gov.tw/subhome.asp?orcaid=C56635AE-3C35-4233-8561-7B2CAA2DF01F'   → 200
  「第一選區 (應選6人) … 第十三選區 (應選1人)」；
  「第一選區(後壁.白河.東山.鹽水.新營.柳營區) 蔡育輝 中國國民黨 趙昆原 無黨籍 王宣貿 民主進步黨 張世賢(歿) 無黨籍 …」
  個人頁 councilorpage.asp?mainid=<GUID>
$ f.sh 'https://www.tncc.gov.tw/councilorpage.asp?mainid=053E553A-B244-4F42-9BF5-0716C40A7EAD'   → 200
  「黨籍： 中國國民黨 參加黨團： 國民黨團 … 學歷 … 經歷 …」；沒有生日
```

名錄會標出已故議員（「張世賢(歿)」），ETL 要處理。

### 2. 書面質詢：未實測

首頁沒有書面質詢系統的連結。有議案檢索（`motion1.asp`，200，可依案由、提案人、連署人查）與「議員質詢辦法」頁，都沒深入。

### 3. 口頭質詢影片 ✅（依議員篩選，逐人 YouTube 影片）

```
$ f.sh 'https://www.tncc.gov.tw/councilmovielist.asp?orcaid=EF1DC98A-A077-4EEA-9687-DE0113752A11'   → 200
  表單 method=post：menu1（屆次）、council1tag（議員，55 人）、avtype（市政總質詢／專案報告／業務報告／自由發言…）
$ sess.py POST 同網址 {menu1:第4屆, council1tag:李啟維, avtype:市政總質詢}   → 200
  2025-11-05【第4屆第6次定期會：市政總質詢】 youtube.com/embed/yDyzoFJU8_Y 「李啟維議員市政總質詢」
  2024-10-29【第4屆第4次定期會：市政總質詢】 youtube.com/embed/aOFmXQEvq74 「李啟維議員市政總質詢」
  （同一天的區塊裡也會出現其他議員的影片，例如朱正軒、李鎮國，因為篩選結果以日期為單位）
```

- 影片是逐位議員的 YouTube 影片，所以穩定網址就是 `https://www.youtube.com/watch?v=<id>`。
- 依議員篩選要用 POST，結果以「日期區塊」回傳，要再用影片標題（「○○○議員市政總質詢」）對到議員。
- 官網首頁連到 YouTube 頻道 `UCdA-WnlDKDfJol0SJhsf63g`，可以認定是官方頻道。頻道影片數與完整度用 yt-dlp **還沒實測**。

### 4. 出缺勤：未實測

議事錄是每個會期一個 PDF，網址是靜態的，例如 `https://www.tncc.gov.tw/warehouse/391D237B-D89E-47F6-8063-23B7B7AE57C3/臺南市議會第4屆第6次定期會議事錄.pdf`，列在 `download.asp?orcaid=391D237B-…`（200）。PDF 內有沒有逐人出席資料沒下載看。

### 5. 著作權與 robots ⚠️

- 議事影音頁寫：「依本會錄影、錄音管理規則第八條規定：經轉錄之影音資料，對外播放或播映，其責任應由播放或播映者自行負責。」我們只連到 YouTube，不轉錄。
- `https://www.tncc.gov.tw/robots.txt` 會轉到 `blank.asp`（200 HTML），等於沒有 robots。
- 頁尾有「網站資料開放宣告」，**還沒讀**。

---

## 桃園市議會（只到首頁）

```
$ f.sh https://www.tycc.gov.tw/          → 200 722 B（meta refresh 轉到 tc/index.aspx，ASP.NET ViewState）
$ f.sh https://www.tycc.gov.tw/tc/index.aspx   → 200 98392 B
```

首頁抓到的系統網址，**都還沒打開**：

| 用途 | 網址 |
|---|---|
| 本屆議員 | `/TC/councilor-info.aspx?mid=39`；議員介紹 `/TC/councilor-detail.aspx?mid=37` |
| 議事影音 | `/TC/LiveVideo/record.aspx?mid=85`、`/TC/LiveVideo/video.aspx` |
| 議事直播 | `/TC/LiveVideo/live.aspx?mid=46` |
| 議事錄 | `/TC/file.aspx?mid=44` |
| 相關質詢審查及活動表 | `/TC/file.aspx?mid=45` |
| 「市政總質詢」 | `/TC/new.aspx?mid=50`（看起來是新聞稿，例如「市議員吳進昌促…」） |
| 著作權聲明 | `/TC/page.aspx?mid=21` |
| 議員社群連結 | `/TC/link02.aspx?mid=79` |

## 新北市議會（連線失敗）

```
$ dig +short www.ntp.gov.tw   → 163.29.134.135
$ f.sh https://www.ntp.gov.tw/            → curl (28) 30 秒逾時，0 bytes（11:43）
$ f.sh http://www.ntp.gov.tw/             → 逾時（11:44）
$ curl -v --http1.1 https://www.ntp.gov.tw/   → TLS 1.3 握手完成、送出 GET 後沒有回應
$ curl（完整瀏覽器標頭、Chrome UA）      → 25 秒逾時
$ nc -z 163.29.134.135 443 / 80           → 都連得上
$ f.sh https://vod.ntp.gov.tw/            → 200，「IIS Windows Server」預設頁
```

可能是站台故障，也可能是 WAF 擋了這個來源 IP（本機 IP 在臺灣，`ipinfo.io/country` 回 TW）。**要換時間或換網路再試**。舊文件提過 `vod.ntp.gov.tw`、`nlive.ntp.gov.tw`、`ntpbook.ntp.gov.tw`，只有 `vod` 實測過，而且只回 IIS 預設頁。

## 16 縣市：未調查

基隆市、新竹市、新竹縣、苗栗縣、彰化縣、南投縣、雲林縣、嘉義市、嘉義縣、屏東縣、宜蘭縣、花蓮縣、臺東縣、澎湖縣、金門縣、連江縣。這次沒有發出任何請求。

---

## 建議順序與工作量（暫定，只根據已查的 3 個議會）

| 順序 | 議會 | 可以先做的 | 預估工作量 | 理由 |
|---|---|---|---|---|
| 1 | 高雄 | 名錄（getMembers JSON）＋影片（逐人 in/out）＋出缺勤（統計表 PDF） | 名錄與影片約 1 人日（JSON，接近 V3 的量）；出缺勤 PDF 直排解析約 1 人日；書面質詢要再驗證 0.5 人日 | 資料最結構化，影片與出缺勤都做得到逐人 |
| 2 | 臺中 | 名錄（HTML iframe）＋影片（逐人剪輯 HTML） | 約 1–1.5 人日 | 影片天生是逐人的；議事錄 JSON 可以補「有發言」的紀錄。書面質詢和出缺勤要先確認有沒有 |
| 3 | 臺南 | 名錄＋影片（POST 篩選＋YouTube ID） | 約 1 人日 | 影片逐人；書面質詢與出缺勤都還沒驗證 |
| — | 桃園、新北、16 縣市 | 先完成普查 | 普查約 0.5 人日／五都、0.1–0.2 人日／縣市 | 還沒有資料可以排序 |

**11/07 前能上線深度資料的五都（暫定判斷）**：
- **高雄最有把握**：名錄、影片、出缺勤三項都已確認有逐人資料。
- **臺中、臺南的名錄＋影片也做得到**，但書面質詢不一定有。
- 桃園、新北要看普查結果。

---

## 未解問題

1. 新北 `www.ntp.gov.tw` 不回應：是站台故障還是 WAF 擋 IP？要換時間或換網路重試。
2. 高雄書面質詢：公報的「議員質詢書面答復」怎麼依議員列出逐筆？（進階查詢 `Scan3.aspx` 的類別篩選沒試）
3. 高雄 iVOD `watch/<gid>/<source>` 的播放器會不會跳到 `mark_list` 的 in 點？要用 headless 瀏覽器驗證。
4. 高雄 getMembers 64 筆、臺中個人頁 62 個，都比應選 65 席少，原因沒查（出缺或遞補）。
5. 臺中 yishi 的屆別參數格式、`FrontDetail` 參數、議事錄 PDF 裡有沒有書面質詢與出席名單。
6. 臺南書面質詢、議事錄 PDF 裡的出席資料、YouTube 頻道完整度。
7. 五都官方 YouTube 頻道的普查（yt-dlp），一個都還沒做。
8. 桃園全部項目。
9. 平台分組要等 16 縣市普查完才能確認有沒有共用廠商。
