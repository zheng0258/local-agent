# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案目標

將 Claude Code Skills 改為可由本地 LLM server 執行的 multi-agent 系統。

## 執行方式

```bash
# 預設：本地 LLM server（http://localhost:1234，模型 qwen3.5-27b-claude-4.6-opus-distilled-mlx）
python3 main.py "/daily-brief"
python3 main.py "幫我摘要這些連結 https://example.com"

# 強制重新執行特定步驟（忽略當日 artifact）
python3 main.py "/daily-brief --force hatena"
python3 main.py "/daily-brief --force hatena hn"
python3 main.py "/daily-brief --force report"   # 重新生成報告（不重抓資料）
python3 main.py "/daily-brief --force notify"   # 重送 Telegram

# 只執行特定步驟
python3 main.py "/daily-brief --only hatena"
python3 main.py "/daily-brief --only report notify"

# 可用 step 名稱：hatena / hn / reddit / security / compress / digest / judge / report / save / notify

# 覆蓋本地 LLM 設定
export LOCAL_LLM_URL=http://localhost:1234
export LOCAL_LLM_MODEL=qwen3.5-27b-claude-4.6-opus-distilled-mlx

# 或改用 Anthropic API
export ANTHROPIC_API_KEY=sk-...
```

## 架構

```
main.py                          # 主入口（路由 + 執行）
AGENTS.md                        # 路由地圖

agents/
├── _template/                   # 新增 agent 的黃金範本
├── daily_brief/                 # 每日趨勢收集
│   ├── agent.py                 # 主流程（並行四來源）
│   ├── prompts.py               # 所有 LLM prompts
│   └── config.py                # 來源設定、門檻、路徑
└── url_digest/                  # URL 摘要
    ├── agent.py
    └── prompts.py

tools/
├── fetchers/                    # 純函數，無 LLM，各來源抓取
│   ├── _template.py
│   ├── hatena.py
│   ├── hn.py
│   ├── reddit.py
│   ├── security_blogs.py
│   └── browser.py              # playwright-cli 共用工具（hn / security_blogs 使用）
└── notifiers/
    └── telegram.py              # Telegram 發送（HTML parse_mode）

pipelines/
└── daily_brief_pipeline.py      # 跨 agent 編排入口（n8n Execute Command 呼叫）

n8n-workflow.json                # 排程 workflow（每日 21:00 執行 daily-brief）

config/
├── settings.py                  # LLM 後端（LocalLLM / Anthropic 切換）
└── logging_config.py

lint/
├── check_agent_interface.py     # 驗證 AGENT_NAME + run()
└── check_fetcher_interface.py   # 驗證 fetch()

archive/                         # 原始 Claude Code SKILL.md 保存
```

**Fetcher 共用工具**：playwright-cli 的 `_cli_bin`、`_run`、`_wait_for_session` 定義在 `tools/fetchers/browser.py`，新增 fetcher 直接 import，禁止複製。

## 排程（n8n）

排程由本機 n8n 負責，無 Docker。`n8n-workflow.json` 可直接 import：
- 觸發：每日 21:00（Schedule Trigger）
- 執行：`cd /Users/guangzhenglee/Workspace/agent && python3 main.py "/daily-brief"`
- 啟動：`n8n start`，開啟 http://localhost:5678

## 核心設計原則

**Agent vs Tool**：Agent 有 LLM 推理與狀態；Tool 是純函數、確定性、無 LLM。  
`send_telegram` 已從 agent 降級為 `tools/notifiers/telegram.py`。

**Prompts 集中管理**：所有 LLM prompt 定義在 `agents/<name>/prompts.py`，`agent.py` 禁止直接寫 prompt 字串。

**步驟化執行（Idempotent Steps）**：每個步驟把結果存為 artifact（`outputs/daily-brief/{today}/steps/{name}.json`）。重複執行時自動略過已完成步驟；用 `--force` 強制重跑，用 `--only` 指定單步執行。

**輸出目錄結構**：
```
outputs/daily-brief/{today}/
├── steps/
│   ├── hatena.json      # fetch raw + LLM scored（含 fetched_at）
│   ├── hn.json
│   ├── reddit.json
│   ├── security.json
│   ├── compress.json    # 各來源語義壓縮（themes + *** articles + one_liner）
│   ├── digest.json      # 跨來源深度摘要
│   └── judge.json       # LLM-as-Judge 品質評分（relevance/completeness/faithfulness）
├── report.md            # 最終趨勢報告（純 markdown）
├── vault.done           # sentinel（存在 = 已存 Obsidian）
└── telegram.done        # sentinel（存在 = 已發送）
```

**LLM 切換**：`config/settings.py` 的 `get_llm()` 根據環境變數決定後端，`LocalLLMBackend` 優先於 `AnthropicBackend`。

## 新增 Agent / Fetcher

詳見 `AGENTS.md`。執行 lint 驗證：

```bash
python lint/check_agent_interface.py
python lint/check_fetcher_interface.py
```

## 執行環境注意

- 使用 `python3`，不是 `python`（`python` 指令不存在）
- `lms ls` 可查 LM Studio 已載入模型（`a4b` suffix = sparse MoE，active params 遠小於總參數）

## Judge 模型配置

- `config/settings.py` 的 `DEFAULT_JUDGE_LLM_MODEL` 控制預設 judge 模型（目前 `google/gemma-4-e4b`）
- 可透過環境變數 `JUDGE_LLM_MODEL=<model>` 覆蓋
- 測試新 judge 模型：備份 judge.json → `python3 main.py "/daily-brief --force judge --only judge"` → 比較 → 還原

## 約束邊界

- Reddit 禁用 WebFetch，必須 Bash curl 一次查詢後用 Python 解析（禁止兩次重複請求同一 URL）
- Reddit `stickied` 貼文必須過濾：`if p.get("stickied"): continue`
- X/Twitter 必須用 chrome-devtools-mcp
- `.md` 輸出必須用 Python `open()` 寫入
- Telegram 用 HTML parse_mode，≤ 4096 字元；**只允許** `<b>`、`<i>`、`<u>`、`<s>`、`<a>`、`<code>`、`<pre>`，`<br>`/`<p>`/`<div>` 會觸發 400 錯誤
- Telegram 雙重防護：prompt 明列允許 tag + `tools/notifiers/telegram.py` 的 `_sanitize_html()` 在發送前自動過濾
- daily-brief 發兩封訊息：msg1 主題分群列表（`• <b><a>` 格式）、msg2 深度摘要編號列表（`n. <b><a>` + 3 句說明），兩者均為 HTML 格式
- compress 步驟：Python 層先過濾 `interest == "***"` 後才傳 LLM；來源無 *** 文章時直接略過 LLM 呼叫
- report 步驟：LLM 直接輸出純 markdown（不包 JSON）；`_run_report()` 自動剝除 LLM 可能加上的 markdown fence
- judge 步驟：只傳 `url + one_liner` 給 judge LLM（slim context），不傳完整文章內容

## playwright-cli 使用規範

- `open` 啟動長駐 daemon（不自動退出），必須用 `Popen` 放背景，再輪詢 `list` 等 session 就緒
- `--raw eval "<expr>"` 回傳 JSON-encoded 字串，需 `json.loads()` 解碼一層
- `eval` 在瀏覽器 context 執行（有 `document`）；`run-code` 在 Node.js context 執行（有 `page`，無 `document`）
- JS 重度渲染頁面（aikido.dev、wiz.io）需 `page_load_wait=6` 秒，否則 DOM 尚未就緒
- 複雜提取用 `eval "(function(){...})()"` IIFE，不支援 `const`/`let`，用 `var`
- aikido.dev DOM：文章用 `[fs-list-field="title"]` / `[fs-list-field="description"]`
- wiz.io DOM：精選文章用 `h2`，其他用 `h3`

## LM Studio API

- Endpoint：`POST /v1/chat/completions`（非 `/api/v1/chat`）
- Body：`{"model": "...", "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]}`
- Response：`data["choices"][0]["message"]["content"]`

## Fetcher 已知 Gotcha

- Hatena `ai.rss`：HTTP 404，已移除；只用 `it.rss`
- HN HTML 留言數格式：`88&nbsp;comments`（含 `&nbsp;`，非空格）
- LLM context 262144 tokens，`max_chars` 可設較大值：HN=36000（全 30 篇）

## 核心工程理念

### 1. 倉庫即記錄系統
所有架構決策寫進 CLAUDE.md；「為什麼這樣設計」必須版本化。Slack 討論、口頭共識對 AI 不可見。

### 2. 地圖而非手冊
根層 CLAUDE.md 只做導航；每個子目錄 CLAUDE.md ≤ 30 行；漸進式披露。

### 3. 機械化執行
介面規範透過 `lint/` 強制執行；lint 錯誤訊息內嵌修復指令，AI 可自我糾正。

### 4. 智能體可讀性
選無聊技術（httpx、asyncio、BeautifulSoup）；每個 tool/agent 可獨立執行與測試。

### 5. 吞吐量改變合併理念
`outputs/` 存放中間產物；pipeline 允許從任意步驟重新執行；單一 fetcher 失敗不 block 整條流程。

### 6. 熵管理
新增 agent/fetcher 複製 `_template`，不參考其他現有實作；壞模式出現一次立即修正。

## 外部依賴

```
VAULT_ROOT = /Users/guangzhenglee/Library/Mobile Documents/iCloud~md~obsidian/Documents/Second-Brain
├── Scripts/send_telegram.py           # telegram.py 載入此模組
├── Scripts/daily-brief/save_output.py # DailyBriefAgent 存檔
└── Scripts/.env                       # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```
