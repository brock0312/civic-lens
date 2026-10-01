# 公開前審查：repo 公開與 GitHub Pages 上線

> **結論**：有 **2 個阻擋項**，都能在一天內修完。
>
> - **B1**：下一次 ETL commit 會把 53 位議員的完整生日寫進公開的 git 歷史，而且無法收回。這一項**阻擋啟用 workflow，也阻擋 commit 任何新的 dump**。
> - **B2**：網站沒有更正與當事人聯絡管道，免責聲明也不足。這一項**阻擋啟用 Pages**，不阻擋 repo 本身公開。
>
> **沒有發現機密外洩**：全部 26 個 commit 都掃過，沒有 token、金鑰、密碼、`.env` 或 cookie jar。前端的 XSS 防護**可接受**。
>
> 另外有兩項建議修正**只能在第一次 push 前低成本處理**：commit 作者信箱，以及測試 fixture 裡的真實生日。push 之後再改寫歷史，fork、快取與封存站都已經有副本，改了也收不回來。

審查日期：2026-09-30　審查者：`security-executor`（依 PLAN §6 第 4 點）
審查基準：`HEAD` = `f31d295`；dump 以 `git show HEAD:data/civic.sql` 為準（ETL 正在主目錄重跑）
範圍：repo 全部內容、完整 git 歷史、`.github/workflows/daily.yml`、`site/`
**法律判斷一律標示「需法律專業確認」**。審查者不是律師，以下只把風險講具體，不構成法律意見。

## 總表

| # | 項目 | 結論 |
|---|---|---|
| 1a | git 歷史中的機密 | ✅ 可接受 |
| 1b | `.gitignore` | ✅ 可接受 |
| 1c | commit 作者信箱與本機使用者名稱 | ⚠️ 建議修正（push 前） |
| 2a | `person.birth_date` 進入 dump | 🚫 **阻擋公開（B1）** |
| 2b | 測試 fixture 內 2022 公報的生日、出生地 | ⚠️ 建議修正（push 前） |
| 2c | `data/identity.csv` 的 `verified_by` | ✅ 可接受（附一點措辭建議） |
| 2d | 其他 dump 內容（姓名、黨籍、質詢標題） | ✅ 可接受 |
| 3 | GitHub Actions 權限與 Pages 部署 | ⚠️ 建議修正 |
| 4a | 免責聲明與更正管道 | 🚫 **阻擋 Pages 上線（B2）** |
| 4b | 黨徽 | ⚠️ 建議修正（低成本，降低風險） |
| 4c | council2026.taiwangogo.tw 外部連結 | ✅ 可接受（依下方條件） |
| 4d | 政府開放資料的顯名聲明 | ⚠️ 建議修正 |
| 5 | 前端 XSS | ✅ 可接受 |

---

## 1. 機密

### 1a. git 歷史：✅ 可接受

```
$ git rev-list --all | wc -l                     → 26 個 commit，分支為 main 與 worktree-agent-a349c88389baf71b3（已合併進 main）
$ git log --all --pretty=format: --name-only --diff-filter=A | sort -u
  → 歷史上出現過 70 個路徑，全部都還在 HEAD；沒有任何被刪掉的檔案（例如曾經 commit 又移除的 .env）
$ … | grep -iE 'env|cookie|jar|secret|key|token|cred|\.pem|\.p12|netrc|scratch|tmp|\.db$'   → 無
$ git rev-list --all | while read c; do git grep -I -n -iE '(api[_-]?key|secret|passw(or)?d|token|bearer|authorization:|cookie|set-cookie|sessionid|PHPSESSID|JSESSIONID|ghp_…|github_pat_|sk-…|AKIA…|AIza…|xox[baprs]-|-----BEGIN)' $c; done
```

- 命中的內容都是**描述 cookie 行為的文件文字**，以及 `etl/sources/tcc_interpellations.py:7,76` 的記憶體內 `http.cookiejar.CookieJar()`，不會寫到磁碟。
- `docs/validation/M4-interpellations.md:30-31` 引用的 `XSRF-TOKEN`、`JSESSIONID` 已截斷成 `0fc6707b-…`、`8C3C…`，而且只是公開網站的匿名 session，沒有風險。
- scratchpad（`/private/tmp/…/scratchpad/`）在 repo 外，裡面的 cookie jar 與原始檔從來沒有進過 git。
- ETL 只用標準函式庫（`urllib`、`sqlite3`、`subprocess` 以參數陣列呼叫 poppler，沒有 `shell=True`）。整個專案沒有讀取任何環境變數或金鑰，**本來就沒有可以外洩的機密**。
- fixture 掃過 `csrf|xsrf|token|jsessionid|__VIEWSTATE`、email、電話格式，全部沒有命中。

### 1b. `.gitignore`：✅ 可接受

`__pycache__/`、`.venv/`、`data/civic.db*`、`site/data/`、`.claude/worktrees/` 都已排除。另外，全域 `~/.config/git/ignore` 已經排除 `.claude/settings.local.json`。專案不使用 `.env`，所以不需要再補規則。

### 1c. commit 作者信箱與本機路徑：⚠️ 建議修正（第一次 push 前）

```
$ git log --all --format='%an <%ae>' | sort | uniq -c   → 26 Brock <<個人信箱>>
$ git grep -n '<scratchpad>' → docs/validation/ 下 7 份文件
```

- **風險**：repo 公開後，26 個 commit 都會帶著個人 Gmail，文件裡的路徑也會洩漏本機帳號名稱。兩者合起來，足以辨識出一個選舉資訊網站的經營者本人。選舉期間，這可能招來騷擾或施壓。另外，如果 GitHub 帳號開啟了「Block command line pushes that expose my email」，push 會直接被拒絕。
- **最小修正**（只有在還沒有 remote 時才便宜）：
  1. `git config user.email <ID>+<帳號>@users.noreply.github.com`
  2. 用 `git filter-repo --mailmap` 改寫既有 26 個 commit 的作者，或者乾脆以單一 initial commit 公開（orphan branch）。
  3. 本機路徑可以用 `sed` 換成 `$SCRATCH/…`。這一項的優先度低，看你是否在意帳號名稱曝光。
- 公開時只推 `main`（`git push -u origin main`），不要 `--all`／`--mirror`，以免把 worktree 分支一起推上去。

---

## 2. 個資

### 2a. `person.birth_date`：🚫 阻擋公開（B1）

**現況**

```
$ grep -c "INSERT INTO \"person\" VALUES('[^']*','[^']*','[0-9]" <(git show HEAD:data/civic.sql)   → 0
$ for c in $(git log --format=%h -- data/civic.sql); do …; done                                    → 歷來各版本都是 0
```

M6 的 merge commit（`f31d295`）**沒有**更新 `data/civic.sql`（dump 最後一次變動在 `b83e709`）。所以 **HEAD 和整個歷史目前都沒有生日**。但只要下一次執行 ETL，生日就會寫進 dump：

- `etl/sources/tcc_councilors.py:110-124`：每次執行都從議會個人頁抓生日，逐一寫進 `person.birth_date`。對象是 `data/identity.csv` 中 53 位 `tcc14` 議員。市長不會被寫入，`run_mayor` 沒有寫生日。
- `etl/run.py:31`：`dump(conn, dump_path)` 用 `iterdump()` 輸出**全部欄位**。
- `.github/workflows/daily.yml:27-29`：每天把 `data/civic.sql` commit 並 push 回 main。

因此，**workflow 啟用後 24 小時內**，或是你**把主目錄正在重跑的 dump commit 進去時**，53 人的完整出生年月日就會進入公開 git 歷史。

**為什麼阻擋**

- 生日**唯一的用途**，是在同一次執行中比對「議會個人頁生日＝公報生日」（`etl/sources/tpe_bulletin_2022.py:472-481`）。前端不輸出（`etl/export.py:15` 只選 `person_id, name`）。而且因為每次執行都會重新抓，**保存在 dump 裡完全沒有功能上的必要**。
- 個資法第 5 條要求蒐集、處理、利用「不得逾越特定目的之必要範圍」。資料來源是官方公開頁面，蒐集本身有第 19 條第 1 項第 3 款（已合法公開）、第 7 款（一般可得之來源）可以依據。但是，把只用於內部比對的生日，以機器可讀的形式公開重製到 repo，很難說是「必要範圍」。
- 姓名加上完整生日，是國內許多身分驗證流程常用的組合。集中成一份可下載的清單，會提高被冒用的風險。
- git 歷史一旦公開就收不回來：fork、clone、GH Archive、Software Heritage 都會留存。
- 修正成本只有幾行，洩漏卻不可逆，所以列為阻擋。
- （需法律專業確認：第 5 條「必要範圍」在民事求償（第 29 條，非公務機關採過失推定）中會怎麼被認定。）

**最小修正（任選其一，建議 A）**

- **A. 生日不進 dump**：在 `etl/db.py` 的 `dump()` 輸出前先清空生日。`civic.db` 每次執行都會從 dump 重建（`etl/db.py:20-21`），而且 `export` 不讀生日，所以直接改正在使用的連線也沒有副作用：

  ```python
  def dump(conn, dump_path):
      # 生日只用於當次執行的身分比對（tpe_bulletin_2022），不公開保存（個資法第 5 條最小化）
      conn.execute("UPDATE person SET birth_date = NULL")
      conn.commit()
      with open(dump_path, "w", encoding="utf-8") as f:
          for line in conn.iterdump():
              f.write(line + "\n")
  ```

  - 加一個測試：`dump` 後的檔案不含任何非 NULL 的 `birth_date`。
  - 不要改用 `conn.backup()` 備份到記憶體副本再清空：實測發現，來源連線還有未 commit 的交易時，`backup()` 會一直卡住。
  - `tpe_bulletin_2022` 在同一次執行裡仍然讀得到 `tcc_councilors` 剛寫入的生日（`etl/run.py:12` 的順序已經保證這一點）。
  - 如果某天議會個人頁抓取失敗，`match_incumbent` 會回傳「議會個人頁沒有生日」並跳過，不會誤寫，既有的 platform/profile facts 也會保留。
- **B. 只存旗標**：`tcc_councilors` 不寫 `person`，改成把生日放在只存在於記憶體的 dict 或 `TEMP TABLE`；比對通過後，在 `person_source_id.verified_by` 記下「2022 公報生日與議會個人頁一致（YYYY-MM-DD 比對）」，**不寫日期本身**。改動範圍比 A 大。

- **再加一道保險**：在 workflow 的 commit 步驟前加上以下檢查，擋住未來其他來源又把生日寫進來：

  ```
  ! grep -qE "INSERT INTO \"person\" VALUES\('[^']*','[^']*','[0-9]" data/civic.sql
  ```

- **在修正合併之前**：主目錄重跑產生的 `data/civic.sql` **不要 commit**。本文撰寫時實測：重跑後工作目錄的 dump 已經有 **53 筆**非 NULL 的 `birth_date`（上面的 `grep -c` 對 `data/civic.sql` 執行），證實這個風險已經發生在本機。

### 2b. 測試 fixture 的 2022 公報個資：⚠️ 建議修正（第一次 push 前）

```
$ grep -c 出生年月日 tests/fixtures/bulletin2022_tp02_raw.txt tests/fixtures/bulletin2022_tp02_bbox.html   → 13、6
$ awk '/^推薦之政黨/{getline p; getline n; print n}' tests/fixtures/bulletin2022_tp02_raw.txt
```

- 兩份 fixture 是 2022 臺北市第 2 選區公報的原文，含 13 位候選人的**完整出生年月日、性別、出生地、學歷、經歷**。其中有 2022 年**落選、現在不是公職**的人，例如江志銘、陳志明、劉榮之。
- `tests/test_tpe_bulletin_2022.py:46,48,131-133` 也寫死了真實生日，例如 `("pA", "江志銘", "1962-08-10", …)`。
- **風險**：公報是依選罷法第 47 條刊登的官方文件，中選會至今仍在公開，所以額外曝光的幅度不大。但把公報內容用在與原目的（告知選民）無關的「測試資料」，並對落選者長期公開，屬於第 20 條特定目的外利用的灰色地帶。修正成本很低。（需法律專業確認。）
- **最小修正**：
  1. fixture 裡所有「出生年月日」的**月、日**改成虛構值（例如 `01月01日`），**年份保留**，讓 `check_against_cec` 的出生年比對測試照樣成立。
  2. 出生地換成虛構值。
  3. 同步修改測試中的預期值。
  4. 這些檔案已經在本地歷史 `68cd2ba` 裡。要清掉，必須和 1c 一起在 push 前改寫歷史，或以單一 initial commit 公開。

### 2c. `data/identity.csv` 的 `verified_by`：✅ 可接受

- 53 筆 `tcc14` 對照都是「名錄 vs 登記冊：姓名、選區、黨籍一致」。其中 2 筆（陳重文、陳怡君）另外引用新聞報導的登記日，佐證他們退黨後以無政黨推薦登記；另 1 筆是市長對照。
- 內容都是公眾人物的公開政治活動。政黨異動不屬於個資法第 6 條的特種個資。這些文字不輸出到前端（`export.py` 不讀 `person_source_id`），但會出現在公開的 repo 與 dump。
- **措辭建議（非必要）**：README 的資料邊界寫「不收媒體傳聞」，但 `verified_by` 引用了新聞。建議在 README 或 `verified_by` 補一句「新聞僅作為人工確認身分的佐證，不作為對外顯示的資料」，避免被指為自相矛盾。

### 2d. 其他 dump 內容：✅ 可接受

- `candidacy`（104 筆）、`office`（53 筆）、`interpellation`（5,391 筆）、`village_district`、`district`：全部是現任民代、候選人的公開職務與公開問政紀錄，每筆都附官方出處。
- 書面質詢標題照錄議會公報，其中有少數涉及第三人事件，例如「邱姓男子」「紀○聰」「劉姓保母」。這些已經由議員在公報中去識別化，本站原文照錄公文（著作權法第 9 條），可以接受。仍然要由 4a 的更正管道承接可能的申訴。
- 身分證、手機、email 格式都掃過（`grep -oE '(^|[^0-9A-Za-z])([A-Z][12][0-9]{8}|09[0-9]{8}|…)'`），沒有真實命中。原本的命中全部來自 URL 裡的十六進位 ID。

**個資法第 19、20 條的依據（PLAN §6 第 4 點；需法律專業確認）**

| 條文 | 本站的依據 | 注意 |
|---|---|---|
| 第 19 條第 1 項（蒐集、處理） | 第 3 款「其他已合法公開之個人資料」、第 7 款「取自於一般可得之來源」；輔以第 6 款公共利益 | 第 19 條第 2 項：當事人依第 7 款但書要求禁止處理時，要能夠停止或刪除，所以需要 4a 的聯絡管道 |
| 第 20 條第 1 項（利用） | 選舉公報、候選人名冊、議會公報的公開目的，本來就是讓公眾知悉，與本站目的一致；即使被認為是特定目的外利用，也可以援引第 2 款「為增進公共利益所必要」 | 生日、落選者資料難以用這一點正當化，所以有 2a、2b |
| 第 9 條（告知義務） | 第 2 項第 2 款：已合法公開的個資，得免告知 | 仍然建議放上隱私說明（見 4a），有助於證明依誠實信用方法處理 |
| 第 11 條（正確性） | 第 1 項：主動或依請求更正；第 2 項：正確性有爭議時停止利用，或「註明其爭議」 | 「當事人說明」要能在頁面上註記爭議 |
| 第 3 條（當事人權利） | 查詢、閱覽、複本、補充更正、停止、刪除，不得預先拋棄 | 需要可以聯絡的管道 |

- 個資法近年有修正（包含設立個人資料保護委員會），條號與要件請以最新條文確認。
- 日後上線 G5（前科）時，資料屬於第 6 條的特種個資，要件更嚴格，要另外審查。

---

## 3. GitHub Actions：⚠️ 建議修正

**現況**（`.github/workflows/daily.yml`）

| 行 | 內容 | 問題 |
|---|---|---|
| 8-9 | workflow 層級 `permissions: contents: write` | 所有步驟，包括解析外部 PDF 的步驟，都拿得到可以寫入的 token |
| 15 | `actions/checkout@v4` | 預設 `persist-credentials: true`，token 會寫在 `.git/config`，ETL 期間任何程式碼都讀得到 |
| 19-21 | 安裝 poppler，執行 ETL | 用 poppler（C 程式）解析從政府網站下載的 PDF／HTML；也就是用有寫入權限的 job 處理**外部輸入** |
| 23 | `if: ${{ !cancelled() }}` | 測試失敗時也會進到這一步（不過 ETL 沒跑，dump 不會變）；ETL 部分失敗時會 commit 部分結果（這是原本的設計） |
| 15-16 | tag 釘版，沒有釘 SHA | 兩者都是 GitHub 官方 action，風險較低 |

**具體失敗情境**：政府網站遭入侵，或被中間人竄改（ETL 走 HTTPS，所以後者機率低），投放一份觸發 poppler 漏洞的 PDF。攻擊者就能在 ETL 步驟執行程式，讀到 `.git/config` 裡的 `GITHUB_TOKEN`，接著：

- 直接 push 修改 `site/app.js`，下一次部署時對所有選民的瀏覽器執行任意 JS；
- 或者在選舉期間竄改候選人資料。

`GITHUB_TOKEN` 不能修改 `.github/workflows/`，但 `site/` 與 `etl/` 都改得動。發生機率低，但影響是選舉期間的網站被竄改。現在本來就要改寫這個檔案來加上 Pages，順手修正的成本最低。

**最小修正：拆成三個 job，權限各自在 job 層級宣告**

```yaml
permissions: {}            # workflow 預設沒有任何權限

jobs:
  etl:                     # 處理外部輸入：唯讀，不留 token
    permissions: { contents: read }
    steps:
      - uses: actions/checkout@<SHA>   # v4
        with: { persist-credentials: false }
      - … 安裝 poppler、跑 unittest、跑 etl.run
      - run: '! grep -qE "INSERT INTO \"person\" VALUES\(''[^'']*'',''[^'']*'',''[0-9]" data/civic.sql'   # B1 保險
      - uses: actions/upload-artifact@<SHA>
        with: { name: dump, path: data/civic.sql }

  commit:                  # 只搬一個檔案，不執行 repo 以外的內容
    needs: etl
    if: ${{ !cancelled() && needs.etl.result != 'skipped' }}
    permissions: { contents: write }
    steps:
      - uses: actions/checkout@<SHA>
      - uses: actions/download-artifact@<SHA>
        with: { name: dump, path: data }
      - run: |   # 原本第 25-29 行的 git add / commit / push，只 add data/civic.sql

  deploy:
    needs: commit
    permissions: { contents: read, pages: write, id-token: write }
    environment: { name: github-pages, url: ${{ steps.d.outputs.page_url }} }
    steps:
      - uses: actions/checkout@<SHA>
        with: { ref: main }   # 取 commit job 剛推上去的版本
      - run: python -c "…open_db 由 dump 重建後呼叫 export(conn, 'site/data')…"
      - uses: actions/upload-pages-artifact@<SHA>
        with: { path: site }  # 只上傳 site/，不要以 repo 根目錄部署
      - id: d
        uses: actions/deploy-pages@<SHA>
```

重點與理由：

1. **處理外部輸入的 job 沒有寫入權限，也不保留 token**。遭入侵時，最多只能竄改 `civic.sql` 的內容，而前端會跳脫輸出（見 5）。
2. **commit job 只複製 `data/civic.sql` 一個檔案**，所以攻擊者沒辦法藉此推送程式碼。
3. **deploy job 以 main 上的程式碼重建 `site/data`**，不沿用 ETL job 產出的網站檔案。
   - 殘餘路徑：deploy 會對 dump 執行 `executescript`（`etl/db.py:26`）。被竄改的 dump 可以用 `ATTACH DATABASE 'site/x.html'` 在 `site/` 裡新增檔案，再跟著部署出去。
   - 防法：在 `open_db` 的 `connect()` 之後加一行 `conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)`（Python 3.11 以上），禁止 ATTACH。
4. **只部署 `site/`**。不要用「Deploy from branch」以根目錄發布，否則 `docs/`、`tests/`、`data/civic.sql` 都會出現在網站網址下。
5. **釘 SHA**：`actions/*` 是 GitHub 官方 action，風險較低，但釘 SHA 的成本也低，建議全部釘，並用 Dependabot（`package-ecosystem: github-actions`）更新。**不要引入非官方的部署或 commit action**，例如 `peaceiris/actions-gh-pages`、`git-auto-commit-action`；目前用原生 git 指令就夠了。
6. **repo 設定**（一次性）：
   - Settings → Actions → General → Workflow permissions 設為「Read repository contents」，讓日後新增的 workflow 預設唯讀。
   - 開啟 Secret scanning 與 Push protection（公開 repo 免費）。
7. **cron 直接 commit 回 main 是否安全**：拆開之後可以接受。沒有 `pull_request`／`pull_request_target` 觸發，fork 無法觸發這個 workflow；`workflow_dispatch` 也只有具寫入權限的人能執行。如果日後替 main 設定需要審查的分支保護，`GITHUB_TOKEN` 會 push 失敗，屆時要改成讓 bot 繞過，或把資料放到獨立的分支。

---

## 4. 網站內容的法遵

### 4a. 免責聲明與更正管道：🚫 阻擋 Pages 上線（B2）

**現況**（`site/index.html:25-30`）：頁尾只有三項：

- 資料來源（只列中選會、北市選委會，沒有臺北市議會）；
- 「只呈現法定公開資料與出處，不評分、不排名、不做政治立場判斷」；
- 更新時間。

`site/app.js:29,121` 會在頁尾補上黨徽來源。

**缺少的項目與具體風險**

| 缺少 | 具體風險 |
|---|---|
| 更正與當事人聯絡管道 | 當事人無法行使個資法第 3 條、第 11 條、第 19 條第 2 項的權利；PLAN §6 第 3 點也列為護欄。選舉期間資料有誤而對方聯絡不上本站，最可能演變成檢舉或訴訟 |
| 「非官方網站」聲明 | 網站呈現選區、候選人資料，容易被誤認為選委會的網站 |
| 「以官方原始出處為準」與錯誤可能 | 解析錯誤（例如質詢歸屬錯人、黨籍錯誤）發生在選舉期間，可能被指為選罷法第 104 條「散布謠言或傳播不實之事」。該條要件包含「意圖使候選人當選或不當選」，有公開的更正流程，能用來證明沒有這種意圖（需法律專業確認） |
| 經營者身分與利益揭露 | 「中立」的說法沒有可以檢驗的依據 |
| 隱私說明 | 本站沒有 cookie、也沒有分析工具（`site/index.html` 沒有第三方 script，已確認），但 GitHub Pages 會記錄存取 IP，應該說明 |
| 資料來源不完整 | 人物頁使用臺北市議會的資料，但頁尾沒有列出（各頁腳註有列） |

**建議文字（頁尾，短版）**

> 本站是個人維運的非官方網站，與中央選舉委員會、各地方選舉委員會、各議會，以及任何政黨、候選人都沒有隸屬或合作關係，也沒有接受政黨或候選人的資助。
>
> 本站只收錄法定公開資料，每筆都附原始出處與擷取時間。資料可能因為來源更新，或本站擷取、解析錯誤，而與原始文件不一致，一律以原始出處的官方公告為準。
>
> 本站不評分、不排名、不做政治立場判斷。列出或未列出任何紀錄，都不代表對任何人的評價。
>
> 資料來源：中央選舉委員會、臺北市選舉委員會、臺北市議會、內政部（政黨標章）。
>
> 資料更正與當事人說明：〔專用信箱〕｜〔更正與說明〕頁｜隱私說明

- 「沒有接受政黨或候選人的資助」這一句，**只有在屬實時才寫**。
- 聯絡信箱請另外開一個專用信箱，**不要用個人 Gmail**（理由同 1c）。

**建議文字（「更正與當事人說明」頁）**

> **更正與當事人說明**
>
> **如何聯絡**：請寄信到〔專用信箱〕，註明頁面網址、有誤的資料與正確資料的出處。
> - 非個資的一般錯誤（例如連結失效），也可以在 GitHub Issues 回報。Issues 是公開的，涉及個人資料的請求**請不要**用 Issues。
>
> **處理時限**：本站會在收到後 〔3〕 個工作日內回覆。選舉期間（〔登記截止日〕至投票日）縮短為 〔1〕 個工作日。
>
> **本站的錯誤**：如果是本站擷取或解析錯誤，會直接更正，並在該筆資料旁註記更正日期。
>
> **原始資料有爭議**：如果您認為官方原始資料本身有誤，本站不會改動官方原文，但會在該筆資料旁標示「當事人對此有異議」，並附上您的說明。同時建議您向原發布機關申請更正；原機關更正後，本站會在下一次每日更新時同步。
>
> **當事人說明**：候選人或民意代表本人，可以針對與自己有關的資料提出說明。
> - 說明以 〔300〕 字為限，原文照登並標註日期，不包含對他人的指控。
> - 本站以同樣的規則處理所有人。
> - 為了避免冒名，本站會請您以可驗證的方式確認身分，例如服務處或官方信箱來函。
>
> **個人資料權利**：依個人資料保護法第 3 條，您可以請求查詢、閱覽、製給複本、補充或更正、停止蒐集處理利用，或刪除您的個人資料。
> - 本站收錄的資料都取自已依法公開的來源（同法第 19 條第 1 項第 3 款、第 7 款），用途是讓選民查詢候選人與民意代表的法定公開資料。
> - 本站不收費，會在前述時限內回覆處理結果。
>
> **隱私說明**：本站不使用 cookie，也不做追蹤或流量分析。網站由 GitHub Pages 託管，GitHub 可能依其隱私政策記錄存取紀錄（例如 IP 位址）。

- 〔〕內的時限與字數，是需要你決定的營運承諾，承諾了就要做得到。
- 條號引用需法律專業確認。

### 4b. 黨徽：⚠️ 建議修正（低成本，降低風險）

**依據**：`docs/validation/party-emblems.md` §4。內政部的開放宣告只及於著作權，明文「不及於……商標」；黨徽的著作權與商標權屬於各政黨。

**風險分析（需法律專業確認）**

- **商標**：商標法第 68 條的侵權要件以「為行銷之目的」使用為前提（第 5 條）。本站是非商業的辨識用途，在候選人黨籍文字旁標示該黨標章，並不是把黨徽當作本站自己商品或服務的商標，侵權風險低。另外可以參考第 36 條第 1 項第 1 款的描述性合理使用。各政黨的標章是否真的註冊為商標，要到智慧局查詢確認。
- **著作權**：黨徽是政黨的美術著作。放上網站屬於重製與公開傳輸，要靠著作權法第 65 條第 2 項（合理使用四要素）或第 52 條（引用）。對本站有利的是非營利、辨識目的、已註明出處；對本站不利的是全圖使用。**「利用的質量」是可以壓低的要素**：目前 15 張圖中有 7 張維持原始尺寸，最大是 `tpp.png` 1182×1182。
- **政黨實際提出異議的機率**：低。有異議時的最佳處理，是立刻改成只顯示文字，所以要事先寫好移除承諾。

**最小修正**

1. 其餘 7 張也等比例縮到高 96 px，與前端顯示的 20 px 相比仍有餘裕。只縮放，不改色、不裁切，符合宣告第三、四點。
2. 頁尾的黨徽來源（`app.js:121`）後面補一句：「政黨標章權利屬於各政黨，僅用於辨識候選人的推薦政黨，不代表各政黨認可本站。政黨如果不同意使用，請來信，本站會改為只顯示文字。」

### 4c. council2026.taiwangogo.tw 外部連結：✅ 可接受（依下列條件）

目前 `site/` 還沒有這個連結，以下是加入時的條件。

- **風險**：
  - 單純連結不構成重製，著作權風險低。
  - 主要風險是**名譽與中立性**。該站收錄了起訴、行政罰、民事判決與新聞報導。如果本站在**個別候選人頁面**放連結，或在網址帶入候選人姓名，就等於暗示「此人有紀錄」。一旦指向的內容不實，本站可能被指為共同散布（需法律專業確認）。
  - 此外，該站與 4 個參選政黨合作，中立網站連過去，會有觀感問題。
- **條件**：
  1. 只放**網站層級**的連結，位置在「外部參考資源」區或頁尾，**不放在個人頁**，也不帶任何查詢參數。
  2. 附上揭露式聲明（以下文字的事實部分取自 README，上線前請再核對一次該站的現況）。
  3. 使用 `target="_blank" rel="noopener noreferrer"`，不把本站網址傳給對方。
  4. 同一區塊並列官方查證管道（司法院裁判書查詢），讓「以確定判決為準」的說法有實際可以點的去處，也平衡中立觀感。

**建議文字**

> **外部參考資源**：council2026.taiwangogo.tw（前科資料庫）
>
> - 該網站由台灣前進經營，時代力量代管，並與時代力量、台灣基進、台灣綠黨、小民參政歐巴桑聯盟合作。
> - 收錄範圍包含起訴、行政罰、民事判決與新聞報導。起訴不等於有罪，行政罰與民事判決也不是刑事前科。
> - 本站未查證其內容，提供連結不代表本站認同或背書。
> - 查證刑事判決，請以司法院裁判書查詢系統的確定判決為準。

### 4d. 政府開放資料的顯名聲明：⚠️ 建議修正

- 中選會的資料集以「政府資料開放授權條款第 1 版」釋出（`docs/data-sources/elections-candidates.md:33` 記錄 `license: "1"`）。該條款要求利用者依附件格式提供顯名聲明，而頁尾目前沒有。
- **最小修正**：在頁尾或「關於」頁加上：「本站使用的中央選舉委員會開放資料，依政府資料開放授權條款（Open Government Data License）第 1 版釋出：https://data.gov.tw/license」。
- 其他來源（議會網站、內政部）以各自網站的著作權聲明為準。議會公報屬於公文，依著作權法第 9 條不受保護。
- 日後加入報導者觀測站（CC BY-NC-ND 3.0 TW）時，要附上作者、標題、授權連結，而且本站不得有廣告或募款。募款是否構成 NC 所稱的商業使用，需法律專業確認。

---

## 5. 前端 XSS：✅ 可接受

資料來自政府 HTML／PDF 的解析結果，屬於不受信任的內容。檢查 `site/app.js`：

| 防線 | 位置 | 評估 |
|---|---|---|
| `esc()` 跳脫 `& < > " '` | `:57` | 所有插入 `innerHTML` 的資料欄位都經過 `esc`：姓名、標題、部門、日期、政黨、選區、席次、發布機關。屬性值都用雙引號包住，涵蓋文字與屬性兩種情境 |
| `safeUrl()` 只允許 `^https?://` | `:58` | 所有外部 `href` 都先經過它（`:73`、`:118`、`:246`、`:266`），擋掉 `javascript:`、`data:`。`ext()` 另外再做一次 `esc` |
| 黨徽路徑白名單 `^parties\/[\w.-]+$` | `:30` | `index.json` 被竄改時，也無法指到外部或 `javascript:` |
| hash 路由 ID 白名單 `^[\w-]+$` | `:130`、`:360` | 防止 `data/people/${id}.json` 路徑穿越 |
| 內部連結 `#/d/${esc(id)}` | `:166`、`:297` | 開頭固定是 `#/`，不會變成其他 scheme |
| 沒有用 `esc` 的插值 | `:83`、`:98` 的 `fmtDate()` | 輸出是 `Intl.DateTimeFormat` 的結果，只會有數字與 `-`；無效日期會丟出 RangeError，進入 `renderError`，不構成注入 |
| 外部連結 | `:59` | `target="_blank" rel="noopener"`，沒有 reverse tabnabbing |

- 沒有 `eval`、`new Function`、`document.write`，也沒有第三方 script。
- 可選：用 `<meta http-equiv="Content-Security-Policy" content="default-src 'self'; object-src 'none'; base-uri 'none'">` 作為縱深防禦。加上之前要先把 `app.js:177` 的行內 `onsubmit="return false"` 改成 `addEventListener`，否則會被 CSP 擋下。
- 注意：M6 的 `platform`／`profile` facts 目前前端還沒有渲染。之後加入時，公報政見全文同樣必須經過 `esc`，換行請用 CSS `white-space: pre-line` 處理，不要把 `\n` 換成 `<br>` 後直接插入。

---

## 附：建議修正的優先順序

1. **B1**（阻擋）：生日不進 dump、加測試、加 workflow 保險；主目錄這次重跑的 dump 先不要 commit。
2. **1c＋2b**（只有 push 前便宜）：作者信箱改成 noreply，fixture 的生日與出生地改成虛構值，然後改寫歷史，或以單一 commit 公開。
3. **3**：workflow 拆成三個 job、`persist-credentials: false`、`SQLITE_LIMIT_ATTACHED = 0`、只部署 `site/`、repo 預設唯讀並開啟 push protection、釘 SHA。
4. **B2**（阻擋 Pages）：頁尾聲明、更正與當事人說明頁、專用信箱。
5. **4d**：政府資料開放授權的顯名聲明。
6. **4b**：黨徽全部縮圖，並加上移除承諾。
7. **2c**：`verified_by` 引用新聞的措辭說明。

## 需要人工或法律專業確認的事項

- 個資法第 5、19、20 條對「公開重製生日」「以落選者公報資料作為測試資料」的評價，以及最新修正條文的條號（2a、2b、§2 表）。
- 黨徽的商標註冊狀態（智慧局查詢），以及辨識用途是否屬於合理使用或引用（4b）。
- 連結到第三方前科資料庫時，本站的名譽責任範圍（4c）。
- 選罷法第 104 條在「資料解析錯誤」情境下的適用（4a）。
- 經營者揭露句「未接受政黨或候選人資助」是否屬實（4a）。
