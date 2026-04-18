---
name: url-digest
description: Use when someone pastes URLs and asks to summarize them. Triggered by /url-digest followed by one or more URLs, or phrases like "幫我摘要這些連結", "digest these URLs", "summarize this article".
argument-hint: <URL1> [URL2 ...] (space or newline separated)
disable-model-invocation: true
---

## 功能說明

接收一或多個 URL，摘要各文章的核心訊息（繁體中文），並附上社群反應（HN／Reddit）。結果存入 Second Brain。

## 常數

```
VAULT_ROOT = $HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Second-Brain
OUTPUT_DIR = {VAULT_ROOT}/01 Projects/daily-digest/url-digest
INDEX_FILE = {VAULT_ROOT}/01 Projects/daily-digest/_daily-digest.md
```

## 注意事項

- **所有 .md 檔案操作必須使用 Python**（`open(path, "w")` 或 `open(path, "a")`），Write / Edit 工具被 hook 封鎖
- 同一天多次執行：**追加**至現有檔案，不覆蓋；追加時先寫 `
---

` 分隔符
- Reddit 使用 Bash + curl（WebFetch 封鎖 reddit.com）
- X/Twitter 使用 chrome-devtools-mcp 瀏覽器自動化（WebFetch 無法渲染 JS）
- 輸出語言：**繁體中文**（英文、日文標題均需翻譯）

---

## Step 1：解析輸入

從使用者輸入中提取所有 URL（換行或空格分隔）。對每個 URL 依序處理。

---

## Step 2：判斷 URL 類型

| 類型 | 判斷條件 | 處理方式 |
|------|---------|--------|
| X / Twitter | `x.com/` 或 `twitter.com/` | chrome-devtools-mcp 瀏覽器自動化 |
| Hacker News | `news.ycombinator.com/item?id=` | HN Algolia API + WebFetch 原文 |
| Reddit | `reddit.com/r/` 且含 `/comments/` | Bash curl JSON + WebFetch 原文 |
| 一般文章 | 其他所有 URL | WebFetch |

---

## Step 3a：一般文章

使用 WebFetch 取得頁面，提取標題與正文，摘要核心訊息。

---

## Step 3b：X / Twitter

使用 chrome-devtools-mcp 工具（需先確認 Chrome 以 `--remote-debugging-port=9222` 啟動）：

```
1. list_pages          → 確認目前開啟的標籤（createIfEmpty 參數）
2. new_page            → 開啟新標籤
3. navigate_page       → 前往 x.com/... URL
4. wait_for            → 等待頁面載入（約 2–3 秒）
5. take_snapshot       → 取得頁面 DOM / 文字內容
```

擷取內容：推文正文、作者名稱／帳號、媒體說明（有圖片／影片時）、回覆／引用脈絡

**注意**：若出現 tool-not-found 錯誤，請確認實際工具名稱（`chrome-devtools-mcp` 提供的工具可能因版本不同而異）。若 Chrome 未以 `--remote-debugging-port=9222` 啟動，瀏覽器工具無法使用，請回傳說明訊息。

---

## Step 3c：Hacker News

從 URL 取出 item_id（`item?id=XXXXX` 中的 XXXXX），呼叫 Algolia API：

```bash
curl -s "https://hn.algolia.com/api/v1/items/{item_id}" | jq '.'
```

資料欄位：
- `title`：文章標題
- `url`：原文 URL（null 表示 HN 貼文本身就是內容，用 `text` 欄位）
- `points`：分數
- `children`：留言陣列（各含 `text` 欄位）

步驟：
1. Algolia API 取得結構化資料
2. 若 `url` 不為 null：WebFetch 取得原文
3. 分析前 5 則留言（`children[:5]`），擷取洞見與反論

---

## Step 3d：Reddit

**重要**：分兩次獨立 curl 查詢（合併執行會導致 jq 錯誤）

從 URL 解析出 `{subreddit}` 和 `{post_id}`（格式：`reddit.com/r/{subreddit}/comments/{post_id}/`）

```bash
# 查詢 1：投稿資訊
curl -s -H "User-Agent: url-digest/1.0"   "https://old.reddit.com/r/{subreddit}/comments/{post_id}.json"   | jq '.[0].data.children[0].data | {title, url, selftext, is_self}'

# 查詢 2：留言（獨立執行）
curl -s -H "User-Agent: url-digest/1.0"   "https://old.reddit.com/r/{subreddit}/comments/{post_id}.json"   | jq '[.[1].data.children[:8][].data | select(.body) | {body: .body[0:500], score}]'
```

使用 `select(.body)` **不用** `select(.body != null)`（驚嘆號在 shell 有特殊意義）

步驟：
1. 取得投稿資訊
2. 若 `is_self` 為 false 且 `url` 是外部連結：WebFetch 取得原文
3. 若 `is_self` 為 true：`selftext` 就是內容，不需 WebFetch
4. 分析前 8 則留言，擷取洞見與反論

---

## Step 4：摘要生成

對每個 URL 生成：

- **標題**：原標題，英文／日文翻譯為繁體中文
- **摘要**：3–5 行，核心訊息 + 社群反應（HN／Reddit 適用）
- **URL**：**原始輸入的 URL**（HN、Reddit 不換成原文 URL）

---

## Step 5：存檔（Python）

```python
import os
from datetime import date

VAULT = "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Second-Brain"
today = date.today().strftime("%Y-%m-%d")
output_path = f"{VAULT}/01 Projects/daily-digest/url-digest/{today}.md"

os.makedirs(os.path.dirname(output_path), exist_ok=True)

# article_content = 各文章的 markdown 段落（## 標題 + 摘要 + URL）

if not os.path.exists(output_path):
    # 新建：含 header
    with open(output_path, "w") as f:
        f.write(f"# URL Digest：{today}\n\n---\n\n" + article_content)
else:
    # 同日追加：先加分隔符
    with open(output_path, "a") as f:
        f.write("\n---\n\n" + article_content)

print(f"已儲存：{output_path}")
```

每篇文章的輸出格式：

```markdown
## [文章標題（繁體中文）]

摘要 3–5 行。核心訊息，社群反應（若適用）。

原始 URL
```

---

## Step 6：更新 _daily-digest.md 索引（Python）

```python
import os
from datetime import date

VAULT = "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Second-Brain"
today = date.today().strftime("%Y-%m-%d")
index_path = f"{VAULT}/01 Projects/daily-digest/_daily-digest.md"

with open(index_path, "r") as f:
    existing = f.read()

row_marker = f"| url-digest | {today} |"
if row_marker not in existing:
    new_row = f"| [[01 Projects/daily-digest/url-digest/{today}|{today}]] | url-digest | {today} |\n"
    with open(index_path, "a") as f:
        f.write(new_row)
    print(f"索引已更新：{today} url-digest")
else:
    print("索引已存在，略過。")
```

---

## Step 7：回傳完成訊息

輸出：

「摘要完成。已儲存至 `01 Projects/daily-digest/url-digest/YYYY-MM-DD.md`。」
