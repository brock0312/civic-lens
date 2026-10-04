# V15 普查：五都現任議員的問政紀錄（書面質詢、口頭質詢影片、出缺勤）與報導者觀測站

> **已定案（使用者，2026-10-03）**
> 1. 報導者觀測站：先由使用者寫信至 contact@twreporter.org 申請書面同意，回覆前不擷取、不存其內容。
> 2. 桃園議會影片（聲明「不得用於政治目的、選舉」）：先交法遵審查（security-executor），審查前不做。
> 3. 高雄出缺勤：照議會官方統計顯示出席、請假、缺席，附定義與出處。
> 4. 新北：出席只顯示「出席 N／M 次」並說明沒有請假紀錄；書面質詢連到各會期掃描 PDF（無個別題目）。
> 5. **更正（2026-10-04）**：新北「摘要紀錄」其實多數列有請假名單（實作時檢查 381 份：305 份有「請　假：」名單，114 份出席欄只寫「詳如簽到簿」，2 份颱風停會）。使用者改決定顯示「出席 N／M、請假 L 次」，兩份名單都未列名者不另顯示、不區分缺席；只寫「詳如簽到簿」的會議不列入分母。

> **結論**：五都都有至少一種「逐人」的官方問政紀錄，但每個議會能做的種類不一樣；**都不需要 headless 瀏覽器**。
> - **高雄**最完整：三種紀錄都有逐人資料。影片可以深連結到該議員發言的起點（`/watch/<gid>/<source>?start=<秒>`）。出席統計表另有「缺席」欄，比臺北細。書面質詢收在公報的「議員質詢書面答復」，每格有「質詢日期（書面質詢）、議員姓名、質詢事項」，要從 PDF 文字層解析。
> - **新北**：V12 連不上，這次正常。**書面質詢**在議事錄系統的附錄裡，一人一份 PDF，連結標題寫明日期和議員姓名（「114年11月10日陳偉杰議員個人書面質詢及答復」），所以逐人歸屬靠 HTML 就夠了；但 PDF 是掃描檔，沒有文字層，抓不到題目。**出席**：每天的大會「摘要紀錄」PDF（有文字層）列出出席議員，沒有請假名單。**影片**：可以依議員查詢，但影片是整場（黨團或多人），沒有個人起點。
> - **桃園**（現在是**第 3 屆**）：**影片**可以依議員篩選，市政總質詢頁另有每位議員的跳轉連結 `record_in.aspx?id=<n>&s=<起始秒>&dd=<長度>`，播放器會帶入 `wstart`。書面質詢、出缺勤都沒有找到逐人資料。
> - **臺中**：**影片**是逐人剪輯（V12 已確認）。書面質詢沒有公開文件，議事錄 JSON 只看得到主席宣布「某某議員改書面質詢」。出缺勤沒有找到逐人名單。
> - **臺南**：**影片**可以依議員查詢（GET 也可以），每人每會期一支市政總質詢 YouTube 影片，量很少（抽樣 1 人在第 4 屆共 8 支）。議事錄附錄有「議員出缺席表」，但那一頁是**掃描圖**，要 OCR 才能讀。沒有找到書面質詢。
> - **報導者觀測站**（`lawmaker.twreporter.org`）：六都議會都有，議員頁網址是 `/council/<城市>/lawmaker/<slug>`，背後有不需登入的 JSON API，5 位抽樣議員都找到。內容是**議員提案**（不是質詢），資料到 2025 年底。**要使用者決定**：它的 robots.txt 對 `*` 是 `Allow: /`，但檔頭註明「未經事先書面許可，禁止以自動化方式擷取內容」，也禁止「提供含其內容的資料集給他人」。
>
> **要注意**：
> - 桃園的議事錄影頁寫著「本會影音訊號不得做為任何形式之商業目的、廣告、促銷、宣傳、政治目的、選舉或訴訟使用」。我們只連結、不轉錄，但頁面主題是選舉，**上線前要請使用者判斷**。
> - 高雄 iVOD 一位議員第 4 屆約 237 支影片，起點秒數要逐支呼叫 `getConvertVideoData`，五都裡請求量最大（54 人，上限約 1.1 萬次，約 3.5 小時）。
> - 臺南 `李啓維`、`李啟維` 在影片標題裡混用；篩選下拉選單用的是 `李啟維`。
> - 高雄 cissearch 全文檢索一次回傳 1–2 MB HTML。我在背景程式用一個會回溯的正規表示式處理，卡住後砍掉了（不是網站的問題）。
> - 臺南定期會議事錄一個 PDF 可以到 296 MB（第 6 次定期會），40 秒內只下載到 40 MB。
>
> **狀態**：✅ 2026-10-03 完成。下面標「未實測」的格子是這次沒有驗證到的。

調查日期：2026-10-03　原始檔：`data/cache/v15/`（gitignore；`log.tsv` 記了約 170 筆請求；`f.sh`、`sess.py` 是這次用的抓取工具）
請求都帶 `User-Agent: civic-lens-etl/0.1`，同一主機間隔 ≥ 1.15 秒，循序發送。沒有開 headless 瀏覽器。高雄、桃園、新北的 ASP.NET 表單都用 `sess.py`（cookie＋ViewState）以 POST 送出。

抽樣議員（從 `data/civic.sql` 的 office＋2026 candidacy 選出，都是現任且登記參選 2026）：

| 議會 | 議員 | 本站選區 | 觀測站 slug |
|---|---|---|---|
| 高雄 | 邱俊憲 | khh-council-05 | `chiu-chun-hsien-kaohsiung` |
| 臺中 | 陳淑華 | txg-council-06 | `chen-shu-hua-taichung` |
| 臺南 | 李啓維（議會網站寫作「李啟維」） | tnn-council-09 | `li-chi-wei-tainan` |
| 新北 | 陳偉杰 | nwt-council-01 | `chen-wei-chieh-new-taipei` |
| 桃園 | 黃瓊慧 | tao-council-01 | `huang-chiung-hui-taoyuan` |

2026-10-03 的 dump 中，現任且登記參選 2026 的議員：新北 52、桃園 55、臺中 56、臺南 47、高雄 54，共 264 人（dump 可能還在被其他 ETL 更新）。

## 總表

圖例：
- ✅：可以逐人取得，抽樣議員實際取到一筆。
- ⚠️：有逐人資料但有限制（掃描檔、沒有個人起點、只有出席沒有請假等）。
- ❌：找過但沒有找到。
- 未實測：沒有查。

| 議會 | 書面質詢 | 口頭質詢影片 | 出缺勤 | 可行性／估計工作量 |
|---|---|---|---|---|
| 高雄 | ✅ 公報「議員質詢書面答復」PDF，有文字層，每格標「（書面質詢）」與議員姓名 | ✅ iVOD JSON，逐人清單＋發言起訖秒數，`?start=` 深連結 | ✅ 公報「議員出席情形統計表」PDF（直排），有出席／請假／病假／公差／公假／喪假／事假／缺席 | 高；影片 1、出缺勤 1、書面質詢 1.5 session |
| 新北 | ⚠️ 議事錄附錄一人一份 PDF，標題有日期＋姓名；PDF 是掃描檔 | ⚠️ VodCloudV2 可依議員查詢；整場影片，列出「發言議員」，沒有個人起點 | ⚠️ 每日大會「摘要紀錄」PDF 列出「出席」名單（有文字層），沒有請假名單 | 中高；書面 0.5–1、影片 0.5–1、出席 1 session |
| 桃園（第 3 屆） | ❌ 只在影片清單看到「（書面質詢）」註記 | ✅ 依議員篩選（POST），市政總質詢有每人 `&s=` 起始秒 | ❌ 議事錄、速紀錄都沒有出席名單 | 中；影片 1 session |
| 臺中 | ❌ 議事錄 JSON 只有「某某議員改書面質詢」 | ✅ 逐人剪輯（V12），一人一頁清單 | ❌ 議事錄 PDF 只寫「簽到人數已達法定開會額數」 | 中；影片 1 session |
| 臺南 | ❌ 首頁、臨時會議事錄都沒有（定期會議事錄太大，未實測） | ✅ 依議員查詢（GET），逐人 YouTube 影片，每人每會期約 1 支 | ⚠️ 議事錄附錄有「議員出缺席表」，但是掃描圖 | 中；影片 0.5 session；出缺勤需要 OCR，不建議 |
| 報導者觀測站 | — | — | — | 技術上 0.5–1 session（五都一起）；**授權與擷取許可要使用者決定** |

---

## 高雄市議會

### 書面質詢 ✅

V12 沒打到逐筆。這次發現書面質詢的答復收在**公報議事錄**，資料分類是「議員質詢書面答復」，每個部門每個會期一筆。內容是「議員質詢事項答復表」，一格一位議員；書面質詢的格子在質詢日期後面標「（書面質詢）」，口頭質詢的格子沒有。

```
# 公報全文檢索（Bulletin/Default.aspx，POST，ddlSession=0704）
$ khh_simple.py '書面質詢'              → 200，1.8 MB，共 141 筆；分類：各部門業務質詢及答復 48、議員質詢書面答復 44、市長施政報告質詢及答復 8 …
$ khh_simple.py '（書面質詢） 邱議員俊憲' → 200，共 23 筆，其中「議員質詢書面答復」1 筆：
  【議事錄】第4屆第2次定期大會 議員質詢書面答復 卷期：第42卷第4期 起始頁次P.8493
  View.aspx?scan=1&BulletinSN=242856&pages=8492,8493
$ f.sh 'https://cissearch.kcc.gov.tw/System/Bulletin/View.aspx?scan=1&BulletinSN=242856&pages=8492,8493'   → 200（不帶 cookie）
  <iframe src='Pdfview.aspx?file=~/Upload/Attachment/公報資料/高雄市議會/42卷/4期/42卷4期08489起頁08494迄頁.pdf&page=5'>
$ f.sh '…/Upload/Attachment/公報資料/高雄市議會/42卷/4期/42卷4期08489起頁08494迄頁.pdf'   → 200 application/pdf 276090 B
$ pdftotext -layout
  都市計畫委員會業務質詢及答復（邱俊憲）
  高雄市議會第 4 屆第 2 次定期大會都市計畫委員會業務質詢議員質詢事項答復表
                   （112.11.10 高市府都發規字第 11205625200 號函復）
  質 詢 日 期 112.11.2（書面質詢）
  議 員 姓 名 邱議員俊憲
  質詢事項  一、建請大樹地區都市計畫通盤檢討時，一併檢討水保區、限建區…
  主辦機關  都市發展局
```

- 這份 6 頁的 PDF 有 5 格：3 格是書面質詢（何權峰 1、邱俊憲 2），2 格是口頭質詢的答復（李眉蓁、黃文志）。所以這個分類同時收口頭與書面，要靠「（書面質詢）」區分。
- **原文連結**：`View.aspx?scan=1&BulletinSN=<n>&pages=<頁>`（不需 cookie），或直接連 PDF。
- **筆數量級**：第 4 屆含「書面質詢」字樣的「議員質詢書面答復」公報共 44 筆（全文檢索的結果，**沒有全量下載核對**）。每筆是一個部門一個會期，裡面有多位議員的多格。逐格總數未實測。
- 進階檢索（`AdvancedSearch.aspx`，可以選類別 27 與議員代碼 `0704024`）POST 後一律回 0 筆，原因沒查出來。改用一般全文檢索就可以。
- 答復表裡的「質詢事項」就是題目，可以直接當標題用，不需要 NotebookLM。

### 口頭質詢影片 ✅（逐人，可以深連結到起點）

```
$ f.sh https://ivod.kcc.gov.tw/cms/public/api/getConvertVideoMemberList/80/1/1000   → 200 480591 B
  videoQuestion 457 支（106-09-28 ～ 115-09-23），其中 date ≥ 111-12-25 的 237 支
$ f.sh https://ivod.kcc.gov.tw/cms/public/api/getConvertVideoData/80/202609KCC0408R1150923143208VIDEOmp4   → 200
  "mark_list":[{"in":"1701","out":"2865","name":"邱俊憲"},{"in":"2864","out":"3066","name":"邱俊憲"}]
  "videoPlayUrl":"https://ivod.kcc.gov.tw/cms/public/api/getConvertVideojs/80/202609/0408R1150923143208.mp4"
$ f.sh 'https://ivod.kcc.gov.tw/cms/public/api/getConvertVideojs/80/202609/0408R1150923143208.mp4?start=927'   → 200
  第 69 行：player.currentTime(927);
```

- 前端程式（`app.b8d679f7….js`）在 watch 頁把 `$route.query.start` 接在 `videoPlayUrl` 後面當 `?start=`，播放器頁由伺服器寫入 `player.currentTime(<start>)`。所以**深連結是 `https://ivod.kcc.gov.tw/watch/<gid>/<source>?start=<in>`**。這是從 HTML 與 JS 判斷的，**沒有用瀏覽器實際播放驗證**。
- 每支影片是整場會議，`mark_list` 給該議員的發言段。要拿到起點，每支影片要多打一次 `getConvertVideoData`。
- 量：邱俊憲第 4 屆 237 支。54 人估計 1 萬支以上（同一場會議會出現在多位議員名下，但 `getConvertVideoData` 帶 gid，是否回傳全部議員的 mark **未實測**）。

### 出缺勤 ✅

V12 已確認第 4 屆有 17 份統計表（成立大會、第 1–10 次臨時會、第 1–6 次定期大會）。這次抽一份讀出邱俊憲：

```
$ f.sh '…/公報資料/高雄市議會/46卷/5期/46卷5期16714起頁16715迄頁.pdf'   → 200 389259 B
  十八、第 4 屆第 9 次臨時會議員出席情形統計表
  姓名（直排）：康曾林林朱李黃陳宋黃林方陸白陳陳黃李李李陳江吳張邱黃李陳簡蔡黃 …
  第 25 欄「邱俊憲」：出席 7、請假 0、病假 0、公差 0、公假 0、喪假 0、事假 0、缺席 0
  註：○出席 △請假 ◇病假 ☆公差 □公假 ▽喪假 §事假 ☉缺席
```

- 比臺北（V4）多了「缺席」與假別，所以可以算出席率、請假率，也可以如實顯示缺席次數（是否顯示要使用者決定，見最後）。
- 公報大約落後一個會期（第 7、8 次定期大會的統計表還沒刊出）。

### robots 與條款

`cissearch.kcc.gov.tw/robots.txt` 404；`ivod` 回 SPA 外殼（等於沒有）。著作權聲明見 V12（個人、非商業使用）；cissearch 自己的聲明頁仍未讀。

---

## 新北市議會

V12 時 `www.ntp.gov.tw` 不回應；這次（10:15）正常，`dig` 只有 IPv4 `163.29.134.135`，沒有遇到憑證或 IPv6 問題。V12 的失敗應該是暫時的。

### 書面質詢 ⚠️（逐人，但 PDF 是掃描檔）

議事錄系統 `ntpbook.ntp.gov.tw` 的每個會期都有「附錄」，其中一節是「書面質詢及答復」，一人一份 PDF。

```
$ f.sh https://ntpbook.ntp.gov.tw/Home/Home/IndexByMJ   → 200；第 4 屆 19 本（成立大會～第 8 次定期會），連結 /Home/BookAgenda?cBookMdslID=<GUID>
$ f.sh 'https://ntpbook.ntp.gov.tw/Home/BookAnnex?cBookMdslID=23fbccb1-8d15-4f9c-8287-dfd58746eb2f'   → 200（第 6 次定期會附錄）
  書面質詢及答復：約 70 個連結，例：
  114年11月10日陳偉杰議員個人書面質詢及答復 | https://ntpbook.ntp.gov.tw/Mam/BookAnnex/202601/f434e0ff-d578-480c-b366-621003c2faf5.pdf
  114年10月31日、11月3日張維倩議員等7位議員聯合書面質詢及答復 | …/17299e0e-….pdf
  114年11月5日、11月7日國民黨團聯合書面質詢 | …/c4927665-….pdf
$ f.sh …/f434e0ff-d578-480c-b366-621003c2faf5.pdf   → 200 6506021 B，15 頁
  pdffonts：沒有字型；pdfimages：每頁一張 300 dpi JPEG → 掃描檔，沒有文字層
```

- 逐人歸屬：連結文字寫了日期和議員姓名；聯合質詢寫「某某議員等 N 位」或黨團，**聯名的其他人要打開 PDF 才知道**。
- 一份 PDF 是一位議員在一個會期的全部書面質詢，沒有題目。顯示方式只能是「第 4 屆第 6 次定期會 書面質詢及答復（PDF，掃描檔）」。
- 量：第 6 次定期會約 70 份；第 4 屆 7 個定期會估計約 500 份（只看了 1 個會期）。
- 附錄更新時間：第 6 次定期會（114 年 10–11 月）的附錄檔放在 `202601/`，大約落後 2 個月。

### 口頭質詢影片 ⚠️（可依議員查詢，沒有個人起點）

```
$ sess.py POST https://vod.ntp.gov.tw/VodCloudV2/VOD/Search
    {pageindex:1, MJ:'', MP:'', MType:'', sMDate:'2022/12/25', eMDate:'2026/10/03', Keyword:'', cEPName:'陳偉杰', Sort:'MDate'}   → 200
  「議員姓名:陳偉杰; 總筆數:152」
  00:02:00:34 第4屆第8次定期會 議程：市政總質詢 發言議員：陳偉杰,曾煥嘉,黃永昌,蔡健棠,蔣根煌 開會日期：115-09-03
  ViewDetailMetaData/3f76024b-9eb2-436c-903a-6517e2283036
$ f.sh https://vod.ntp.gov.tw/VodCloudV2/VOD/ViewDetailMetaData/3f76024b-…   → 200（不帶 cookie）
$ f.sh 'https://vod.ntp.gov.tw/VodCloudV2/VodStream/VideoPlayer?assetID=3f76024b-…&type=Book_SD'   → 200
  video.js 播放 vodwms.ntp.gov.tw 的 HLS，沒有讀網址的起始參數
```

- 少了 `Sort` 欄位時伺服器回 500。
- 業務質詢是「黨團發言」整場，一場 10 多位議員；市政總質詢一場約 5 人。只能連到整場影片，並寫「本場發言議員：…（N 位），未細分到個人」。
- 審查委員會影片另在 `vod.ntp.gov.tw/ExamVOD`，列有「出席議員」（委員會出席），這次沒有細看。

### 出缺勤 ⚠️（只有出席名單）

```
$ f.sh 'https://ntpbook.ntp.gov.tw/Home/BookAgenda?cBookMdslID=23fbccb1-…'   → 200；第 6 次定期會共 45 個「摘要紀錄」、45 個「會議紀錄」
$ f.sh https://ntpbook.ntp.gov.tw/Mam/BookAgendaAnnex/202510/bff680b7-69df-4ee0-a40e-c7d8373bb06d.pdf   → 200（有文字層）
  新北市議會第 4 屆第 6 次定期會第 1 次會議摘要紀錄
  時  間：中華民國 114 年 10 月 1 日 13 時 59 分
  出  席：林國春 洪佳君 陳鴻源 石一佑 … 陳偉杰 劉美芳
  列  席：秘書長陳王正源 …
```

- 每一天的摘要紀錄都列出出席議員，**沒有請假名單**（全文只有「局長今日請假」）。只能算「出席 N 次／應出席 M 次」，請假和缺席分不出來。比臺北 V4 的資訊少。
- 量：一個定期會約 45 份，第 4 屆估計 300–400 份 PDF。會議紀錄 HTML（`/Home/BookAgenda/ViewRecord?cBookAgendaID=`）是逐字紀錄，不列出席。

### robots 與條款

`www.ntp.gov.tw`、`ntpbook`、`vod` 的 robots.txt 都是 404。著作權聲明未讀（未實測）。

---

## 桃園市議會

桃園 2014 年才升格，**現任是第 3 屆**（2022-12-25 就職）。

### 口頭質詢影片 ✅（逐人起點）

```
$ f.sh 'https://www.tycc.gov.tw/TC/LiveVideo/record.aspx?mid=85'   → 200
  篩選欄位：ddlMembersName（議員代碼，黃瓊慧=974）、ddlMeetingClass（53=總質詢）、ddlClass（20=第三屆）、ddlMeetingType、ddlMeetingBout
$ sess.py POST 同網址（所有 select 都要帶預設值，例如 ddlMeetingType=0；少帶一個就回 404 頁）
    {ddlMembersName:974, ddlMeetingClass:0, ddlClass:20, ddlMeetingType:0, ddlMeetingBout:'', btnSearch:'查詢'}   → 200
  12 筆／頁，共 2 頁，例：record_in.aspx?id=1190「1、林志強 2、黃瓊慧 3、張肇良 4、王珮毓」（2026-05-12）
$ f.sh 'https://www.tycc.gov.tw/TC/LiveVideo/record_in.aspx?id=1190'   → 200
  record_in.aspx?id=1190&s=4782&dd=2405">黃瓊慧議員
$ f.sh 'https://www.tycc.gov.tw/TC/LiveVideo/record_in.aspx?id=1190&s=4782&dd=2405'   → 200
  <iframe src="https://rds.ginnet.cloud/player/vod/vod0120vv-s5q1/20260512115401_live_30040641?autoplay&wstart=4782&wduration=2405">
```

- 市政總質詢一個時段一位議員（40 分鐘），頁面給每位議員的起始秒。**深連結是 `record_in.aspx?id=<n>&s=<s>&dd=<dd>`**（HTML 層確認 `wstart` 有帶入，沒有用瀏覽器播放驗證）。
- 清單會出現「（黃瓊慧議員）」「（黃瓊慧 許家睿 等議員聯合質詢）」這類括號註記，是併入別人時段的聯合質詢。這種情況只能連到主質詢人的時段。
- 量：黃瓊慧第 3 屆約 20 筆（2 頁），多數是市政總質詢。工作報告（業務質詢）的影片沒有逐人切段。

### 書面質詢 ❌、出缺勤 ❌

- 影片清單看得到「1、張肇良 議員（書面質詢）」，表示有改採書面的情形，但官網沒有書面質詢文件。
- 議事錄（`/TC/file.aspx?mid=44`）：第 3 屆第 7 次定期會正本 5,340 頁（15 MB）、附錄 50 頁，grep 不到出席名單；附錄是議事日程等。
- 速紀錄（`/TC/meeting.aspx?mid=41`，每次會議一個 PDF，有文字層）是逐字質詢稿，例 `第28次會議：市政總質詢.pdf` 從「劉曾議員玉春問：」開始，沒有出席名單。

### robots 與條款

- `www.tycc.gov.tw/robots.txt` 回首頁 HTML（等於沒有 robots）。
- 著作權聲明（`/TC/page.aspx?mid=21`）：以議會名義發表的著作「在合理範圍內得重製、公開播送或公開傳輸，並請註明出處」；為報導、評論等正當目的可以合理引用。
- **議事錄影頁另有限制**：「本會影音訊號不得做為任何形式之商業目的、廣告、促銷、宣傳、政治目的、選舉或訴訟使用」。我們只放連結，但網站主題是選舉，要使用者判斷。

---

## 臺中市議會

### 口頭質詢影片 ✅（逐人剪輯）

```
$ f.sh 'https://vod.tccc.gov.tw/wb_name02.asp?url=22&cno=24'   → 200（陳淑華）
  第4屆第8次定期會 市政總質詢(陳俞融、陳淑華等議員聯合質詢) 2026-09-29
  index.asp?url=22&cno=24&ano=14826&pageno=1
  分頁：最末頁 PageNo=32（第 2 屆起）；第 12 頁已是第 4 屆第 1 次定期會（2023-05～06）
```

- 每支影片就是該議員的質詢片段，連到影片頁即是起點（V12 已確認 `index.asp?url=92&ano=<n>` 整數 ID）。
- 量：陳淑華第 4 屆約 12 頁 × 10 支 ≈ 120 支；清單含第 2、3 屆，要用屆別過濾。全量約 56 人 × 12 頁 ≈ 700 次請求。
- `vod.tccc.gov.tw/robots.txt` 404。頁尾：「本網站之所有版權屬臺中市議會所有，未經授權不得轉載」（只連結）。

### 書面質詢 ❌

```
$ f.sh 'https://yishi.tccc.gov.tw/api/Common/GetMeetingType'   → 200：沒有書面質詢類別
$ f.sh 'https://yishi.tccc.gov.tw/api/ProceedingsBackWeb/FrontList?pageSize=20&pageNumber=1&keywordList=書面質詢'   → 200，totalCount 791
  2026-05-05 業務質詢 主席（黃議員佳恬）| 接下來沈佑蓮議員改「書面質詢」…
  2026-04-28 業務質詢 主席（蕭議員隆澤）| …添議員請假、曾威議員改書面、賴順仁議員改「書面質詢」…
```

- 找到 FrontList 的全文檢索參數是 `keywordList`（V12 試的 `keyword`、`term=4` 無效；`speaker=`、`period=` 也被忽略）。
- 議事錄只有主席宣布「改書面質詢」，沒有書面質詢內容。可以從這些句子抽出「某議員某日改採書面質詢」，但沒有題目和原文，**價值低，不建議做**。

### 出缺勤 ❌

```
$ f.sh '…/FrontList?…&keywordList=出席議員'   → 311 筆，都是「今天簽到出席議員已達法定開會額數」
$ f.sh '…/FrontList?…&keywordList=請假議員'   → 0 筆
$ f.sh 'https://yishi.tccc.gov.tw/api/ProceedingsBackWeb/FrontDownload?proceedingsId=1c1ce93f-c839-442f-8668-14f626751d6d'   → 200 application/pdf，4 頁
  大會-第 11 次會議（115 年 6 月 1 日）：開頭只有「簽到議員人數已達到法定開會額數」，沒有名單
```

---

## 臺南市議會

### 口頭質詢影片 ✅（逐人 YouTube）

```
$ sess.py POST https://www.tncc.gov.tw/councilmovielist.asp
    {menu1:'第4屆', council1tag:'李啟維', status:'^', orcaid:'EF1DC98A-…', avtype:''}   → 200，第 1 頁 5 支
  2026-09-02【第4屆第8次定期會：市政總質詢】李啓維議員市政總質詢  youtube.com/embed/6SSZuttYCJk
$ f.sh 'https://www.tncc.gov.tw/councilmovielist.asp?orcaid=EF1DC98A-…&topage=2&status=^&council1tag=李啟維&AVTYPE=&menu1=第4屆&menu2=&menu3='   → 200（GET 也可以）
  2024-05-27、2023-11-02、2023-06-05 各 1 支
```

- 李啓維第 4 屆共 8 支，第 1–8 次定期會各一支市政總質詢。量很小，全量約 47 人 × 2 頁。
- 深連結就是 `https://www.youtube.com/watch?v=<id>`，影片本身就是該議員的時段。

### 出缺勤 ⚠️（掃描圖）

```
$ curl 臺南市議會第4屆第10次臨時會議事錄.pdf   → 200，31 MB，677 頁（定期會可以到 296 MB）
$ pdftotext：目錄「三、議員出缺席表 …… 676」；第 676 頁是掃描圖，抽出的文字是亂碼（「虛豈福」「昔肇輝」）
  內文只有「出席議員已達法定人數(29 位)」，沒有名單
```

表格是逐日、逐人標記（看得出 ○ 與 A），要 OCR 或人工判讀。依 V13 對無文字層公報的決定（不 OCR），**建議不做**。

### 書面質詢 ❌（未找到）

首頁沒有書面質詢系統。第 10 次臨時會議事錄全文的「書面」都是「書面資料」「書面報告」。定期會議事錄裡有沒有書面質詢**未實測**（檔案太大，沒有下載完）。

### robots

`www.tncc.gov.tw/robots.txt` 轉到 `blank.asp`（V12），等於沒有。

---

## 報導者觀測站

### 網址與資料

- 首頁 `https://lawmaker.twreporter.org/`，「六都議會」包含臺北、新北、桃園、臺中、臺南、高雄；另有立法院（`/congress/...`）。
- 涵蓋範圍（`/about`）：「六都議會則已上傳最新屆期截至 2025 年底之提案」「六都議案則將於 2026 年選舉前完成資料更新」。將來預定加入六都議員的**質詢發言**，目前只有**提案**。
- 路由（從前端 JS `14878` 模組取出）：議會首頁 `/council/<城市>`、議員頁 `/council/<城市>/lawmaker/<slug>`、議題頁 `/council/<城市>/topic/<slug>`。城市代碼：`taipei`、`new-taipei`、`taoyuan`、`taichung`、`tainan`、`kaohsiung`。
- 議員 slug 是「姓名羅馬拼音-城市」，例 `chiu-chun-hsien-kaohsiung`。拼音規則不固定（Wade-Giles 為主，也有 `pasulang-tomatalate-kaohsiung`、圖檔用數字 ID `110021.jpg`），**不能自己拼，要從 API 取**。
- JSON API（GET、不需登入，前端直接呼叫）：

```
$ f.sh 'https://lawmaker.twreporter.org/api/councilor/chiu-chun-hsien-kaohsiung/topic?city=kaohsiung'   → 200 application/json
  {"data":[{"slug":"kaohsiung-public-safety-fire-health-and-environment","name":"警消衛環","count":48},
           {"slug":"kaohsiung-transportation","name":"交通","count":41}, …共 10 筆],"status":"success"}
  （前端帶 &top=5 只取前 5；不帶 top 回全部）
$ f.sh 'https://lawmaker.twreporter.org/api/council-topic/kaohsiung-school-lunch/councilor?city=kaohsiung'   → 200
  [{"count":2,"slug":"huang-yen-yu-kaohsiung","name":"黃彥毓","avatar":"…"}, … {"count":1,"slug":"chiu-chun-hsien-kaohsiung","name":"邱俊憲"} …]
其他端點（JS 取出，未實測）：/api/council-topic?mid=&take=&skip=&pids=、/api/councilor/<slug>/topic/<topic>/bill?mid=
$ f.sh https://lawmaker.twreporter.org/council/kaohsiung/lawmaker/chiu-chun-hsien-kaohsiung   → 200 344 KB（伺服器端渲染）
  屆別 第4屆高雄市議員 現任 黨籍 民主進步黨 選區 高雄市第5選區 … 提案數 僅統計本屆期的提案數 264
  議案 警消衛環(48) 交通(41) 工務(40) 財經(30) 社政(29) …（下面列出各提案摘要）
```

- 5 位抽樣議員的頁面都打得開：

| 議員 | 頁面上的屆別／選區 | 本屆提案數 |
|---|---|---|
| 邱俊憲 | 第4屆高雄市議員／高雄市第5選區 | 264 |
| 陳淑華 | 第4屆台中市議員／台中市第6選區 | 224 |
| 李啓維 | 第4屆台南市議員／台南市第9選區 | 34 |
| 陳偉杰 | 第4屆新北市議員／新北市第1選區 | 543 |
| 黃瓊慧 | 第3屆桃園市議員／桃園市第1選區 | 220 |

- **議題標籤**大多是部門分類（警消衛環、交通、工務…），另有少數編輯精選議題（營養午餐、敬老卡福利、社會住宅政策、TPASS）。
- **怎麼對應到本站的人**：API 的人物資料只有 `name`、`slug`（以及議會首頁 RSC 資料裡的 `id`、黨籍），沒有選區；議員頁 HTML 才有選區。建議做法：每個城市用各議題的 `council-topic/<slug>/councilor?city=` 取聯集當名冊（約 10–20 個請求／城市），用「城市＋姓名」對到本站 office；同城市同名或異體字（啓／啟）進審閱清單，必要時再讀議員頁的選區確認。全量對應**未實測**，只驗證了 5 人。
- `sitemap.xml`（5.5 MB）只有立法院頁面，沒有議會頁面。

### robots.txt 與授權

```
$ f.sh https://lawmaker.twreporter.org/robots.txt   → 200
  # The Reporter content is made available for your personal, non-commercial use subject to our Terms of Service.
  # Use of any device, tool, or process designed to data mine or scrape the content using automated means
  # is prohibited without prior written permission from The Reporter. Prohibited uses include …
  # (3) creating or providing archived or cached data sets containing our content to others; and/or (4) any commercial purposes.
  User-agent: anthropic-ai … Disallow: /（另有多個 AI 爬蟲被禁止）
  User-agent: *
  Allow: /
  Disallow: /private/
$ f.sh https://www.twreporter.org/a/license-footer   → 200
  《報導者觀測站》…之內容…以 CC BY-NC-ND 3.0 台灣授權條款釋出…標示來源與作者、不得作商業使用、不得改作。
  不適用 CC 授權：評論和專欄、攝影圖表影音、非專職人員著作、頁面另標 © 的內容。
  「另外，本服務不授權政黨或政治人物使用。」
  希望進行商業使用、改作或其他未包含於授權範圍之利用方式，請聯繫 contact@twreporter.org
```

授權判斷（不是法律意見）：

| 我們想做的事 | 判斷 |
|---|---|
| 現任候選人個人頁放一個連到觀測站議員頁的連結 | 只是連結，不涉及重製，**可以**。 |
| 原文照錄議題名稱＋提案數，標示「資料來源：報導者觀測站（CC BY-NC-ND 3.0 TW）」並連回 | 提案數是事實，議題名稱多是部門名稱，原創性低；照錄不改字、標示出處、非商業，**大致在允許範圍內**。只摘前幾個議題算不算「改作」**需確認**（CC 3.0 允許把原作不加修改地收進「編輯著作」，但只取一部分是否屬於改作，條款沒有明說）。 |
| 本站非商業 | 本站沒有廣告與收費，符合 NC；**需確認**使用者是否同意這個認定。 |
| 「不授權政黨或政治人物使用」 | 本站不是政黨或政治人物，不受影響。 |
| 用程式定期抓 API，把議題與數字存進公開的 `data/civic.sql` | **有衝突**：robots.txt 的檔頭禁止未經書面許可的自動擷取，也禁止「提供含其內容的資料集給他人」。`User-agent: *` 雖然是 `Allow: /`，但檔頭文字是明確的條款。**需要使用者決定**：①寫信給 contact@twreporter.org 取得書面許可（建議）；②只放連結（slug 由人工或一次性少量查詢取得），不存數字；③暫緩。 |

---

## 建議實作順序

估計單位是 session（一個 Claude 工作階段，約等於這次普查的長度）。每一項都只收「現任且參選 2026」的人，資料照樣全收、在 export 過濾（HANDOFF §3 第 9 條）。

| 順序 | 議會 | 紀錄 | 做法 | 估計 |
|---|---|---|---|---|
| 1 | 高雄 | 口頭質詢影片 | `getMembers` → `getConvertVideoMemberList/<gid>/1/1000` → 每支 `getConvertVideoData` 取 `mark_list`；連結 `/watch/<gid>/<source>?start=<in>`。先抽一支用瀏覽器確認會跳到起點。全量請求約 1 萬次，用 `nohup` 背景跑 | 1 |
| 2 | 高雄 | 出缺勤 | 公報全文檢索「出席情形統計表」（17 份）→ 下載 PDF → 依欄位 x 座標把直排姓名對齊每欄的出席、請假、缺席數 | 1 |
| 3 | 新北 | 書面質詢 | `IndexByMJ` → 每個定期會的 `BookAnnex` → 解析「書面質詢及答復」連結文字（日期、姓名、個人／聯合），連到 PDF；聯合質詢先只記發起人 | 0.5–1 |
| 4 | 新北 | 出缺勤 | 每個會期 `BookAgenda` 的「摘要紀錄」PDF → 抽「出  席：」名單；只顯示出席次數，不顯示請假與缺席 | 1 |
| 5 | 桃園 | 口頭質詢影片 | `record.aspx` 依議員 POST（`ddlClass=20`，所有 select 帶預設值）→ 每個 `record_in.aspx?id=` 取該議員的 `&s=&dd=` 連結；先處理第 3 屆 | 1 |
| 6 | 臺中 | 口頭質詢影片 | `wb_name02.asp?url=22&cno=<n>` 翻頁到第 4 屆開頭；`cno` 從名錄或 VOD 名單取 | 1 |
| 7 | 臺南 | 口頭質詢影片 | `councilmovielist.asp` GET（`menu1=第4屆&council1tag=<名>&topage=N`），標題對姓名（處理啓／啟） | 0.5 |
| 8 | 新北 | 口頭質詢影片 | VodCloudV2 POST 依議員查詢，連到整場影片頁並列出同場發言議員 | 0.5–1 |
| 9 | 高雄 | 書面質詢 | 公報全文檢索「書面質詢」＋分類「議員質詢書面答復」→ 下載 PDF → 解析答復表，只收標「（書面質詢）」的格子；題目用「質詢事項」 | 1.5 |
| — | 五都 | 報導者觀測站 | 等使用者決定授權與擷取方式（見上）。若取得許可：每城市取名冊 → 城市＋姓名對應 → 存 slug、議題名稱與數字，頁面標示 CC BY-NC-ND 3.0 TW 與連結 | 0.5–1 |
| 不建議 | 臺中書面質詢、臺中出缺勤、桃園書面質詢、桃園出缺勤、臺南出缺勤（掃描圖）、臺南書面質詢 | | 沒有逐人文件，或要 OCR | — |

「以觀測站先補位」的做法：如果使用者選②（只放連結），只要一次性取得 264 人的 slug，0.5 session 就能讓五都的現任候選人都有一個問政入口；其餘官方紀錄再依上表逐步補上。

## 需要使用者決定的事

1. **報導者觀測站**：寫信要書面許可、只放連結，還是暫緩？（robots.txt 檔頭禁止未經許可的自動擷取與提供資料集）
2. **桃園影片**：議事錄影頁寫「不得做為…政治目的、選舉…使用」。選舉資訊站放連結算不算，要不要先問議會？
3. **高雄出缺勤的「缺席」欄**：官方表格有缺席次數。要照錄顯示，還是比照臺北只顯示出席與請假？（不評分、不排名的原則不受影響，但缺席數比較敏感）
4. **新北出缺勤**只有出席名單、沒有請假：可以只顯示「出席 N／M 次」嗎？
5. **新北書面質詢**是掃描 PDF：只顯示「某會期 書面質詢及答復（PDF）」連結、不顯示題目，可以接受嗎？

## 未實測

- 高雄 iVOD 的 `?start=` 是否真的在瀏覽器裡跳到起點；`桃園 wstart` 同。
- 高雄「議員質詢書面答復」的逐格總數；進階檢索為什麼回 0 筆。
- 高雄 `getConvertVideoData/<gid>/<source>` 是否只回該 gid 的 mark。
- 新北審查委員會影片（ExamVOD）的出席名單能不能當委員會出席資料。
- 新北、臺中 `www.tccc.gov.tw`、cissearch 的著作權聲明頁。
- 臺南定期會議事錄裡有沒有書面質詢。
- 觀測站全量名冊與本站 264 人的對應率。
- 五都官方 YouTube 頻道（V12 未解問題 7，這次也沒做）。
