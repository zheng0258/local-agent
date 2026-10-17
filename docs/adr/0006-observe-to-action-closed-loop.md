# 觀測→動作閉環：分層 L0–L5，每層都要有「誰收到、怎麼關」

## Context

2026-10-17 系統性檢查發現：觀測層做得很多（health / judge / usage / run 四份歷史、站台、每週 PM 審查），
但**所有觀測都停在「記錄」**，沒有接到可追蹤、可關閉的動作上：

- **每週 PM 審查（雲端 routine）只是感測器**：prompt 明令只寫報告、不改碼、不開 PR、不開 issue。
  建議以散文寫進 `docs/pm-reviews/`，無 owner、無狀態，同一項 P0 被「連續第 7 次點名」仍無人接手。
- **感測器視野不完整**：只讀 judge / health 歷史，看不到 `run-history.json` / `usage-history.json`，
  因此六天 0 tokens（09-24／09-28／10-04／10-05／10-08／10-15）與報告無超連結都沒被發現。
- **感測器讀錯版本**：排程跑「本機 main」（`agent-prod` worktree），PM 審查讀 origin/main。
  本機 6 個 commit 未 push（含 09-23 已修的 quality_alert 判準擴充與缺席日偵測），週報連三週把
  已修的事報成「P0 未修、0/6 進度」，甚至把新判準造成的 `quality_alert=True` 推論成 LLM 欄位外洩 bug。
- **原有開單鏈路斷線**：analyzer `file-issues` → `needs-triage` → 人工升 `ready-for-agent` → `/tdd-issues`
  的設計（issue #20）靠 `/loop` 觸發，綁在互動 session 上；session 一關就停，issue 最後活動停在 09-23。

根因不是缺感測器，而是**每一層缺「輸出給誰、何時算結束」**。報告是給人讀的散文，沒有關閉語義；
告警是推播，沒有去重與追蹤；只有 issue 同時具備去重 key、狀態、owner、關閉事件。

## Decision

把觀測→動作切成六層，每層明確定義「觸發條件 / 輸出載體 / 由誰關閉」。上層只處理下層兜不住的事。

| 層 | 名稱 | 觸發 | 輸出載體 | 誰關閉 | 現況 |
|---|---|---|---|---|---|
| L0 | 自癒 | 單步 transient 失敗 | supervisor retry、`≥2 來源門檻`、run 內上游失效（ADR 0005） | 系統自身（重試成功即結束） | ✅ 已有 |
| L1 | 資料品質關卡 | 產物結構/內容不合格 | URL 由 id 重建、`strip_invalid_anchors`、judge 三軸門檻、`completeness` 校正 | 系統自身（重生或降級） | ✅ 已有 |
| L2 | SLO 告警 | 慢性故障（7 天 ≥3 次）、缺席日、品質門檻 | Telegram 當日摘要 + chronic escalation（ADR 0001），episode 去重 | 人：看到就處理；episode 結束自然靜默 | ✅ 已有 |
| L3 | 自動開單＋自動關單 | 每日 artifact 異常（analyzer）、每週 PM 審查建議 | GitHub issue，標題即穩定指紋 slug，一律 `needs-triage` | 開：機器；**關：同一感測器證據滿足驗收條件** | 🔧 本 ADR |
| L4 | agent 開 PR＋人審 | issue 被人工升 `ready-for-agent` | `/tdd-issues` 產 commit / PR | 人審 merge | ⚠️ 有 skill，未排程 |
| L5 | 同一感測器驗證 | issue 有對應修復 commit | 下一輪同一感測器在 issue 上 comment「驗證：建議關閉」＋證據 | 人按 close（或 L3 規則自動關） | 🔧 本 ADR |

### L3 的兩個感測器

1. **每日 `[brief-check]`**（analyzer `file-issues`，確定性、artifact 推導）：
   由 crontab 以 `claude -p` 無人值守執行（06:30 / 09:30 兩個時段共用當日 stamp，pipeline 未結束則讓給下一時段），
   取代綁 session 的 `/loop`。wrapper 走 `agent-prod` worktree 對齊本機 main，`--permission-mode dontAsk`
   只放行讀檔與 `gh issue` 指令。
2. **每週 `[pm-review]`**（雲端 routine，判斷型）：
   - 證據加上 `run-history.json` / `usage-history.json`，並掃「不可能狀態」（LLM 步 ran 但 0 tokens、
     scheduled run 耗時過短、四份歷史同日缺漏、deploy 兩處記錄矛盾）。
   - **第 0 步先對帳**：上週建議逐條以程式碼現狀（檔案:行號 / commit）判斷已修與否；再以
     `run-history.json` 的 `git_sha` 比對 origin/main，生產 SHA 不在 origin 上即視為「看到的程式碼落後」，
     行為與程式碼不符時優先歸因於未 push，不得推論成 bug。
   - 每條建議產生穩定 slug `[pm-review] <subject>: <problem-type>`（subject 取固定詞彙），以
     **標題完全相等**查重：命中 open → comment 追加證據；命中 closed → 開新單註明「復發，前案 #N」；
     未命中 → 開新單。報告散文保留，但改引用 `#N`，「第幾次點名」由 issue 存活時間取代。
   - 雲端環境 GraphQL 被擋，一律走 `gh api` REST；寫入失敗時把預定動作寫進報告，下週先補。

### 關單規則（L3 / L5）

- **`[pm-review]`（判斷型）：只建議、不自關。** 驗證通過時 comment「建議關閉」＋證據，由人按 close。
  理由：建議本身可能錯（10-12 那份就把已修的判準誤判為 bug），讓 LLM 自關會把錯誤判斷變成錯誤狀態。
- **`[brief-check]`（確定性）：目標是自動關。** slug 與異常偵測都是由 artifact 機械推導，
  「連續 3 天同一 slug 未再偵測到」即可安全自關並 comment 證據。此規則**尚未實作**（現行 skill 寫「不自動關單」），
  列為後續任務；在那之前 PM 審查的 L5 驗證也會掃 `[brief-check]` 單並建議關閉，避免殭屍單。
- 任何層都只貼 `needs-triage`；升 `ready-for-agent` 永遠是人的決定——這是 L3 與 L4 之間唯一的人工閘門，
  讓「機器開單」不會直接變成「機器改碼」。

## Considered Options

- **讓 PM 審查直接開 PR 修碼** — 否決：判斷型感測器的誤判率不低（見上），且雲端看不到本機狀態；
  修碼應經過 issue + 人工 triage 再進 L4。
- **只把報告寫得更好（加表格、加 owner 欄）** — 否決：報告沒有狀態機，寫得再好也無法回答「這件事關了沒」。
- **所有觀測改走 Telegram** — 否決：Telegram 是高打擾、無狀態通道（ADR 0001 已限縮成只推慢性故障），
  不適合承載「待辦」。
- **issue 標題用自然語言、靠模糊搜尋查重** — 否決：每週措辭漂移就會開重複單；穩定 slug ＋ 精確比對才有去重保證。

## Consequences

- 閉環的「關」端第一次有了定義：每張機器開的單都帶驗收條件，下一輪同一感測器負責驗證。
- 本機 main 與 origin/main 不同步不再被誤報為「未修」，而是被顯式點名成一張 `prod-sha-not-on-origin` 單。
- 新增外部依賴：cron 中的 `claude -p` 與 `gh` 認證（keyring 讀不到時以 `.env` 的 issue 專用 PAT 補位）；
  crontab 需使用者本人寫入（macOS TCC 擋程式寫 crontab）。
- PM 審查開單量受上限約束（每週新開 ≤5，超過改開彙總單），analyzer 維持每日 ≤5。
- 待辦（不在本 ADR 實作）：`[brief-check]` 連續 3 天乾淨自動關單；`/tdd-issues` 排程化（L4）。
