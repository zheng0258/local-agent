# LLM 結構化輸出：json_schema 約束解碼取代「自由輸出 + 事後解析」

## Context

2026-10-17 重構評估的結論：daily-brief 多數 LLM 相關 bug 都源自同一種形狀——
**LLM 自由輸出文字，Python 事後解析、再猜它的意思**：

- 報告 `[標題](@@id@@)` token：標題含 `[..]` 或 LLM 漏寫 `[` 時 token 未被替換、死連結上站
  （commit `bd84711` 以 `links.py` 補丁修）。
- judge LLM 自吐 `quality_alert` / `quality_alert_reason` 欄位，`_judge` 把整份 parsed dict
  當結果，這些欄位隨之流入 `judge.json` 與公開歷史（PM 週報 10-12 鑑識）。
  分數全合格時 Python 不會覆寫，LLM 的旗標就原樣留下。
- `parse_llm_json` 數次收到空回應或半截 JSON 而失敗（json_repair 救不回）。

業界標準作法是**約束解碼**（constrained decoding）：推論端把 JSON Schema 編成文法，
取樣時遮掉不合法的 token，模型「只能」輸出合法結構；連結、markdown 等呈現層由
Python 依可信資料組裝。LM Studio 支援 OpenAI 相容的
`response_format: {"type": "json_schema", "json_schema": {...}}`。

## Spike（2026-10-17，本機 LM Studio，scratch 腳本未入 repo）

四個極小請求（prompt ≤ 175 tokens）：

| 案例 | 模型 | 結果 |
|---|---|---|
| compress schema + `/no_think` | qwen/qwen3.6-27b | JSON 完全合法、內容正常；`/no_think` 相容 |
| 要求額外輸出 `title`/`url`/頂層 `note` | qwen/qwen3.6-27b | 文法擋下，只出 `id`/`one_liner`（**schema 外欄位無法生成**） |
| judge schema + 要求自吐 `quality_alert` | qwen3.6-35b-a3b（不帶 `/no_think`） | 文法擋下 `quality_alert`；分數合理（遺漏 1 篇 → completeness=4、missed_urls 正確） |
| 整合：真實 `build_compress_prompt` 走 `LocalLLMBackend` | qwen/qwen3.6-27b | 解析成功 |

兩個非預期但關鍵的發現：

1. **JSON 落在 `reasoning_content`，`content` 為空字串。** 文法從第一個 token 就生效，
   模型沒有 `<think>` 區段，但 LM Studio 的 reasoning parser 仍把整段輸出標成
   reasoning（`completion_tokens_details.reasoning_tokens` == 全部輸出）。
   → 後端必須在「約束解碼且 content 為空」時退回讀 `reasoning_content`。
   無 schema 時 `reasoning_content` 是隱藏思考，**絕不**當答案（有測試鎖住）。
2. **約束解碼 = 模型不思考。** 對 compress（本來就 `/no_think`）是純收益；
   對原本會思考的 judge / digest，completion tokens 大降（CLAUDE.md 記載瑣碎呼叫的
   隱藏 reasoning 可達 ~1900 tokens），但失去了思考帶來的品質。judge 以「schema 屬性
   順序 = 生成順序」代償：每維度 `reasoning` 排在 `score` 前，理由先於分數生成。

結論：支援、遵守、與 `/no_think` 相容，未見品質下降 → 採用。

## Decision

1. **後端**：`LocalLLMBackend.complete(prompt, system="", schema=None)`。`schema` 非 None
   時送 `response_format`（`strict: true`）；回應經 `_extract_content` 純函數取答案。
   `Step._complete(ctx, prompt, schema=None)` 對應開放，`LLMBackend` Protocol 與
   `tests/fakes.FakeLLM`（記錄 `schemas`）同步。
2. **契約集中於 `agents/daily_brief/llm_schemas.py`**（與 `prompts.py` 成對：prompt 說任務，
   schema 規定只能輸出什麼）。每個 object 皆 `additionalProperties: false` + 全欄位 required。
   - `JUDGE_SCHEMA`：頂層只有 `scores` / `missed_urls` / `overall`；維度來自
     `schemas.JUDGE_DIMENSIONS`（與 `QualityScore` typed view、示警門檻共用單一定義）；
     `score` 為 1–5 整數。
   - `COMPRESS_SCHEMA`：`themes` + `articles[{id, one_liner}]`。
   - `DIGEST_SCHEMA`：`digests[{id, summary}]`。
   URL / title 在文法層就無法經 LLM 之手——把 CLAUDE.md「URL 是資料，不是 LLM 輸出」
   從 prompt 約定 + 事後重建，前移到解碼層。
3. **`parse_llm_json` 保留為 fallback**：約束輸出本身就是合法 JSON，`json.loads` 首次即成功；
   schema 未生效（回退開關關閉、未來換用不支援的後端）時仍走原本的 fence 剝除 + json_repair。
4. **judge 白名單化（縱深防禦）**：`_sanitize_judge_response` 只保留各維度 `score`/`reasoning`
   與頂層字串 `missed_urls`；LLM 自填的 `overall`、`quality_alert*` 一律丟棄，由 Python
   依分數重算。即使 fallback 路徑也不會再有外洩欄位進 `judge.json` / 歷史。
5. **回退開關**：`LLM_STRUCTURED_OUTPUT=0|false|off|no` 關閉約束解碼（`get_llm` /
   `get_judge_llm` 讀取），不改程式即可退回舊行為。

## Consequences

- 正面：外洩欄位、URL 回吐在文法層根除；JSON 解析失敗只剩截斷（`max_tokens` 用盡）一途；
  judge / digest 不再產生隱藏 reasoning，token 吞吐預期大降（以 `--usage` 觀察）。
- 風險：judge / digest 失去思考。監測方式為既有的品質訊號——`quality_signals` 的 judge
  分數飽和與 digest 來源占比、judge 的 faithfulness 示警；若 faithfulness 或鑑別力明顯
  劣化，先以 `LLM_STRUCTURED_OUTPUT=0` 回退，再評估「先自由思考、再以第二次約束呼叫
  格式化」的兩段式。
- `reasoning_content` fallback 綁定 LM Studio 現行 reasoning parser 行為；若日後
  LM Studio 改把約束輸出放回 `content`，`_extract_content` 優先讀 `content`，自動相容。
- 其餘仍走自由輸出的 LLM 步驟（source 評分、enrich、tldr、report、compose_tg）未變。

## 後續計畫：report 改由 Python 模板組 markdown

report 是目前唯一仍讓 LLM 直接輸出「含連結的 markdown」的步驟，也是 `@@id@@` token
未替換事件的源頭。下一步：

1. 新增 `REPORT_SCHEMA`：LLM 只回結構化內容——各來源的主題群（`theme` + 文章 `id` 清單）、
   今日總結段落等純文字欄位，**不含任何連結或 markdown 語法**。
2. `report.md` 由 Python 模板（如既有的 jinja2 依賴）依 `id` 從 compress / digest 重建
   `[title](url)`，標題中的 `[` `]` 由模板統一逸脫——`links.py` 的 token 替換補丁屆時可移除。
3. compose_tg 同理：LLM 只回 `{id, 說明}`，HTML `<a href>` 由 Python 組裝，`@@id@@`
   token 機制與 `strip_invalid_anchors` 降為最後防線。
4. source 評分（`interest`/`category`）亦可套 enum schema，消除自由文字分級的解析分歧。
