# 可觀測性：以「慢性故障偵測」而非「每事件告警」呈現健康狀態

## Context

Pipeline 設計上有韌性（`≥2 來源門檻` 撐過部分失敗），但代價是**會默默降級而無人知**。
70 天的 outputs 中約 25% 的執行日觸發過 Alert，但細看幾乎都是 transient flake
（HTTP 4xx/5xx、模型未載完的 connection refused、本地模型偶發吐空）；真正的 code bug
僅 1 次。系統有逐事件的 Alert，卻無法回答「某來源最近**反覆**失敗了嗎」——要回答這問題
得手動 grep 數十天的 `alerts.json`。

## Decision

新增一層可觀測性（`agents/daily_brief/health.py`）：每次執行寫一筆 Health Record 到
`_health-history.json`（形狀鏡像既有的 `_judge-history.json`），記錄 5 個 Source + 2 個遞送
（Telegram / vault）的成功/失敗結果，失敗者分類到 ErrorClass enum。據此**跨天 roll-up**，
只在偵測到「慢性故障」（同一 subject 7 天內失敗 ≥3 次）時主動 escalate，並附帶依錯誤型別
給出的針對性修復建議；同一 episode 只打擾一次。另提供 `--health` pull 查詢印出成功率表。

## Considered Options

- **每週固定健康摘要（push）** — 否決：健康時那封訊息零資訊量，會被無視成雜訊。
- **只做 pull dashboard** — 否決：病根正是「不會主動去看」，pull-only 等於沒解。
- **逐事件就加 retry（robustness 優先）** — 否決：未量測前加 retry 是猜；可觀測性應**先於**強健性，
  讓「哪個來源值得 retry」由數據決定。

## Consequences

- 錯誤分類來自對 `alerts.json` 自由文字的字串比對，**脆弱**；上游改了錯誤訊息措辭可能誤歸到 `other`。
  可接受：分類只驅動「建議文字」，誤分不影響 chronic 判定本身。
- Health Record 由「執行後檢視 artifact / sentinel / alerts」推導，而非各 step 主動上報——
  可觀測性層與 pipeline 解耦，不汙染既有 Step；代價是只能觀察到留下檔案痕跡的結果。
