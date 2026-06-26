<!--
手寫雙語專案敘事（首頁用）。直接編輯此檔即可改首頁敘事，不必動程式碼。

格式：兩個區塊，以 `<!-- lang:zh -->` / `<!-- lang:en -->` 標記分隔。
每個區塊內是純 markdown，builder 會各自渲染成 HTML 並提供 EN／中 切換。
雙語策略：只有專案敘事中英切換；每日報告與存檔維持繁中。
-->

<!-- lang:zh -->

## 這是什麼

一套**本地 LLM 多代理自主系統**。每天清晨，它在我自己的機器上自主醒來，
從 Hatena、Hacker News、Reddit、資安部落格與 RSS 五個來源策展出「當日值得關注的技術趨勢」，
寫成一份完整報告、同步進筆記庫，並把精華推播到 Telegram。整條流程不依賴任何雲端推理服務。

## 架構亮點

- **多代理 pipeline**：抓取、語義去重、跨來源壓縮、留言增強、深度摘要、品質評審到發佈，
  各階段職責單一、可獨立執行與測試。
- **冪等步驟**：每一步把結果存成當日 artifact，重跑時自動略過已完成步驟；
  單一步驟可用 `--force` 強制重算、用 `--only` 單獨執行。補跑安全、不重抓資料。
- **韌性而非脆弱**：任一來源失敗不會中斷整條流程；只要 ≥2 個來源成功就照常產出報告，
  系統優雅降級而非全盤崩潰。
- **可觀測性**：每次執行留下健康記錄，跨天偵測慢性故障才主動告警，偶發抖動靜默吞下，
  不製造告警疲勞。
- **LLM-as-Judge 自評**：產物以 relevance／completeness／faithfulness 三軸自我評分並逐日記錄，
  讓品質可被追蹤而非憑感覺。

設計理念：倉庫即記錄系統、地圖而非手冊、選無聊技術、單一失敗不阻塞全局。

<!-- lang:en -->

## What this is

A **local-LLM multi-agent autonomous system**. Every morning it wakes up on my own machine and
curates the day's notable technical trends from five sources — Hatena, Hacker News, Reddit,
security blogs and RSS — into a full report, syncs it into my notes, and pushes the highlights
to Telegram. The whole pipeline runs without any cloud inference service.

## Architecture highlights

- **Multi-agent pipeline**: fetch, semantic dedup, cross-source compression, comment enrichment,
  deep digest, quality judging and deploy — each stage has a single responsibility and can be
  run and tested in isolation.
- **Idempotent steps**: every step persists its result as a per-day artifact and is skipped on
  re-run once complete; any step can be re-computed with `--force` or run alone with `--only`.
  Re-runs are safe and never re-fetch data needlessly.
- **Resilient, not brittle**: a single failing source never halts the pipeline; as long as ≥2
  sources succeed the report still ships. The system degrades gracefully instead of collapsing.
- **Observability**: each run leaves a health record; chronic failures are detected across days
  before escalating, while transient flakes are silently absorbed — no alert fatigue.
- **LLM-as-Judge self-scoring**: outputs are self-rated on relevance, completeness and
  faithfulness and logged daily, so quality is tracked rather than guessed.

Design ethos: the repo is the system of record, a map not a manual, boring technology, and no
single failure blocks the whole.
