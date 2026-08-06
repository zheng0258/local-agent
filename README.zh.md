# Agent — 本地 LLM Multi-Agent 系統

將 Claude Code Skills 改為可由**本地 LLM server**（LM Studio / OpenAI-compatible API）執行的 multi-agent 系統。每日自動收集 **5 個來源**的科技趨勢,經去重、LLM 評分、壓縮、深度摘要與 LLM-as-Judge 品質把關後,推送到 Telegram、存入 Obsidian、並發布到公開展示站 —— 全程跑本地模型,API 成本趨近於零。

[English](README.md)

## 功能

| Skill | 觸發方式 | 說明 |
|-------|----------|------|
| `daily-brief` | `/daily-brief` | 每日自動收集 Hatena、HN、Reddit、資安部落格、RSS 趨勢,產生摘要報告並推送 Telegram / Obsidian / 展示站 |
| `url-digest` | `/url-digest <URL>` 或「幫我摘要這些連結」 | 擷取指定網頁內容並以 LLM 摘要 |

## 快速開始

### 環境需求

- Python 3.11+
- [LM Studio](https://lmstudio.ai/)（或任何 OpenAI-compatible 本地 LLM server）
- [playwright-cli](https://github.com/cloudflare/playwright-cli)（HN 抓取使用）

### 安裝依賴

```bash
pip install -r requirements.txt
```

### 設定環境變數

所有機器專屬值走專案根 `.env`（範本見 `.env.example`）,原始碼不寫死路徑或憑證。

```bash
# 本地 LLM（預設）
export LOCAL_LLM_URL=http://localhost:1234
export LOCAL_LLM_MODEL=qwen/qwen3.6-27b

# Telegram / vault / deploy 皆為選填,寫進專案根 .env：
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=...
# VAULT_ROOT=/path/to/obsidian/vault
# DEPLOY_GITHUB_TOKEN=...
```

| 設定 | env var | 必填？ | 未設定時 |
|---|---|---|---|
| 本地 LLM | `LOCAL_LLM_URL` / `LOCAL_LLM_MODEL` | 否（有預設） | 用 `localhost:1234` / `qwen/qwen3.6-27b` |
| Judge 模型 | `JUDGE_LLM_URL` / `JUDGE_LLM_MODEL` | 否 | 與主 LLM 同 URL / `gemma-4-e4b` |
| Telegram 推播 | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 選填 | 靜默略過推播與告警 |
| Obsidian 存檔 | `VAULT_ROOT` | 選填 | `save` 步驟略過 |
| Deploy（gh-pages）| `DEPLOY_GITHUB_TOKEN` | 選填 | 走 `origin` credential helper |

### 執行

```bash
# 每日趨勢收集
python3 main.py "/daily-brief"

# URL 摘要
python3 main.py "幫我摘要這些連結 https://example.com"
```

## 進階用法

### 步驟控制（daily-brief）

daily-brief 是 **14 個 idempotent 步驟**組成的 pipeline,結果以 artifact 快取,重複執行自動略過已完成步驟：

```
hatena · hn · reddit · security · rss   →  dedup  →  compress  →  enrich
   →  digest  →  tldr  →  judge  →  report  →  save  →  compose_tg  →  notify  →  deploy
```

```bash
# 強制重新執行特定步驟（忽略當日 artifact）
python3 main.py "/daily-brief --force hatena hn"
python3 main.py "/daily-brief --force report"    # 重新生成報告（不重抓資料）
python3 main.py "/daily-brief --force notify"    # 重送 Telegram

# 只執行特定步驟
python3 main.py "/daily-brief --only report notify"

# 唯讀健康查詢（不載入模型、不跑 pipeline）—— 印近 7 天各來源/遞送成功率表
python3 main.py "/daily-brief --health"
```

「該跑 / 該載入 / 該略過」的門檻判定集中於純函數 `step_cache.decide(in_steps, exists, forced)`（回傳 RUN / LOAD / SKIP）；每個步驟繼承共用的 `Step` 基底（`step.py`）,公開介面只有 `run(ctx, input) -> StepOutcome`。

### 排程（crontab）

兩段式排程：先預熱模型,再執行 pipeline,避免 10 分鐘 API 等待拖慢主流程。

```bash
# 第一條：load_model（01:45）
(crontab -l 2>/dev/null; echo "45 1 * * * cd $HOME/Workspace/agent && /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 load_model.py >> /tmp/load_model.log 2>&1") | crontab -

# 第二條：daily-brief（02:00）
(crontab -l 2>/dev/null; echo "0 2 * * * cd $HOME/Workspace/agent && /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 main.py \"/daily-brief\" >> /tmp/daily_brief.log 2>&1") | crontab -

crontab -l   # 確認
```

| 腳本 | 時間 | 職責 |
|------|------|------|
| `load_model.py` | 01:45 | LM Studio 自動啟動 → 模型載入 → API 穩定等待（600s）→ 失敗 Telegram 告警 |
| `main.py` | 02:00 | 假設模型已就緒直接執行；仍以 `ensure_llm_ready()` 做最後防線 |

**手動補跑**：`python3 main.py "/daily-brief"`（確保 LM Studio 已啟動）或雙點擊 `run_daily_brief.command`。

## 架構

**Agent vs Tool 分離**：Agent 有 LLM 推理與狀態（`DailyBriefAgent` + `steps/`）；Tool 是純函數、確定性、無 LLM（fetchers / notifiers / vector_store）,可獨立測試。

```
main.py                       # 路由 + 執行入口
AGENTS.md                     # Agent 路由地圖

agents/daily_brief/
├── agent.py                  # DailyBriefAgent.run()：純 pipeline 地圖
├── step.py                   # Step 基底（run → produce/load/guard seam）
├── step_cache.py             # decide() → RUN/LOAD/SKIP 純函數
├── codecs.py                 # ArtifactCodec（Json/Text/Sentinel）
├── schemas.py                # step artifact 的 typed 唯讀 view
├── health.py                 # 可觀測性：Health Record + 慢性故障偵測
├── supervisor.py             # LLM 監督器（fetch 品質控管）
├── prompts.py / reflect_prompts.py   # 所有 LLM prompts
├── config.py                 # 來源、門檻、retry 設定、路徑
├── steps/                    # source · dedup · compress · enrich · digest ·
│                             #   tldr · judge · report · save · compose_tg · notify · deploy
└── fetchers/

tools/
├── fetchers/                 # 純函數,無 LLM
│   ├── hatena.py             # Hatena Bookmark RSS
│   ├── hn.py / hn_comments.py         # Hacker News（playwright-cli）+ 留言
│   ├── reddit.py / reddit_comments.py # Reddit（curl）+ 留言
│   ├── security_blogs.py     # 資安部落格 RSS（aikido.dev / wiz.io）
│   ├── rss_common.py         # RSS 來源共用 SSL context + feed 抓取
│   └── browser.py            # playwright-cli 共用工具
├── vector_store/             # 語義去重（ChromaDB + MLX 嵌入）
│   ├── embedder.py           # Qwen3-Embedding-0.6B-4bit-DWQ（MLX）
│   ├── client.py             # ChromaDB PersistentClient 封裝
│   └── dedup.py              # URL 精確比對 + 語義去重
├── lms_lifecycle.py          # lms CLI 模型載入/卸載
└── notifiers/telegram.py     # Telegram HTML 訊息（自包,讀專案 .env）

config/settings.py            # LocalLLMBackend + LLM 可用性探測
lint/
├── check_agent_interface.py  # 驗證 AGENT_NAME + run()
└── check_fetcher_interface.py # 驗證 fetch()
```

## 輸出結構

```
outputs/daily-brief/{YYYY-MM-DD}/
├── steps/
│   ├── hatena/hn/reddit/security/rss.json  # 原始抓取 + LLM 評分
│   ├── alerts.json    # 步驟失敗記錄（結尾彙總成單封 Telegram 告警）
│   ├── dedup.json     # 去重統計 + kept_urls
│   ├── compress.json  # 各來源語義壓縮（themes + articles + one_liner）
│   ├── enrich.json    # HN/Reddit 留言摘要（社群觀點）
│   ├── digest.json    # 跨來源深度摘要
│   ├── tldr.json      # 展示站首頁「今日重點」
│   ├── judge.json     # LLM-as-Judge 品質評分
│   └── compose_tg.json # 兩封 Telegram 訊息（Telegram-safe HTML）
├── report.md          # 最終趨勢報告
├── vault.done         # 已存 Obsidian 哨兵檔
└── telegram.done      # 已發送哨兵檔

outputs/daily-brief/
├── _judge-history.json     # 逐日品質分歷史
├── _health-history.json    # 逐日 Health Record（各來源/遞送 ok 或錯誤型別）
└── _health-escalated.json  # 慢性故障 escalation 去重狀態
```

## 語義去重（dedup 步驟）

五來源抓取完成後,`dedup` 步驟對所有文章去重,避免重複內容消耗後續 compress / digest 的 LLM token：

- **URL 精確比對**：7 天滑動視窗內出現過的 URL 直接過濾
- **語義去重**：以 `Qwen3-Embedding-0.6B-4bit-DWQ`（MLX,351MB）對標題向量化,cosine similarity ≥ 0.80 視為近似文章並過濾
- **向量庫**：ChromaDB PersistentClient,存於 `outputs/daily-brief/.vectordb/`（已加入 `.gitignore`）
- **可重跑**：`dedup.json` artifact 儲存 `kept_urls`,後續步驟 `--force` 重跑時重現相同過濾結果

## LLM 後端

固定使用 `LocalLLMBackend`（LM Studio,OpenAI-compatible `/v1/chat/completions`）,啟動時自動探測可用性,未回應則發 Telegram 告警並中止。後端符合 `LLMBackend` Protocol（`complete(prompt, system) -> str`）,agent 程式碼不綁定特定 vendor。

| 用途 | 預設模型 | 覆蓋方式 |
|------|----------|----------|
| 主 LLM | `qwen/qwen3.6-27b` | `LOCAL_LLM_MODEL` |
| Judge | `google/gemma-4-e4b` | `JUDGE_LLM_MODEL` / `JUDGE_LLM_URL` |

Judge 步驟可獨立使用不同（更強）的評分模型；設定位置：`config/settings.py` → `DEFAULT_JUDGE_LLM_MODEL`。

## 品質把關與可觀測性

- **LLM-as-Judge**：以獨立模型評 relevance / completeness / faithfulness,`completeness` 過低時觸發 reflect-and-regenerate 迴圈重跑 digest；分數逐日累積於 `_judge-history.json`。
- **health.py 可觀測性**：pipeline 有韌性（≥2 來源即出貨）但會默默降級。每次執行末推導出一筆 Health Record,跨天偵測**慢性故障**（同 subject 7 天內失敗 ≥3 次）才主動 Telegram escalate,單次 transient flake 靜默。`--health` 是同一份歷史的唯讀 render。

## 新增 Agent / Fetcher

```bash
# 新增 Agent
cp -r agents/_template/ agents/<name>/
python3 lint/check_agent_interface.py     # 驗證 AGENT_NAME + run()

# 新增 Fetcher
cp tools/fetchers/_template.py tools/fetchers/<name>.py
python3 lint/check_fetcher_interface.py   # 驗證 fetch()
```

詳細說明見 [AGENTS.md](AGENTS.md),完整設計理念見 [CLAUDE.md](CLAUDE.md)。
