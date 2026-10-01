# M4 驗證：臺北市議會第 14 屆議員名錄與質詢紀錄

> **結論**：✅ **可做，範圍限書面質詢**。現行系統是 `gaz.tcc.gov.tw`（`tcckm.tcc.gov.tw` 已失效：憑證 2025-06-04 過期、連線回空）。書面質詢清單可以用純 GET＋cookie 取得，不需要驗證碼、登入或瀏覽器自動化，也沒有 CSRF 要求（CSRF token 只用在 POST，我們不用 POST）。每份書面質詢都有穩定的**書面質詢稿編號**（例：`AQ14102629`），也有不需 cookie 就能開的**公開 PDF 檢視器 URL**。代價是這兩樣東西不在清單頁，每份文件要多打一次 `doc_viewer`。第 14 屆書面質詢共 2,600 份。現任 53 位議員中，有對照的 50 人名下 1,937 份。第一次回補約 2,000 次請求，以每秒 1 次計約 35–45 分鐘。**市政總質詢、部門業務質詢在公報裡是「第 N 組」整組 4 人左右的速記錄，只有組別標題、沒有各人的質詢主題，無法乾淨歸屬到個人，MVP 不收。**
> 網站著作權聲明允許合理使用與連結（需註明出處），沒有禁止自動化存取；我們只存詮釋資料與連結。

調查日期：2026-09-28　原始檔：`<scratchpad>/m4/`（不進 repo）
所有請求都帶 `User-Agent: civic-lens-etl/0.1`，間隔 ≥ 1 秒。

## 總表

| # | 問題 | 答案 | 狀態 |
|---|---|---|---|
| 1 | 現行系統 | `gaz.tcc.gov.tw`；`tcckm.tcc.gov.tw` 失效 | ✅ 實測 |
| 2 | 程式化查詢 | GET `/search/dq/deptID/result.html`，用 `cst=S&se=14` 限定屆別，`cid=` 限定議員，`pageSize≤40`，`currentPage=N` 翻頁。單筆 `doc_viewer.html?dataIndex=i` 要帶同一個 session 的 cookie。沒有 JSON 搜尋端點 | ✅ 實測 |
| 3 | 清單欄位 | 質詢日期（民國）、部門、屆會次、標題、提案議員（聯名時列多位）、內文摘要、`dataIndex`（綁 session） | ✅ 實測 |
| 3b | 穩定 ID／URL | `doc_viewer` 頁有書面質詢稿編號 `AQ…`，以及 `/pdf/viewer.html?id=<hex>`（跨 session 相同，不需 cookie） | ✅ 實測 |
| 4 | 歸屬到個人 | 書面質詢可以（2,600 份中 2,599 份單一議員，1 份兩人聯名）；總質詢、業務質詢不行（整組速記錄） | ✅ 實測 |
| 5 | 量 | 第 14 屆 2,600 份；每人 0–321 份（中位數約 24）；回補約 65 頁清單＋1,937 次 doc_viewer；每日增量通常 1 頁清單＋幾次 doc_viewer | ✅ 實測 |
| 6 | 再利用條件 | 著作權聲明：得依著作權法合理使用，引用須註明出處；同意任何網站連結，須標示本會名稱。沒有 robots.txt（404） | ✅ 實測 |
| 7 | 議員名錄 | `www.tcc.gov.tw/cp.aspx?n=13898`：53 位現任議員。每個 qtype 頁都含全部 8 個選區，qtype 只決定預設展開哪一區 | ✅ 實測 |
| 8 | 第 14 屆就職日 | 2022-12-25（公報「第 14 屆就職典禮暨成立大會（111 年 12 月 25、26 日）」） | ✅ 實測 |

---

## 1. gaz 與 tcckm 的關係

```
$ curl -sS -L -D - -o gaz.html https://gaz.tcc.gov.tw/
HTTP/1.1 200
Set-Cookie: XSRF-TOKEN=0fc6707b-…; Path=/; HttpOnly
Set-Cookie: JSESSIONID=8C3C…; Path=/; HttpOnly
<title>臺北市議會電子公報全文檢索系統 Taipei City Council Gazette Online</title>

$ curl -sS https://tcckm.tcc.gov.tw/
curl: (60) SSL certificate problem: certificate has expired
$ echo | openssl s_client -connect tcckm.tcc.gov.tw:443 2>/dev/null | openssl x509 -noout -dates -subject
notAfter=Jun  4 05:59:01 2025 GMT
subject=C=TW, L=臺北市, O=市議會, CN=tcckm.tcc.gov.tw
$ curl -skS https://tcckm.tcc.gov.tw/        # 忽略憑證
curl: (52) Empty reply from server
$ curl -sS -m 20 http://tcckm.tcc.gov.tw/
curl: (28) Connection timed out after 20002 milliseconds
```

`tcckm` 仍有 DNS 紀錄（210.69.176.245），但 HTTPS 回空、HTTP 逾時，憑證已過期一年以上，判斷為停用的舊系統或測試站。`gaz.tcc.gov.tw` 首頁的最新資料到 2026-09-24，是現行系統。gaz 內分三個資料庫：「公報」（`/search/gaz/`，公報／議事錄）、「搶鮮報」（`/search/dq/`，書面質詢、會議紀錄、速記錄、市府書面報告）、「7–9 屆公報」（`/search/gaz_old/`）。

## 2. 程式化查詢

### 2.1 清單（GET，只需 cookie）

進階搜尋表單（`/search/adv-search.html`、`/search/councillor-search.html`）是 `method="get"`，參數直接放在 query string：

| 參數 | 意義 |
|---|---|
| `cst=S&se=14` | 屆別＝14（`ti=` 可再限定第幾次會；`ct=` 限定會議種類） |
| `ccond=AND&cname=王欣儀&cid=49116` | 議員。`cid` 是公報系統內部的議員編號，出自 `/finder/councillor/index.html?listType=ALL`（第 14 屆共 61 個 `data-id`＝應選 61 席，表示本屆沒有遞補） |
| `sort=desc&sortField=date` | 依質詢日期新到舊 |
| `pageSize=40&currentPage=N` | UI 下拉選單上限 40；超過頁尾回傳 0 筆 |

```
$ curl -sS -c jar -b jar 'https://gaz.tcc.gov.tw/search/dq/deptID/result.html?sort=desc&sortField=date&ccond=AND&cname=%E7%8E%8B%E6%AC%A3%E5%84%80&cid=49116&sy=Y&sm=N&cst=S&se=14'
HTTP 200；部門 facet：民政 25、財政建設 14、教育 31、交通 12、警政衛生 24、工務 30（合計 136）
$ …（同上，不帶 cst/se）                      → 616 筆（歷屆合計）
$ …/result.html?sort=desc&sortField=date&pageSize=40&cst=S&se=14            → facet 合計 2,600，最後一頁 65
$ …/result.html?sort=desc&sortField=date&pageSize=40&cst=S&se=13            → 4,841
$ …/result.html?sort=desc&sortField=date&pageSize=40                       → 24,949（最早 95-01-24，第 10 屆）
$ …&cst=S&se=14&currentPage=66                                              → 0 筆
```

CSRF：頁面把 `XSRF-TOKEN` 塞進 POST 表單與 `$.ajaxSetup` 的 `X-XSRF-TOKEN` 標頭，但搜尋與翻頁都是 GET，不需要 token。沒有驗證碼，也不需要登入。

### 2.2 有沒有 JSON 端點

把所有頁面與 JS 裡出現的 `.json` 全部列出來：`/check-login.json`、`/index-doc-list.json`、`/index-topic-{cp,mt,rr}-list.json`、`/print/action-file*.json`、`/search/remove-list.json`、`/member/search-his/add.json`。唯一有資料的是首頁用的 `POST /index-doc-list.json`（要帶 `X-XSRF-TOKEN`），欄位非常完整：

```json
{"id":146072,"no":"AQ14102629","date":"20260924","session":"14","times":"08",
 "title":"受監護長者財產遭侵占案凸顯社會局內控機制失靈，…","replier":"臺北市政府社會局",
 "majorCouncillorID":"410703","majorCouncillor":"侯漢廷","subCouncillorID":"","subCouncillor":"",
 "sessionTimes":"第14屆第08次定期大會","pdf":{"name":"AQ14102629.pdf","encodePath":"https://gaz.tcc.gov.tw/s/file/…"}, …}
```

但它每個部門只回最新 5 筆，不能查詢或翻頁。猜測的 `/search/dq/deptID/result.json` 回 404。**結論：沒有可用的 JSON 搜尋端點，要解析 HTML。**

### 2.3 單筆：穩定 ID 與公開 URL

清單上的連結是 `/pdf/index/doc_viewer.html?dataIndex=i`。`i` 是「這個 session 最近一次查詢」結果中的全域序號（第 2 頁從 40 開始），**換 session 就指向別的文件，不能當 ID**。`doc_viewer` 頁裡有兩樣穩定的東西：

```
$ curl -sS -c jar -b jar '…/pdf/index/doc_viewer.html?dataIndex=0&fromPage=1'      # 同 session，先查過清單
200
<iframe id="doc-ifr" title="書面質詢：第14屆第08次定期大會" src="/pdf/viewer.html?id=F626A9A3…4DE7DF3"></iframe>
<h2>書面質詢</h2> <div class="title" id="htitle">第14屆第08次定期大會</div>
<li>部門別：民政</li>  書面質詢稿編號：<a href="javascript:doDoc()">AQ14102629</a>

# 新開一個 session 重查同一份清單，dataIndex=0 → 同一個 viewer id
viewer.html?id=F626A9A3…4DE7DF3

# 不帶 cookie 直接開 viewer
$ curl -sS 'https://gaz.tcc.gov.tw/pdf/viewer.html?id=F626A9A3…4DE7DF3'
200  var tcc_file = "https://gaz.tcc.gov.tw/s/file/D5F1…/9BAA…"; var tcc_name = "AQ14102629.pdf";
$ curl -sS -o /dev/null -w '%{http_code} %{content_type} %{size_download}' 'https://gaz.tcc.gov.tw/s/file/D5F1…/9BAA…'
200 application/pdf 117293
```

- **文件 ID**：書面質詢稿編號 `AQ14102629`，與首頁 JSON 的 `no` 一致。
- **source_url**：`https://gaz.tcc.gov.tw/pdf/viewer.html?id=<hex>`，跨 session 相同，不需 cookie。
- 風險：viewer id 看起來是伺服器端加密後的檔案路徑，網站若換金鑰，舊連結可能失效。書面質詢稿編號不受影響，屆時可用編號重建連結。

公報庫（`/search/gaz/`）的「公報詳細資料」`/search/gaz/gaz-<id>-info.html` 不帶 session 會回 404，所以不適合當公開連結。

## 3. 清單欄位

一筆書面質詢清單項目（`/search/dq/`，裁切）：

```html
<span class="date">115-09-24</span>
<span class="dept">民政</span>
<span class="dept">第14屆第08次定期大會</span>
<a href="/pdf/index/doc_viewer.html?dataIndex=0&fromPage=1" title="另開視窗至:受監護長者財產遭侵占案凸顯社會局內控機制失靈，應全面檢討財產管理及監督制度">
  … <div class="readset"><p>侯漢廷 一、近日發生社會局社工涉嫌…</p></div></a>
<div class="item3"><span class="starpage">侯漢廷</span></div>
```

| 欄位 | 來源 | 備註 |
|---|---|---|
| 日期 | `span.date` | 民國 `yyy-mm-dd`，是質詢日期 |
| 部門 | 第 1 個 `span.dept` | 民政／財政建設／教育／交通／警政衛生／工務 6 類（議會的部門分組，不是市府局處；答覆機關 `replier` 只出現在首頁 JSON） |
| 屆會次 | 第 2 個 `span.dept` | 例：`第14屆第08次定期大會`、`第14屆休會`、`第14屆第07次臨時大會` |
| 標題 | `a[title]` 去掉「另開視窗至:」 | |
| 議員 | `span.starpage`（可多個） | 聯名時列多位 |
| 摘要 | `div.readset p` | 內文前段；**不存** |
| 文件類型 | 查詢分類 `stype=dq` | 清單本身不標示，一律是書面質詢 |
| 穩定 ID／URL | 要再打 `doc_viewer` | 見 2.3 |

## 4. 能不能乾淨歸屬到個別議員

**書面質詢：可以。** 解析第 14 屆全部 65 頁（2,600 份）：2,599 份只有一位議員，1 份兩人聯名（112-02-24 交通「請貴處說明是否有未依法行政與行政怠惰的情事與理由」，陳宥丞、張志豪）。首頁 JSON 也證實系統內部有結構化的 `majorCouncillor`／`subCouncillor`。聯名時每位議員各寫一筆。

**市政總質詢、部門業務質詢：不行。** 它們在「公報」庫，用 `cid` 查得到，但每筆是一整組的速記錄：

```
$ …/search/gaz/gazSubCate/總質詢/result.html?…&cname=王欣儀&cid=49116&cst=S&se=14
第144卷第01期 第14屆第06次定期大會 總質詢 「第 14 屆第6次定期大會市政總質詢第2組」
  質詢日期：中華民國 114 年 11 月 28 日 質詢對象：蔣市長萬安
  質詢議員：林杏兒 游淑慧 詹為元 王欣儀 計 4 位 時間 1660 分鐘 ※速 記 錄 …
$ …/search/gaz/result.html?…&cname=王欣儀&cid=49116&cst=S&se=14
性質 facet：會議紀錄 51、業務質詢 52、總質詢 6、速記錄 23
第14屆第7次定期大會民政部門第1組 … 質詢議員：林杏兒 游淑慧 詹為元 王欣儀 計 4 位 時間 72 分鐘
```

標題只有「第 N 組」，每位議員質詢了什麼，只能從速記錄全文逐段切出來。這需要解析 PDF，也要判斷哪段話是誰說的，不符合「只存詮釋資料」的原則，而且容易切錯。**MVP 不收口頭質詢**。之後如果要收，可以把「參與某次總質詢第 N 組」記成一筆 participation fact，標題寫明是整組，並連到公報原文。

**MVP 也不收**：會議紀錄、速記錄、市府書面報告（非個人質詢）；已離職議員（許家蓓 74、陳政忠 14、徐巧芯 12、李彥秀 10、吳沛憶 10、趙怡翔 6、王世堅 2 份。他們不在現任名錄，也不在 identity.csv）；第 13 屆以前的質詢。

## 5. 量與請求數

- 第 14 屆書面質詢 2,600 份，最早 2022-12-26（第 14 屆成立大會），最新 2026-09-24。
- 現任 53 人的份數：0（6 人：陳錦祥、鍾小平、應曉薇、曾獻瑩、王閔生、徐弘庭）到 321（徐立信），中位數約 24。
- identity.csv 有對照的 50 人名下共 1,937 份。
- **第一次回補**：清單 65 頁（每頁 40 筆）＋每份有對照的文件 1 次 `doc_viewer`，約 2,000 次請求，間隔 1 秒，約 35–45 分鐘。只做一次。
- **每日增量**：依日期新到舊翻頁；碰到 DB 已有的文件（用清單上的日期＋標題＋議員比對，不必打 doc_viewer），把那一頁處理完就停。平常是 1 頁清單＋當天新增幾份的 doc_viewer。上限與升級方式寫在 `etl/sources/tcc_interpellations.py` 的 `# ponytail:` 註解。
- `dataIndex` 綁 session：清單與 `doc_viewer` 必須在同一個 cookie session 內依序請求。程式會拿 `doc_viewer` 回傳的部門與屆會次跟清單比對，不一致就中止，擋掉大部分索引位移。

## 6. 再利用條件

`https://gaz.tcc.gov.tw/cate/0D6BB9816EB3C977/info.html`（著作權聲明，發布日期 113/08/16）：

> 一、著作權保護 1. 臺北市議會電子公報全文檢索系統…上刊載之所有內容，除依著作權法第9條規定不得為著作權標的者外，均受著作權法之保護。2. 本會網站之內容，得依著作權法規定為合理使用；引用時，請註明出處。
> 二、本會網站之連結 1. 除連結將誤導使用或有誤導使用之虞者外，本會同意任何網站得連結至本會網站；連結時，並請標示本會名稱。

`www.tcc.gov.tw`、`gaz.tcc.gov.tw` 都沒有 robots.txt（404），也沒有明文禁止自動化存取。另讀了隱私權政策（`/cate/F1BE032E3FCD9FC6/`）與資通安全政策（`/cate/8DA96AA6836B8E8D/`），都沒有爬取限制條款。
**我們的做法**：只存標題、日期、屆會次、部門、書面質詢稿編號、議員姓名與原文連結，不存摘要與 PDF 全文。前端顯示時要標示「資料來源：臺北市議會電子公報」。公報屬議會公文，多半落在著作權法第 9 條（不得為著作權標的）的範圍，但我們不依賴這一點，只存詮釋資料。

## 7. 議員名錄

```
$ for q in 1..9; curl -sS -o q$q.html 'https://www.tcc.gov.tw/cp.aspx?n=13898&qtype=$q'
q1 200 136028 … q9 200 136102
```

每個 qtype 頁都含 8 個選區區塊，差別只在頁尾 `setTimeout('change_area(<qtype>,true,true)')` 決定預設展開哪一區。所以 ETL 只抓 `cp.aspx?n=13898` 一頁，**選區取自區塊標題**，不從 qtype 推：

```html
<a title="第一選區<br>北投/士林" …>第一選區<br>北投/士林</a> …
<li><a class="div" href="Councilor_Content.aspx?n=13898&s=2547" title="黃瀞瑩">…
  <div class="caption"><img src="images/party_logo11.jpg" alt="台灣民眾黨"><span>黃瀞瑩</span></div></a></li>
```

- 第一～第六選區對應北投/士林、內湖/南港、松山/信義、中山/大同、中正/萬華、大安/文山；第七＝平地原住民、第八＝山地原住民。和 `tpe_candidates` 的 `tpe-council-0N` 一致。
- 黨籍取自黨徽圖的 `alt`。
- 現任 53 人（各區 11/8/6/7/7/12/1/1）。應選 61 席，缺額是任內離職、未遞補的席次。
- 名錄上沒有生日；個別議員頁 `Councilor_Content.aspx?n=13898&s=<id>` 有「出生：民國XX年X月X日」，可以作為日後生日對齊的依據（本次未使用）。

## 8. 就職日

```
$ …/search/gaz/result.html?sort=asc&sortField=date&cst=S&se=14&ct=008106837D6DFBA6D0636733C6861689
第129卷第14期 第14屆第00次成立大會 議員出席情形統計表
「臺北市議會第 14 屆就職典禮暨成立大會（111 年 12 月 25、26 日）議員出席、請假統計表」
```

第 14 屆就職日是 **2022-12-25**，office fact 的 `date` 用這一天。
