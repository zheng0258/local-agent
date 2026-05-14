# AGENTS.md

整個專案的路由地圖。`main.py` 根據此文件決定呼叫哪個 agent。

## Agent 路由表

| Agent | 觸發條件 | 入口 |
|-------|----------|------|
| `daily_brief` | `/daily-brief`、`run daily-brief`、`收集今日趨勢`、`跑趨勢收集` | `agents/daily_brief/agent.py` |
| `url_digest` | `/url-digest`、`digest these urls`、`summarize this article`、`幫我摘要這些連結` | `agents/url_digest/agent.py` |

## Tools（確定性，無 LLM）

| Tool | 職責 |
|------|------|
| `tools/fetchers/hatena.py` | Hatena Bookmark IT 抓取（RSS） |
| `tools/fetchers/hn.py` | Hacker News 首頁抓取（playwright-cli） |
| `tools/fetchers/reddit.py` | Reddit 16 子版抓取（Bash curl） |
| `tools/fetchers/security_blogs.py` | 資安部落格抓取（playwright-cli） |
| `tools/fetchers/browser.py` | playwright-cli 共用工具（`_cli_bin`、`_run`、`_wait_for_session`） |
| `tools/notifiers/telegram.py` | Telegram 發送（HTML parse_mode） |
## DailyBrief 步驟

執行順序：`hatena` → `hn` → `reddit` → `security` → `compress` → `digest` → `judge` → `report` → `save` → `notify`

| 步驟 | 說明 | Artifact |
|------|------|----------|
| hatena / hn / reddit / security | fetch + LLM 興趣評分（*** / ** / *） | `steps/{name}.json` |
| compress | 各來源 Python 預篩選 *** 後，LLM 壓縮為 themes + one_liner | `steps/compress.json` |
| digest | 跨來源深度摘要（3–5 行） | `steps/digest.json` |
| judge | LLM-as-Judge 評分（relevance/completeness/faithfulness），slim context | `steps/judge.json` |
| report | 純 markdown 趨勢報告 | `report.md` |
| save | 同步至 Obsidian vault | `vault.done` |
| notify | 發送 Telegram 雙訊息（msg1 分群列表 / msg2 深度摘要前 8 則） | `telegram.done` |

每步驟產生 artifact，重複執行自動略過；`--force <step>` 強制重跑，`--only <step>` 單步執行。

## 新增 Agent

1. 複製 `agents/_template/` → `agents/<name>/`
2. 實作 `agent.py`（`AGENT_NAME`、`run()`）
3. 在本文件路由表新增一行
4. 在 `main.py` SKILL_MAP 新增觸發條件
5. 執行 `python lint/check_agent_interface.py` 驗證

## 新增 Fetcher

1. 複製 `tools/fetchers/_template.py` → `tools/fetchers/<name>.py`
2. 實作 `fetch()` 純函數
3. 若需要 playwright-cli，從 `browser.py` import `_cli_bin`、`_run`、`_wait_for_session`
4. 執行 `python lint/check_fetcher_interface.py` 驗證
