AI Daily Brief Agent | Python · Local LLM · ChromaDB · n8n

每日自動從 4 個來源（Hatena、Hacker News、Reddit、資安部落格）爬取 100+ 篇文章，LLM 興趣評分、跨日向量去重、語義壓縮、跨來源摘要、Telegram 推送。以本地 LLM 執行，API 成本為零。

---

## 詳細版

- **LLMBackend Protocol**：duck typing 抽象 LLM 後端，本地 server（LM Studio / Ollama）與任何 OpenAI-compatible API 可透過環境變數切換，不需修改 agent 程式碼；機械性任務注入 `/no_think` token 降低推理延遲
- **Idempotent 11-step pipeline**：hatena / hn / reddit / security / dedup / compress / digest / judge / report / save / notify；每步驟產生 JSON artifact，支援精確重跑（`--force` / `--only`），單步失敗不阻斷整條流程
- **ChromaDB 跨日語義去重**：以 Qwen3-Embedding 對文章標題向量化，7 天滑動視窗內 cosine similarity > 0.80 的近似文章自動過濾，避免重複內容拖長後續 LLM 推理時間
- **SupervisorAgent 自癒迴圈**：包覆每個 LLM 步驟，解析錯誤類型後自動 retry，連續失敗直接觸發 Telegram alert，全程無需人工介入
- **並行抓取 + partial-success guard**：4 個來源並行爬取，單一 fetcher 失敗不阻斷其他來源，保證每日摘要完整性
- **LLM-as-Judge**：獨立 judge 模型（Gemma 4B，可透過環境變數熱換）每日對摘要評分（relevance / completeness / faithfulness），completeness 過低自動觸發 quality alert，歷史分數累積供趨勢追蹤
- **三層 JSON fallback**：正則提取 → `json.loads` → `json-repair`，穩定處理本地模型輸出不規則問題
- **Interface lint scripts**：機械化強制 agent/fetcher 介面規範，LLM 可根據錯誤訊息自我糾正

---

## 簡化版

- **LLMBackend Protocol**：duck typing 抽象 LLM 後端，環境變數熱切換本地 server 與任何 OpenAI-compatible API，不需修改 agent 程式碼
- **Idempotent 11-step pipeline**：每步驟產生 JSON artifact，支援 `--force` / `--only` 精確重跑，單步失敗不阻斷整條流程
- **ChromaDB 跨日語義去重**：Qwen3-Embedding 向量化文章標題，7 天滑動視窗過濾語義近似文章，避免重複內容拖長 LLM 推理時間
- **SupervisorAgent 自癒迴圈**：監控每個 LLM 步驟，自動 retry，連續失敗觸發 Telegram alert
- **LLM-as-Judge**：獨立 judge 模型（Gemma 4B）每日三維評分，completeness 過低自動觸發 quality alert
- **三層 JSON fallback**：正則提取 → `json.loads` → `json-repair`，處理本地模型不規則輸出
- **Interface lint scripts**：機械化強制 agent/fetcher 介面規範，LLM 可自我糾正
