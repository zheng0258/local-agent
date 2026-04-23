# Agent — 本地 LLM Multi-Agent 系統

將 Claude Code Skills 改為可由**本地 LLM server**（LM Studio / OpenAI-compatible API）執行的 multi-agent 系統。

## 功能

| Skill | 觸發方式 | 說明 |
|-------|----------|------|
| `daily-brief` | `/daily-brief` | 每日自動收集 Hatena、HN、Reddit、資安部落格趨勢，產生摘要報告並推送 Telegram |
| `url-digest` | `/url-digest <URL>` | 擷取指定網頁內容並以 LLM 摘要 |

## 快速開始

### 環境需求

- Python 3.11+
- [LM Studio](https://lmstudio.ai/)（或任何 OpenAI-compatible 本地 LLM server）
- [playwright-cli](https://github.com/cloudflare/playwright-cli)（用於 HN、資安部落格抓取）

### 安裝依賴

```bash
pip install -r requirements.txt
```

### 設定環境變數

```bash
# 本地 LLM（預設）
export LOCAL_LLM_URL=http://localhost:1234
export LOCAL_LLM_MODEL=qwen3.5-27b-claude-4.6-opus-distilled-mlx

# 或使用 Anthropic API
export ANTHROPIC_API_KEY=sk-ant-...

# Telegram 通知（存放於 Obsidian vault Scripts/.env）
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=...
```

### 執行

```bash
# 每日趨勢收集
python3 main.py "/daily-brief"

# URL 摘要
python3 main.py "幫我摘要這些連結 https://example.com"
```

## 進階用法

### 步驟控制（daily-brief）

daily-brief 分為以下步驟，結果以 artifact 快取，重複執行自動略過：

```
hatena → hn → reddit → security → dedup → compress → digest → judge → report → save → notify
```

```bash
# 強制重新執行特定步驟
python3 main.py "/daily-brief --force hatena"
python3 main.py "/daily-brief --force report notify"

# 只執行特定步驟
python3 main.py "/daily-brief --only report"
python3 main.py "/daily-brief --only notify"
```

### 排程（n8n）

匯入 `n8n-workflow.json` 到本機 n8n，每日 21:00 自動執行：

```bash
n8n start  # 開啟 http://localhost:5678
```

## 架構

```
main.py                    # 路由 + 執行入口
AGENTS.md                  # Agent 路由地圖

agents/
├── _template/             # 新增 agent 的範本
├── daily_brief/           # 每日趨勢收集（並行四來源）
│   ├── agent.py
│   ├── prompts.py         # 所有 LLM prompts
│   └── config.py
└── url_digest/            # URL 摘要
    ├── agent.py
    └── prompts.py

tools/
├── fetchers/              # 純函數，無 LLM
│   ├── hatena.py          # Hatena Bookmark RSS
│   ├── hn.py              # Hacker News（playwright-cli）
│   ├── reddit.py          # Reddit（curl）
│   ├── security_blogs.py  # 資安部落格（playwright-cli）
│   └── browser.py         # playwright-cli 共用工具
├── vector_store/          # 向量去重（ChromaDB + 本地嵌入）
│   ├── embedder.py        # Qwen3-Embedding-0.6B MLX 嵌入器
│   ├── client.py          # ChromaDB PersistentClient 封裝
│   └── dedup.py           # URL 精確比對 + 語義去重邏輯
└── notifiers/
    └── telegram.py        # Telegram HTML 訊息

config/
├── settings.py            # LLM 後端切換（Local / Anthropic）
└── logging_config.py

pipelines/
└── daily_brief_pipeline.py  # 跨步驟編排

lint/
├── check_agent_interface.py   # 驗證 AGENT_NAME + run()
└── check_fetcher_interface.py # 驗證 fetch()
```

## 輸出結構

```
outputs/daily-brief/{YYYY-MM-DD}/
├── steps/
│   ├── hatena.json     # 原始抓取 + LLM 評分
│   ├── hn.json
│   ├── reddit.json
│   ├── security.json
│   ├── dedup.json      # 去重統計 + kept_urls
│   ├── compress.json   # 各來源語義壓縮
│   ├── digest.json     # 跨來源深度摘要
│   └── judge.json      # LLM-as-Judge 品質評分
├── report.md           # 最終趨勢報告
├── vault.done          # 已存 Obsidian 哨兵檔
└── telegram.done       # 已發送哨兵檔
```

## 新增 Agent / Fetcher

```bash
# 新增 Agent
cp -r agents/_template/ agents/<name>/
# 實作 AGENT_NAME 與 run()
python3 lint/check_agent_interface.py

# 新增 Fetcher
cp tools/fetchers/_template.py tools/fetchers/<name>.py
# 實作 fetch() 純函數
python3 lint/check_fetcher_interface.py
```

詳細說明見 [AGENTS.md](AGENTS.md)。

## 向量去重（dedup 步驟）

四來源抓取完成後，`dedup` 步驟對所有文章進行去重，避免重複內容消耗後續 compress / digest 的 LLM token：

- **URL 精確比對**：7 天滑動視窗內出現過的 URL 直接過濾
- **語義去重**：以 `Qwen3-Embedding-0.6B-4bit-DWQ`（MLX，351MB）對標題做向量化，cosine similarity ≥ 0.80 視為近似文章並過濾
- **向量庫**：ChromaDB PersistentClient，存於 `outputs/daily-brief/.vectordb/`（已加入 `.gitignore`）
- **可重跑**：`dedup.json` artifact 儲存 `kept_urls`，後續步驟 `--force` 重跑時重現相同過濾結果

```bash
# 強制重新執行去重步驟
python3 main.py "/daily-brief --force dedup"
```

## LLM 後端

| 後端 | 條件 | 預設模型 |
|------|------|----------|
| `LocalLLMBackend` | 無 `ANTHROPIC_API_KEY`，或有 `LOCAL_LLM_URL` | `qwen3.5-27b-claude-4.6-opus-distilled-mlx` |
| `AnthropicBackend` | 有 `ANTHROPIC_API_KEY`，且無 `LOCAL_LLM_URL` | `claude-sonnet-4-6` |

兩種後端皆符合 `LLMBackend` Protocol（`complete(prompt, system) -> str`），可自由替換。

### Judge 模型

Judge 步驟可獨立使用不同模型（預設 `google/gemma-4-e4b`）：

```bash
export JUDGE_LLM_MODEL=google/gemma-4-e4b   # 預設
export JUDGE_LLM_URL=http://localhost:1234   # 可指向不同 server
```

設定位置：`config/settings.py` → `DEFAULT_JUDGE_LLM_MODEL`。
