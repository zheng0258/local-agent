# Side Project：AI Daily Brief Agent

> AI Engineering Resume — Side Project 條目

---

## 一句話摘要

將 Claude Code Skills 重構為可在本地 LLM 上運行的 multi-agent pipeline，每日自動從 4 個來源爬取科技趨勢、LLM 興趣評分、跨日向量去重、語義壓縮、SupervisorAgent 自癒、Telegram 推送，並同步至 Obsidian 知識庫，API 成本為零。

---

## 專案亮點（Resume Bullet Points）

- **Local LLM-first 架構**：設計 `LLMBackend` Protocol，支援 LM Studio（OpenAI-compatible）與 Anthropic Claude API 熱切換，無需改動 agent 程式碼
- **Multi-source 資料聚合**：並行爬取 Hatena Bookmark IT（RSS）、Hacker News（playwright-cli JS 渲染）、Reddit 16 子版（curl + JSON）、資安部落格（aikido.dev / wiz.io），每日處理 100+ 篇文章
- **Idempotent Step Pipeline**：11 步驟（4×fetch / **dedup** / compress / digest / judge / report / save / notify）各自產生 JSON artifact，支援 `--force` / `--only` 精確重跑，單步失敗不阻斷整條流程
- **Prompt Engineering**：Interest scoring（*** / ** / *）含 few-shot 邊界範例穩定評分、Python 預篩選後語義壓縮（compress）、跨來源去重 digest、report 直接輸出純 markdown（避免 JSON 包裝引起的解析失敗）、Telegram HTML 格式雙訊息，prompt 集中管理於 `prompts.py`
- **Fetcher Output 標準化**：`tools/fetchers/schema.py` 定義 `@dataclass(frozen=True) Article` + `clean_articles()`，作為 hierarchical summarization 第一層（純函數、無 LLM），統一各 fetcher 輸出格式後再進 LLM 流程
- **LLM Output 防禦**：正則提取 ` ```json ` 區塊 → `json.loads` → `json-repair` 三層 fallback，處理本地模型輸出不穩定問題（全形冒號、未逸脫引號等）；Telegram HTML sanitizer 自動過濾不支援 tag，避免 Telegram API 400 錯誤；report 輸出自動剝除 markdown fence
- **LLM-as-Judge 品質評估**：獨立 judge LLM（`google/gemma-4-e4b`，可透過 env var 熱換）每日對摘要進行 relevance / completeness / faithfulness 三維評分；completeness < 3 自動觸發 `quality_alert`；歷史分數累積至 `_judge-history.json` 供趨勢追蹤
- **Interface Lint 自動化**：`lint/check_agent_interface.py` / `check_fetcher_interface.py` 驗證所有 agent/fetcher 符合介面規範，可整合 CI
- **Model Lifecycle 自動化**：`tools/lms_lifecycle.py` 在 `main.py` 執行前以阻塞式 `lms load -y` 確保主模型（qwen3.5-27b）與 judge 模型（gemma-4-e4b）已載入，完成後 `lms unload --all` 釋放記憶體；load 後再次 `lms ps` 做雙重驗證；所有 subprocess 呼叫設 timeout（ps: 10s / load: 300s / unload: 30s）防 daemon hang 卡死 pipeline；`try/finally` 保證 unload 必然執行，無論 pipeline 成功或失敗
- **Vector DB 語意去重**：fetch 完成後插入 `dedup` 步驟，以 ChromaDB（persistent）+ `Qwen3-Embedding-0.6B`（MLX，351MB）對文章標題做語意向量化；7 天滑動視窗內 URL 精確比對與 cosine similarity > 0.80 的語意近似文章均被過濾，避免重複文章消耗 compress / digest 的 LLM token；`dedup.json` artifact 保存 `kept_urls` 供後續步驟重跑時重現相同過濾結果
- **n8n 排程**：本機 n8n workflow 每日凌晨 02:00 觸發，免伺服器、免 Docker

---

## Tech Stack

| 層次 | 技術 |
|------|------|
| **Language** | Python 3.12（型別標注、Protocol、dataclass） |
| **LLM Backend** | LM Studio（本地）/ Anthropic Claude API（備援） |
| **Main / Judge Model** | Main：Qwen 3.5 27B（Claude 4.6 Opus distilled, MLX）；Judge：`google/gemma-4-e4b`（MLX）；兩者均由 LM Studio server（port 1234）提供；`tools/lms_lifecycle.py` 在 pipeline 啟動前自動 load、結束後 unload |
| **Web Scraping** | playwright-cli（JS 渲染）、curl / urllib（RSS/JSON API） |
| **Data Sources** | Hatena RSS、HN 首頁（playwright-cli + HTML 解析）、Reddit JSON API、aikido.dev / wiz.io |
| **Notification** | Telegram Bot API（HTML parse_mode） |
| **Knowledge Base** | Obsidian（iCloud vault，Markdown + frontmatter） |
| **Scheduler** | n8n（Schedule Trigger，本機） |
| **Testing** | pytest（unit + integration）；`tests/harness/` 針對 compress/digest/judge/telegram 進行端對端 harness 測試 |
| **Linting** | ruff、interface lint scripts |
| **Vector DB** | ChromaDB（PersistentClient）+ Qwen3-Embedding-0.6B-4bit-DWQ（mlx_lm 直接推理） |
| **Dependency** | 極簡（`anthropic`, `certifi`, `chromadb`, `json-repair`），核心功能使用 stdlib |

---

## 架構概覽

```
main.py  ──→  route()  ──→  DailyBriefAgent / UrlDigestAgent
                                     │
                   ┌─────────────────┼──────────────────────┐
                   ▼                 ▼                       ▼
            tools/fetchers/    config/settings.py      tools/notifiers/
            (純函數，無 LLM)    LLMBackend Protocol     telegram.py
            hatena / hn /       LocalLLM / Anthropic
            reddit / security
            schema.py ← Article dataclass（frozen）
                   │
                   ▼
            steps/{name}.json  ← artifact cache（每步驟獨立）
            ├── hatena/hn/reddit/security.json   # fetch + LLM score
            ├── dedup.json                       # 去重統計 + kept_urls
            ├── compress.json                    # 語義壓縮 + 主題分群
            ├── digest.json                      # 跨來源去重摘要
            ├── judge.json                       # 品質評分（3 維度）
            report.md / telegram.done / vault.done

tools/lms_lifecycle.py  ← 模型生命週期（load / unload / verify）
```

**Agent vs Tool 分層**：
- **Agent**：擁有 LLM 推理能力與執行狀態（`DailyBriefAgent`, `UrlDigestAgent`）
- **Tool**：純函數、確定性、無 LLM（fetchers, notifiers），可獨立測試

---

## 解決的工程問題

### 1. 本地 LLM 輸出不穩定
本地模型偶爾輸出含全形冒號（`：`）或未逸脫雙引號的無效 JSON，使用三層 fallback 策略：
```python
# 1. 正則提取 code fence 內的 JSON
m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
text = m.group(1) if m else raw
try:
    return json.loads(text)          # 2. 直接解析
except json.JSONDecodeError:
    repaired = json.loads(repair_json(text))  # 3. json-repair 修復
    return repaired if isinstance(repaired, dict) else {"raw": raw}
```

### 2. playwright-cli Daemon 管理
`playwright-cli open` 是長駐 daemon，需 `Popen` 放背景再輪詢 `list` 確認 session 就緒，否則 eval 指令會失敗：
```python
open_proc = subprocess.Popen(base + ["open", url], ...)
ready = _wait_for_session(cli, session, retries=10, interval=1.0)
```

### 3. Telegram HTML 限制
Telegram 只接受少數 HTML tag，LLM 輸出常夾雜 `<br>`、`<p>` 導致 400 錯誤，使用 regex sanitizer 在發送前自動過濾：
```python
_ALLOWED_TAGS = {"b", "i", "u", "s", "a", "code", "pre"}
```

### 4. Reddit Stickied 貼文污染
Reddit stickied 公告貼文若不過濾，LLM 會將其列入摘要：
```python
if p.get("stickied"): continue
```

### 6. 模型生命週期自動化
每次 pipeline 執行前需確保 LM Studio 主模型與 judge 模型已載入，執行後釋放記憶體。手動管理容易遺漏；`lms unload --all` 若從未執行，27B 模型常駐佔用 15GB RAM。

設計 `tools/lms_lifecycle.py`，`subprocess.run` 阻塞式呼叫確保 load 完成才繼續，並在 load 後再次 `lms ps` 驗證：
```python
# main.py
ensure_models_loaded([DEFAULT_LOCAL_LLM_MODEL, DEFAULT_JUDGE_LLM_MODEL])
try:
    print(agent.run(args))
finally:
    unload_all()  # 無論成功或失敗都執行
```
所有 subprocess 加 timeout（load: 300s）防止 daemon hang 永久阻塞 pipeline。

### 5. LLM 靜默丟棄 *** 文章
Compress 步驟偶爾 LLM 靜默丟棄 *** 評分文章。根本解法是 Python 預篩選，而非事後 fallback：只將 `interest == "***"` 的文章傳入 LLM，prompt 明確標示「已由程式預先篩選，禁止丟棄任何一篇」；無 *** 文章時直接跳過 LLM 呼叫：
```python
starred = [a for a in articles if isinstance(a, dict) and a.get("interest") == "***"]
if not starred:
    result[name] = {"themes": [], "articles": []}
    continue
# 僅傳 starred 給 LLM，prompt 明確禁止丟棄
raw = self._complete(prompts.build_compress_prompt(name, json.dumps(starred)))
```

---

## 設計決策

| 決策 | 理由 |
|------|------|
| Protocol 而非 ABC | Duck typing，不強迫實作繼承，符合 Go/Python 最佳實踐 |
| Artifact-based idempotency | 重跑成本高（LLM 呼叫），需明確控制哪些步驟重執行 |
| Prompts 集中在 `prompts.py` | agent.py 禁止直接寫 prompt 字串，統一管理、易於版本比較 |
| `json-repair` 作為 fallback | 本地模型 JSON 格式錯誤無法完全靠 prompt 根治；引入輕量 pure Python 函式庫作第三層防禦，比自行實作 parser 更可靠 |
| LLM-as-Judge 獨立 backend | judge 與主 LLM 使用相同預設模型，但透過 env var 可熱換為更強模型；`quality_alert` 閘門讓品質問題可被偵測；歷史追蹤讓品質退步有跡可循 |
| Judge slim context | judge LLM 只接收 url + one_liner（約原始 compress.json 的 40%），completeness 判斷不需完整文章內文，顯著降低 token 消耗 |
| Few-shot 評分範例 | 單純規則描述在邊界案例（`**` vs `*`）上不穩定；加入具名範例後 LLM 評分一致性明顯提升，且可集中管理在 `_FEW_SHOT` 常數 |
| Lint scripts 而非文件 | 介面規範機械化強制執行，AI 可根據錯誤訊息自我糾正 |

---

## 成果指標

- 每日自動執行，處理 **100+ 篇文章**，輸出 Markdown 報告 + 2 則 Telegram 訊息
- 支援 **4 個資料來源** × 多種爬取策略（RSS / API / JS 渲染）
- **10 個獨立步驟**，任意步驟可單獨重跑，pipeline 不中斷
- 本地 LLM（Qwen 27B）執行成本 **接近零**，雲端 API 作備援
- **LLM-as-Judge** 每日品質追蹤，completeness < 3 觸發 `quality_alert`，歷史分數累積至 `_judge-history.json`
- **Source Health 監控**：每次 compress 後自動檢查各來源是否為 0 篇，異常時 log warning

---

## 相關連結

- 架構說明：`CLAUDE.md`、`AGENTS.md`
- 路由入口：`main.py`
- Agent 範本：`agents/_template/`
- 原始 Claude Code Skills（對照參考）：`archive/`
