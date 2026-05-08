# Daily Brief MCP Server

透過 MCP 協定查詢 `outputs/daily-brief/` 下已生成的 artifact。

## 啟動

```bash
# 在專案根目錄執行
python agents/daily_brief/mcp_server/server.py
```

伺服器使用 stdio 傳輸，適合直接作為 Claude Code 的 MCP server。

## 設定（Claude Code）

在 `.claude/settings.json` 加入：

```json
{
  "mcpServers": {
    "daily-brief": {
      "command": "python",
      "args": ["agents/daily_brief/mcp_server/server.py"]
    }
  }
}
```

## 可用工具

### `list_recent_briefs(days: int = 7)`

列出最近 N 天有哪些 brief，回傳元數據清單。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `date` | str | 日期（YYYY-MM-DD） |
| `has_digest` | bool | 是否有 digest.json |
| `has_report` | bool | 是否有 report.md |
| `digest_count` | int | 摘要篇數 |
| `themes` | list[str] | 主題標籤（最多 10 個） |

### `search_recent_digests(query: str, days: int = 7)`

關鍵字搜尋最近 N 天的 digest 內容（AND 邏輯，不分大小寫）。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `date` | str | 日期 |
| `title` | str | 文章標題 |
| `url` | str | 原文 URL |
| `source` | str | 來源（Hatena / HN / ...） |
| `interest` | str | 興趣度（*** / ** / *） |
| `summary` | str | 摘要內容 |

## 前置條件

```bash
pip install fastmcp
```
