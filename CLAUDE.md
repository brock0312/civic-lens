# civic-lens

開始工作前先讀 [`docs/HANDOFF.md`](docs/HANDOFF.md)：現況、操作方式、規則與接下來的工作都在那裡。

最重要的規則（細節見 HANDOFF §3）：

- 只推 main，不要 `git push --all`；新環境先安裝 `scripts/git-hooks/pre-push`。
- 生日不進公開 dump；未審閱通過的質詢摘要不 commit、不上線。
- ETL 只能在本機（臺灣網路）跑，GitHub Actions 只負責測試與部署。
- 不轉載第三方前科資料庫內容；不顯示「無前科」；不評分、不排名。
- 測試是否通過一律看 exit code。
- 研究知識庫：本專案研究前不查 ~/dev/projects/research（沒有 civic 領域），專案知識以 docs/validation/ 與 docs/HANDOFF.md 為準；[kb] hook 的查庫提醒在本專案不適用。研究完成後不自動回寫，於 session 結束時一次列出可回寫的結論，問使用者是否用 kb.py inbox 回寫；subagent 不自行回寫。
