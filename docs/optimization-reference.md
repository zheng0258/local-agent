# 自動化系統優化參考

**來源**：https://zenn.dev/shunya_sudo/articles/claude-code-45-automation-tasks  
**作者**：shunya（東大院 M2，生物工程）  
**整理日期**：2026-04-22

---

## 核心設計哲學

### 判斷與執行分離
AI 負責資訊處理與草稿生成，人類保留最終決策權。  
> "メールが来たら下書きを生成する（送信は人間が判断）"

本專案 daily-brief 已遵循此原則：系統整理摘要，人類閱讀決策。  
新增任何自動化時，問：「這個決策應由 AI 還是人類做？」

### 穩定性優先於功能完整性
ICS URL > OAuth API；RSS > 爬蟲。  
選最不容易壞的方式，減少 auth token 過期、API 版本變更等維護成本。

### 漸進式開發
Day 1 → 30 行最小腳本 → Week 1 加功能 → Month 1 完整版。  
從真實痛點出發，先跑再擴充，避免過度設計。

---

## 作者系統規模（參考基準）

| 項目 | 數量 |
|------|------|
| cron 任務 | 45 本 |
| 自訂 agent | 36 個 |
| Python 腳本 | 132 支 |
| Slack 頻道 | 12 個 |
| 月費 | $100（Claude Code Max） |

執行環境：本機 Mac，無雲端伺服器。

---

## 值得借鑒的任務

### 郵件自動分類（每天省 20-30 分鐘）
- 每 10 分鐘輪詢 3 個信箱
- AI 四級分類：`reply / see / skip / delegate`
- 自動生成回覆草稿（不自動送出）
- 行事曆整合：自動插入可用時段

### 論文新書監控
- 每天 15:00 執行
- 帶關聯度評分 + Slack 摘要
- arXiv RSS 解析，無需瀏覽器

### 多頻率資訊收集

| 任務 | 時間 | 內容 |
|------|------|------|
| `ai_news_brief` | 04:00 | AI 新聞速報 |
| `ai_info_digest` | 09:00/18:00/21:00 | 分析存入 Notion 的連結 |
| `ai_researcher` | 04:30/12:00 | 學術 AI 研究動態 |

### Slack 作為儀表板
每類輸出有專屬頻道，AI 輸出集中到人類可見的地方：

```
#ai-email     → 郵件分類結果
#ai-research  → 論文新書
#ai-news      → AI 新聞
#ai-daily     → 日次報告（含 cron 成功率）
#ai-system    → 系統健康監控
```

---

## 本專案缺口與優化方向

### 1. 系統健康監控（高優先）
**現狀**：n8n 失敗只有 n8n 介面可見，無主動告警。  
**方向**：每次執行結束後，發一條 Telegram 系統狀態摘要：
```
✅ hatena ✅ hn ✅ reddit ❌ security（timeout）
```

### 2. cron 成功率追蹤（高優先）
**現狀**：無跨日執行記錄。  
**方向**：在 `outputs/daily-brief/{today}/steps/` 加 `_meta.json`，記錄每步驟執行狀態與耗時，report 加「近 7 日執行摘要」。

### 3. 郵件自動分類（中優先）
**方向**：新增 `agents/email_triage/`，Gmail API 監控，Telegram 推送分類結果，草稿存 Drafts 不自動送出。

### 4. 論文/學術監控（低優先）
**方向**：新增 `tools/fetchers/arxiv.py`（RSS 解析），daily-brief config 加 `arxiv` 來源開關。

---

## 本專案 vs 文章對照

| 面向 | 文章作者 | 本專案 |
|------|---------|--------|
| 排程 | cron 45 本 | n8n workflow |
| 通知 | Slack 12 頻道 | Telegram 2 則訊息 |
| 資訊來源 | 論文 + AI 新聞 | Hatena/HN/Reddit/Security |
| AI 後端 | Claude Code Max（$100/月） | 本地 LLM + Anthropic API |
| 可觀測性 | 完整（cron 成功率、系統頻道）| **不足（缺健康監控）** |

**最大差距**：可觀測性——系統跑壞了，本專案目前沒有主動告警機制。
