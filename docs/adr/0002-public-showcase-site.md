# 從 local-agent 自身 repo 的 gh-pages 發佈公開展示站（repo 轉 public）

## Context

需要一個對外的履歷副件，介紹本專案並每日呈現 Brief 結果（見 CONTEXT.md「對外展示」）。
這要求網站必須**公開可見**，且「每日結果」要持續更新。pipeline 在本機 02:00 由 cron 跑，
`outputs/` 被 gitignore、不在 repo 內，因此「GitHub Actions 從 repo 內 report.md build」這條路不通——
發佈只能由本機 deploy step 直接把產物推上 GitHub。

「網站放哪個 repo」同時決定隱私邊界：發佈成公開站意味著託管它的 repo 必須 public。

## Decision

直接用 **local-agent 自身 repo 的 `gh-pages` branch** 作為 GitHub Pages 來源；**local-agent 轉為 public**。
本機新增 deploy step（gate 在今日 Brief 成功），每天重建**全部歷史**存檔成靜態站，force-push 到 `gh-pages`。
main branch 只留原始碼，不被每日自動 commit 汙染。

連帶接受**原始碼一併公開**：上線前必做一次 secret sweep（確認 `.env` 未進 git、
prompts/`interests.txt`/`CLAUDE.md` 內無敏感資訊），作為轉 public 的硬性 gate。

## Considered Options

- **專用公開 repo（如 `zheng0258.github.io` / `daily-brief-site`）** — 否決：雖能讓 local-agent 維持 private、
  隱私與展示解耦，但要管兩個 repo、跨 repo push 憑證更麻煩；且本案接受「原始碼即賣點」，公開源碼反而加分。
- **main 的 `docs/` 資料夾發佈** — 否決：每日自動 commit 會汙染 main 歷史；`gh-pages` force-push 讓產物與源碼歷史分離。
- **GitHub Actions 從 repo build** — 否決（非真選項）：`outputs/` gitignore 且 pipeline 在本機，repo 內無資料可 build。

## Consequences

- local-agent 一旦 public，歷史即公開、難以完全收回；secret sweep 成為不可略過的前置。
- `gh-pages` 由本機 force-push，是「最新本機狀態的鏡像」而非增量 commit——歷史不可追溯，可接受（產物本就由 `outputs/` 重生）。
- deploy gate 在今日成功：若連續多日無新 Brief（如改 interests 重跑期間），公開站會停在最後成功日，不會倒退或顯示空白。
- 多一條對外遞送（Deploy），與 Telegram／vault 平行；納入既有 Step gating，失敗不 block 其他遞送。
