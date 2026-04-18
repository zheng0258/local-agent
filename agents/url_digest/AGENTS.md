# UrlDigest Agent

接收一或多個 URL，生成繁體中文摘要，存入 Second Brain。同日多次執行時追加至現有檔案。

## 觸發條件

- `/url-digest <URL1> [URL2 ...]`
- 「幫我摘要這些連結」、「digest these URLs」、「summarize this article」

## 輸入

`args`：一或多個 URL（空格或換行分隔）

## 輸出

摘要存至 `{VAULT}/01 Projects/daily-digest/url-digest/YYYY-MM-DD.md`

## URL 類型分類（確定性）

| 類型 | 判斷條件 | 抓取方式 |
|------|---------|--------|
| 一般文章 | 其他 | urllib |
| Hacker News | `news.ycombinator.com/item?id=` | HN Algolia API |
| Reddit | `reddit.com/r/` + `/comments/` | Bash curl × 2 |
| X / Twitter | `x.com/` 或 `twitter.com/` | chrome-devtools-mcp（需瀏覽器）|

## 依賴

無外部 agent 依賴，純工具層操作。
