---
name: daily-brief
description: Use when someone asks to collect daily tech trends or run the trend digest. Triggered by /daily-brief or phrases like "收集今日趨勢", "跑趨勢收集", "run daily-brief".
argument-hint: (no arguments)
disable-model-invocation: true
---

## 功能說明

收集當日科技趨勢文章，來源涵蓋 Hatena Bookmark IT（日本市場）、Hacker News（全球）、Reddit（16 個子版）及資安部落格，輸出繁體中文整理報告，存入 Second Brain。

## 流程架構：Pipeline（每個來源獨立完成 fetch → 評分 → digest）

```
Step 1: Hatena     → 評分 → digest *** → 保留壓縮摘要
Step 2: HN         → 評分 → digest *** → 保留壓縮摘要
Step 3: Reddit     → 評分 → digest *** → 保留壓縮摘要
Step 4: 資安部落格 → 評分 → digest *** → 保留壓縮摘要
Step 5: 跨來源去重 → 生成報告（從壓縮摘要，不再需要原始資料）
Step 6: 存檔報告 + digest + 更新索引
Step 7: 回傳完成訊息
Step 8: Telegram 通知
```

**Token 節省原理**：每個來源的原始 HTML/JSON 在產出壓縮摘要後即不再擴張 context；生成報告時 context 只有摘要，而非全量原始資料。

## 常數

```
VAULT_ROOT = $HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Second-Brain
OUTPUT_DIR = {VAULT_ROOT}/01 Projects/daily-brief
INDEX_FILE = {VAULT_ROOT}/01 Projects/daily-brief/_daily-brief.md
SCRIPTS    = {VAULT_ROOT}/Scripts/daily-brief
```

## 注意事項

- **所有 .md 檔案操作必須使用 Python**（`open(path, "w")`），Write / Edit 工具被 hook 封鎖
- Reddit 使用 Bash + curl，不用 WebFetch（WebFetch 封鎖 reddit.com）
- HN 使用 WebFetch 取得 HTML 首頁，LLM 直接解讀，**不用** Algolia API
- 輸出語言：**繁體中文**（英文、日文標題均需翻譯）

## WebFetch digest 門檻（高分才抓原文）

只有同時符合「評為 ***」**且**分數超過門檻的文章才執行 WebFetch 取原文：

| 來源 | 門檻 |
|------|------|
| Hatena | 書籤數 > 100 |
| HN | 分數 > 200 |
| Reddit | upvotes > 300 |
| Step 4/5 | 只要評為 *** 即抓（通常量少） |

若當日無符合條件者，退而取分數最高的前 3 篇執行 digest。

---

## Step 0：使用者興趣領域

用於評定每篇文章的興趣度（***/**/*）：

- AI（開發工具、資安應用、倫理議題）
- Web 資安 / 滲透測試（OWASP、漏洞、供應鏈攻擊）
- OSS 開發與社群
- 獨立開發 / SaaS（Technical SEO、Growth Hacking、變現）
- 職涯 / 人生哲學（財務自由、外商轉職、Build in Public）
- JavaScript / TypeScript 技術棧
- AI 開發工具（Claude Code、Cursor、Gemini、ChatGPT、Claude 功能更新、工具比較、實戰心得）
  - 功能公告、教學、深度比較 → `***`
  - 社群討論、使用心得 → `**`

**跨步驟狀態**：初始化 `all_digests = []`，每個來源步驟將 *** 文章摘要 append 進去，供 Step 6 去重與 Step 7 存檔使用。

---

## Step 1：Hatena Bookmark IT（日本市場）

### 1a：抓取

使用 WebFetch 取得以下頁面，LLM 解讀 HTML：

- https://b.hatena.ne.jp/hotentry/it
- https://b.hatena.ne.jp/hotentry/it/AI%E3%83%BB%E6%A9%9F%E6%A2%B0%E5%AD%A6%E7%BF%92

每個 entry 取得：**標題（翻譯為繁體中文）、原文 URL、書籤數**
注意：取原文 URL，不是 はてブ 頁面 URL。

### 1b：評分 + digest ***（門檻：書籤數 > 100）

對每篇文章評定興趣度（***/**/*）。

對每篇「*** 且書籤數 > 100」的文章執行 digest：
- 使用 WebFetch 取得原文內容
- 生成 3–5 行繁體中文摘要（核心訊息）
- append 到 `all_digests`：`{"title": ..., "url": ..., "source": "Hatena", "summary": ...}`

若無符合門檻者，取分數最高的前 3 篇執行 digest。

### 1c：保留壓縮結果

```python
hatena_articles = [
    {"title": "...", "url": "...", "bookmarks": 123, "interest": "***", "category": "AI"},
]
```

---

## Step 2：Hacker News（全球）

### 2a：抓取

使用 WebFetch 取得 https://news.ycombinator.com/

LLM 解讀 HTML，取得每篇文章：
- **標題**（翻譯為繁體中文）
- **HN 討論頁 URL**：格式為 `https://news.ycombinator.com/item?id={id}`
- **分數**（points）

**重要**：連結一律使用 HN 討論頁 URL（`item?id=` 格式），**不使用原文 URL**。

### 2b：評分 + digest ***（門檻：分數 > 200）

對每篇「*** 且分數 > 200」的文章執行 digest：

```bash
curl -s "https://hn.algolia.com/api/v1/items/{item_id}" | jq '{title, url, text, children: [.children[:5][].text]}'
```

生成 3–5 行繁體中文摘要（核心訊息 + 社群反應），append 到 `all_digests`：
`{"title": ..., "url": "https://news.ycombinator.com/item?id=...", "source": "HN", "summary": ...}`

若無符合門檻者，取分數最高的前 3 篇執行 digest。

### 2c：保留壓縮結果

```python
hn_articles = [
    {"title": "...", "url": "https://news.ycombinator.com/item?id=...", "score": 456, "interest": "***", "category": "Security"},
]
```

---

## Step 3：Reddit（16 個子版）

### 3a：抓取

```bash
VAULT="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Second-Brain"
reddit_json=$(bash "$VAULT/Scripts/daily-brief/fetch_reddit.sh")
```

`reddit_json` 為 JSON array，每個元素格式：

```json
{"subreddit": "r/netsec", "category": "資安類", "posts": [
  {"title": "...", "score": 123, "num_comments": 45, "permalink": "/r/...", "url": "https://www.reddit.com/r/..."}
]}
```

### 子版清單（16 個）

**資安類（2）：** r/netsec, r/cybersecurity

**AI 類（3）：** r/OpenAI, r/LocalLLaMA, r/ClaudeCode

**AI 開發工具類（3）：** r/cursor_ai, r/ChatGPT, r/GoogleGeminiAI

**核心技術類（2）：** r/programming, r/technology

**OSS／獨立開發類（4）：** r/opensource, r/indiehackers, r/webdev, r/javascript

**職涯／實踐類（2）：** r/cscareerquestions, r/productivity

### 3b：評分 + digest ***（門檻：upvotes > 300）

對每篇「*** 且 upvotes > 300」的文章執行 digest（分兩次 curl）：

```bash
curl -s -H "User-Agent: daily-brief/1.0" \
  "https://old.reddit.com/r/{sub}/comments/{id}.json" \
  | jq '.[0].data.children[0].data | {title, url, selftext, is_self}'

curl -s -H "User-Agent: daily-brief/1.0" \
  "https://old.reddit.com/r/{sub}/comments/{id}.json" \
  | jq '[.[1].data.children[:8][].data | select(.body) | {body: .body[0:500], score}]'
```

生成 3–5 行繁體中文摘要，append 到 `all_digests`：
`{"title": ..., "url": "https://www.reddit.com/...", "source": "r/{sub}", "summary": ...}`

若無符合門檻者，取分數最高的前 3 篇執行 digest。

### 3c：保留壓縮結果

```python
reddit_articles = {
    "資安類": [...], "AI 類": [...], "AI 開發工具類": [...],
    "核心技術類": [...], "OSS・獨立開發類": [...], "職涯・實踐類": [...],
}
```

---

## Step 4：資安部落格

### 4a：抓取

使用 WebFetch 取得：
- https://www.aikido.dev/blog
- https://www.wiz.io/blog

檢查最新 1–3 篇文章。

### 4b：評分 + digest ***

只有 *** 的才納入。立即 WebFetch 原文 + 生成摘要，append 到 `all_digests`：
`{"title": ..., "url": ..., "source": "aikido.dev/wiz.io", "summary": ...}`

### 4c：保留壓縮結果

```python
security_articles = [{"title": "...", "url": "...", "source": "aikido.dev", "interest": "***"}]
```

---

## Step 5：跨來源去重 + 生成報告

### 5a：去重 all_digests

相同事件被多來源報導時，只保留一篇。優先順序：**部落格 > Reddit > HN > Hatena**

### 5b：產生繁體中文報告

從各來源的壓縮清單生成報告（不需要重新讀取原始 HTML）。輸出格式：

```markdown
# 趨勢話題：YYYY-MM-DD

## Hatena Bookmark IT（日本市場）
### 注目話題
| 標題 | 書籤數 | 興趣度 | 類別 | 備註 |
|------|--------|--------|------|------|
| [標題](URL) | XXX | *** | AI | 切入點 |

### 全部文章
1. [標題](URL) (XXX users) — 一行摘要

## Hacker News（全球）
### 注目話題
| 標題 | 分數 | 興趣度 | 類別 | 備註 |
|------|------|--------|------|------|
| [標題](HN item URL) | XXXpt | *** | Security | 切入點 |

### 全部文章
1. [標題](HN item URL) (XXXpt) — 一行摘要

## Reddit（16 個子版）
### 注目話題
| 標題 | 票數 | 留言數 | 興趣度 | 類別 | 子版 | 備註 |
### 依類別列表（資安類 / AI 類 / AI 開發工具類 / 核心技術類 / OSS・獨立開發類 / 職涯・實踐類）
1. [標題](URL) (XXX ups, XXX comments) — r/sub — 一行摘要

## 資安部落格
| 標題 | 來源 | 興趣度 | 備註 |
```

---

## Step 6：存檔報告 + digest + 更新索引（Python）

```python
import sys
from datetime import date

SCRIPTS = "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Second-Brain/Scripts/daily-brief"
sys.path.insert(0, SCRIPTS)
from save_output import save_report, save_digest

today = date.today().strftime("%Y-%m-%d")
save_report(report_content, today)   # 同時更新 _daily-brief.md 索引
save_digest(all_digests, today)      # all_digests 為空時自動略過
```

---

## Step 7：回傳完成訊息

輸出：

「趨勢收集完成。已儲存至 `01 Projects/daily-brief/YYYY-MM-DD.md`。」

---

## Step 8：Telegram 通知

**使用 `send-telegram` skill 處理傳送邏輯（載入憑證、guard 檢查、4096 字元截斷）。**

### 8a：產出訊息 1（LLM）

從 context 中的 `all_digests` 與 Step 5b 報告，依主題分群，每群列出 3–5 個重點，輸出 **HTML 格式**（Telegram parse_mode=HTML）。

格式規則：
- 每個 bullet：`• <b><a href="URL">標題</a></b> — 2–3 句說明（核心內容與重要性，不加書籤數/票數等數字）`
- 標題群組加 emoji：🤖 Claude Code / 🔐 資安 / 🛠️ AI 開發工具 / 💼 職涯 / 📰 其他（依當日實際內容選用）
- URL 使用原始文章 URL（非 hatena/reddit 聚合頁）
- 禁用 `**`、`_`、`[text](url)` 等 Markdown 符號，只用 HTML tag
- 訊息不超過 4096 字元

格式範例：
```
今日重點摘要（YYYY-MM-DD）：

🤖 Claude Code 狂熱
• <b><a href="https://...">標題</a></b> — 核心理念是「讓 AI 代勞而非先自學」。涵蓋 MCP、Skills、記憶功能，是目前最完整的入門資源

🔐 資安警示
• ...
```

### 8b：傳送訊息 1

執行 `send-telegram` skill，傳入 msg1。

### 8c：產出訊息 2（LLM，僅在 all_digests 非空時執行）

從 `all_digests` 中挑選與訊息 1 重點相關的文章，輸出完整摘要原文（標題 + 段落 + 原始URL），不超過 4096 字元，輸出純文字（不要 markdown 代碼塊）。

### 8d：傳送訊息 2（僅在 8c 執行時）

執行 `send-telegram` skill，傳入 msg2。
