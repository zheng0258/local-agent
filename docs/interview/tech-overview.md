# AI Daily Brief Agent — 面試技術介紹筆記

> 面試時介紹這個 side project 的技術重點與設計思路

---

## 一句話介紹

用 Python 打造一條 **local-first multi-agent pipeline**，每天自動從 4 個來源抓取科技趨勢，經過 LLM 評分 → 向量去重 → 語義壓縮 → 品質評估，最終推送 Telegram 並存進 Obsidian，本地 LLM 執行，API 費用接近零。

---

## 技術棧速覽

| 層次 | 技術選型 | 為什麼這樣選 |
|------|---------|------------|
| **語言** | Python 3.12，全型別標注 | Protocol + dataclass 夠用，不需要框架 |
| **LLM 後端** | LM Studio（本地）/ Anthropic API（備援） | 零 API 成本；Protocol 讓切換無需改 agent 程式碼 |
| **主模型** | Qwen 3.5 27B（Claude 4.6 Opus distilled, MLX） | 量化後本地可跑，品質接近 Claude Sonnet |
| **Judge 模型** | Gemma 4e4b（MLX，獨立 port 1235） | 輕量獨立評分，可熱換，不污染主流程 |
| **向量資料庫** | ChromaDB（PersistentClient）| 輕量 embedded，無需額外服務 |
| **Embedding** | Qwen3-Embedding-0.6B（MLX，351MB） | 本地推理，支援中日英，cosine similarity 去重 |
| **網頁爬取** | playwright-cli（JS 渲染）、curl + urllib（RSS/JSON） | 視頁面動態程度選最輕量工具 |
| **排程** | n8n（本機，Schedule Trigger）| 無 Docker，免伺服器，workflow 可 import |
| **通知** | Telegram Bot API（HTML parse_mode） | 簡單可靠；sanitizer 自動防 400 錯誤 |
| **知識庫** | Obsidian（iCloud vault，Markdown + frontmatter）| 個人知識管理，可搜尋歷史報告 |
| **測試** | pytest（unit + integration + harness）| 標準選擇；harness 覆蓋 compress/digest/judge |
| **Lint** | ruff + 自製介面 lint scripts | 機械化強制執行介面規範 |

---

## 核心架構設計

### 1. Protocol 而非繼承（Duck Typing）

```python
class LLMBackend(Protocol):
    def complete(self, prompt: str, system: str = "") -> str: ...
```

- `LocalLLMBackend` 呼叫 LM Studio OpenAI-compatible API
- `AnthropicBackend` 呼叫 Anthropic SDK
- Agent 只依賴 Protocol，切換後端不改任何 agent 程式碼
- **面試重點**：Python Protocol 等同 Go interface，duck typing 讓測試可以 mock，生產可以熱換

### 2. Idempotent Step Pipeline（步驟化執行）

```
fetch → dedup → compress → digest → judge → report → save → notify
```

- 每個步驟輸出 JSON artifact 存磁碟（`outputs/daily-brief/{today}/steps/{name}.json`）
- 重跑時自動略過已完成步驟
- `--force hatena` 強制重抓單步；`--only report` 只執行報告生成
- **面試重點**：LLM 呼叫成本高，idempotency 讓開發時只重跑需要的步驟，不浪費資源

### 3. Agent vs Tool 分層

| 類型 | 特徵 | 範例 |
|------|------|------|
| **Agent** | 有 LLM 推理、執行狀態 | `DailyBriefAgent`, `UrlDigestAgent` |
| **Tool** | 純函數、無 LLM、確定性 | fetchers, `telegram.py` |

- Tool 可獨立測試，不需 LLM mock
- Fetcher 統一輸出 `@dataclass(frozen=True) Article`（schema.py 定義），進 LLM 前先正規化

### 4. Prompts 集中管理

- 所有 LLM prompt 定義在 `agents/<name>/prompts.py`
- `agent.py` 禁止直接寫 prompt 字串
- **面試重點**：prompt 是程式碼，要版本控制；集中管理讓 A/B 比較容易

---

## 重要工程問題與解法

### 問題一：本地 LLM JSON 輸出不穩定

本地模型偶爾輸出全形冒號（`：`）、未逸脫引號，導致 `json.loads` 失敗。

**三層 fallback 策略**：
```python
# 1. 正則提取 code fence 內的 JSON
m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
text = m.group(1) if m else raw

try:
    return json.loads(text)           # 2. 直接解析
except json.JSONDecodeError:
    return json.loads(repair_json(text))  # 3. json-repair 修復
```

**面試重點**：`json-repair` 是 pure Python 函式庫，比自行實作 parser 可靠；問題無法靠 prompt 完全根治，需要防禦性程式碼。

---

### 問題二：LLM 靜默丟棄高評分文章

Compress 步驟偶爾 LLM 自行丟棄 `***` 評分文章。

**根本解法：Python 預篩選，不依賴 LLM 遵守規則**：
```python
starred = [a for a in articles if a.get("interest") == "***"]
if not starred:
    result[name] = {"themes": [], "articles": []}
    continue
# 只傳 starred 給 LLM，prompt 明確標示「禁止丟棄任何一篇」
```

**面試重點**：當 LLM 行為不可靠時，在 Python 層先強制過濾，比靠 prompt 說「不要做X」更可靠。

---

### 問題三：playwright-cli Daemon 時序問題

`playwright-cli open` 是長駐 daemon，不能用 `subprocess.run`（會卡住）。

**解法**：
```python
# 1. Popen 放背景啟動
open_proc = subprocess.Popen(base + ["open", url], ...)
# 2. 輪詢等 session 就緒再執行 eval
ready = _wait_for_session(cli, session, retries=10, interval=1.0)
```

**面試重點**：CLI daemon 的正確啟動方式；`eval` 在瀏覽器 context 執行（有 `document`），`run-code` 在 Node.js context 執行（有 `page`）。

---

### 問題四：Telegram HTML 格式限制

Telegram 只接受少數 HTML tag，LLM 輸出常夾雜 `<br>`、`<p>` 導致 400 錯誤。

**雙重防護**：
1. Prompt 明列允許 tag
2. `_sanitize_html()` 發送前自動過濾不支援 tag

```python
_ALLOWED_TAGS = {"b", "i", "u", "s", "a", "code", "pre"}
```

**面試重點**：外部 API 的格式限制要在應用層加 sanitizer，不能假設 LLM 100% 遵守格式。

---

### 問題五：向量去重跨日重現性

每次重跑 pipeline 時，dedup 結果需要一致（否則後續步驟 `--only` 重跑會有差異）。

**解法**：`dedup.json` artifact 保存 `kept_urls`，後續步驟讀 artifact 而非重算向量。

---

## LLM Engineering 重點

### Interest Scoring（評分穩定化）

```
*** = 工程師必看（新架構、突破性技術、安全事件）
**  = 值得追蹤（工具更新、趨勢文章）
*   = 一般資訊（新聞、公告）
```

- Few-shot 邊界範例讓 `**` vs `*` 判斷一致性明顯提升
- `_FEW_SHOT` 常數集中管理，可 A/B 對比

### LLM-as-Judge 品質評估

- 獨立 judge LLM（port 1235，可透過 env var 熱換）
- 三維評分：relevance / completeness / faithfulness
- `completeness < 3` 自動觸發 `quality_alert`
- 歷史分數累積至 `_judge-history.json` 供趨勢追蹤
- **Slim context**：只傳 `url + one_liner`（約原始資料 40%），降低 token 消耗

### Hierarchical Summarization

```
fetch（100+ 篇）
  → interest score（LLM）
  → dedup（向量去重，7 天視窗）
  → compress（各來源語義壓縮，只傳 *** 文章）
  → digest（跨來源整合摘要）
  → report（最終 Markdown 報告）
```

---

## 可延伸的設計決策

| 決策 | 理由 | 未來延伸 |
|------|------|---------|
| Protocol 而非 ABC | Duck typing，不強迫繼承 | 加 OpenAI backend 只需實作 `complete()` |
| Artifact-based idempotency | LLM 呼叫成本高 | 可加 TTL 讓 artifact 過期自動失效 |
| n8n 本機排程 | 免伺服器 | 可改 GitHub Actions 或 cron |
| ChromaDB embedded | 無外部服務依賴 | 資料量大時可遷移 Qdrant/Weaviate |
| Lint scripts | 機械化強制執行介面規範 | 可整合 pre-commit hook |

---

## 面試常見問題預備

**Q: 為什麼不用 LangChain / LlamaIndex？**
> 這個專案只需要 `complete(prompt) → str` 介面，不需要框架的 abstraction overhead。自製 Protocol 更輕量、更好測試，也沒有版本升級的風險。

**Q: Local LLM 品質和 GPT-4 差多少？**
> 針對這個任務（評分、摘要、分類），Qwen 27B 品質足夠。Judge 機制每日量化追蹤，completeness 分數穩定在 3.5+。雲端 API 透過環境變數一鍵切換作為備援。

**Q: Vector DB 的去重效果如何？**
> 7 天滑動視窗，URL 精確比對 + cosine similarity > 0.80 雙重過濾。實際測試重複文章過濾率約 15-20%，節省對應比例的 compress/digest LLM token。

**Q: 這個系統最難的地方是什麼？**
> 本地 LLM 的輸出不穩定性管理。JSON 解析 fallback、compress 預篩選、Telegram sanitizer 都是同一個問題的不同面向：不能假設 LLM 100% 遵守指示，需要在應用層加防禦性程式碼。

**Q: 如果要讓這個系統更 production-ready？**
> 1. Fetcher 加 retry + circuit breaker；2. LLM 呼叫加 timeout + 熔斷；3. artifact 加 schema validation（目前靠 json-repair）；4. 指標輸出 Prometheus，n8n 失敗告警。
