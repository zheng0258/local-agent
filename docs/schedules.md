# Claude 排程清單

每個排程的 name、cron、description、prompt 集中維護於此。
更新排程時先改此文件，再到 https://claude.ai/code/routines 同步。

---

## daily-brief

| 欄位 | 值 |
|------|-----|
| **Name** | 每日趨勢收集 |
| **Cron** | `30 18 * * *`（UTC）= 每日 02:30 Asia/Taipei |
| **Model** | claude-sonnet-4-6 |
| **Repo** | https://github.com/zheng0258/local-agent |
| **Enabled** | true |

### Description

執行 daily-brief pipeline（hatena / HN / Reddit / security / RSS → dedup → compress → enrich → digest → judge → report → save），所有步驟 artifact 驗證通過後才發送 Telegram 通知。

LM Studio 未就緒時 `main.py` 會自動嘗試喚醒（open + lms server start），最多等 3 分鐘；仍失敗則發 Telegram 告警並中止，不執行 notify。

### Prompt

```
你是一個本地自動化 agent。請在 $HOME/Workspace/agent 專案執行每日趨勢收集，並在所有步驟驗證通過後才發送 Telegram 通知。

## 執行 Pipeline（不含 notify）

cd $HOME/Workspace/agent
python3 main.py "/daily-brief --only hatena hn reddit security rss dedup compress enrich digest judge report save"

main.py 會自動處理 LM Studio 啟動與模型載入，無需手動確認。
若 LM Studio 無法在 3 分鐘內就緒，main.py 會自行發送 Telegram 告警並中止。

## 驗證所有步驟

執行完成後，確認今日輸出目錄的以下 artifact 均存在且非空：

TODAY=$(date +%Y-%m-%d)
DIR=$HOME/Workspace/agent/outputs/daily-brief/$TODAY

必須通過的檢查：
1. $DIR/steps/hatena.json     — 存在且 > 100 bytes
2. $DIR/steps/hn.json         — 存在且 > 100 bytes
3. $DIR/steps/reddit.json     — 存在且 > 100 bytes
4. $DIR/steps/security.json   — 存在且 > 100 bytes
5. $DIR/steps/compress.json   — 存在且包含 themes 欄位
6. $DIR/steps/enrich.json     — 存在且 > 100 bytes
7. $DIR/steps/digest.json     — 存在且 > 100 bytes
8. $DIR/steps/judge.json      — 存在且包含 relevance 欄位
9. $DIR/report.md             — 存在且字元數 > 500

若任何一個驗證失敗，停止並回報失敗的步驟，不執行 notify。

## 發送 Telegram（僅驗證全部通過後執行）

cd $HOME/Workspace/agent
python3 main.py "/daily-brief --only notify"

## 回報結果

- 成功：列出每個步驟的 artifact 大小，以及「✓ Telegram 通知已發送」
- 失敗：詳細列出哪個步驟失敗、錯誤原因，以及「✗ Telegram 通知未發送」
```

### 版本紀錄

| 日期 | 變更 |
|------|------|
| 2026-05-31 | 移除「環境確認」前置步驟，改由 `main.py` 自動喚醒 LM Studio（`ensure_llm_ready`） |
| 初始 | 建立排程，含手動 curl 確認 LM Studio |
