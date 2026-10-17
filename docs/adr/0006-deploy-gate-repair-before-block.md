# Deploy 前資料品質關卡：先修復、修復失敗才擋

## Context

pipeline 的韌性設計（≥2 來源門檻、失敗回 default）讓壞資料也能一路走到 deploy，health
照樣全綠。2026-10 實例：快取重跑把六天 token 帳本覆寫成 0；`report.md` 的
`[標題](@@id@@)` token 因標題含 `[..]` 或 LLM 漏寫 `[` 未替換就上站（09-24 / 09-28 / 10-16）。
系統沒有任何「不可能狀態」檢查。

第一版關卡（`invariants.py`）偵測到違規就擋 deploy。但使用者要求：**要有修復的路徑，
修復失敗再說**——內容壞掉的那天直接停站，讀者看不到當天任何內容，代價高於「先試著修」。

## Decision

`deploy_gate.run_gate` 依違規類型分流：

| 違規 | 修復路徑 | 修不好時 |
|---|---|---|
| `leftover_token` / `unlinked_articles`（發佈內容） | ① 確定性 relink（`report_repair`：ReportStep 同一套 id 枚舉重替換 token；降級純文字列以**唯一**標題比對補連結）② 仍壞 → 以 reflect context 強制重跑 ReportStep **一次**（LLM） | 記 `invariants` alert + manifest `deploy=blocked`，擋 deploy |
| `zero_tokens`（帳本） | 無（不擋，只記 `ledger` alert） | — |

- **確定性優先**：URL 是資料不是 LLM 輸出（`links.py`），壞連結幾乎都能從 enrich / digest
  找回。歷史資料試跑：06-04、06-23 全數修好，06-24 修好 30/31（剩 1 列標題比對不唯一 → 交給 LLM 層）。
  標題比對寧缺勿錯：完全相符優先、子字串相符需 ≥ 8 字，任一層不唯一就不補。
- **LLM 重跑只一次**：避免無界迴圈與 token 消耗；第二次仍失敗即視為修不好。
- **zero_tokens 不擋**：這是觀測帳本的問題，不是發佈內容的問題——報告本身是好的，擋站只會
  讓讀者看不到正確內容；token 數也無法事後重建，沒有可靠的自動修復。結構性根除另由
  event-ledger 重構處理。alert 鍵刻意用 `ledger` 而非 `invariants`，避免 health 把 deploy
  誤判為被擋。
- **修復不靜默**：修好時 log + manifest `invariants=repaired`，並重落觀測快照，運行紀錄頁
  當天即顯示 🔧。
- **關卡不反噬 pipeline**：檢查本身出錯 → 放行；修復出錯 → 視為修不好（往下一層 / 擋）。

## Consequences

- 修復失敗後的長期政策**尚未定案**（使用者：「修復失敗再說」）。目前維持「擋 deploy + 告警」；
  可能的替代：改發佈前一版站台並標示、或依違規比例決定是否放行。
- 修復發生在 SaveStep 之後：vault 內的 report.md 仍是修復前版本（僅站台拿到修好的版本）。
- 檢查依賴 report 的文字形狀（清單項 / 表格列 + `(N users)` / `(Npt)` / `(N ups)` 標記）；
  若 report prompt 改格式，`invariants.ARTICLE_MARKER_RE` 需同步。
