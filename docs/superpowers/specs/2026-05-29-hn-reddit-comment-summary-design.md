# HN / Reddit 留言摘要設計文件

**日期：** 2026-05-29
**Issue：** daily-brief #1
**狀態：** 已核准，待實作

---

## 目標

對每日 daily-brief 中評為 `***` 的 HN 與 Reddit 文章，抓取 top 10 留言並以 LLM 生成社群觀點摘要（≤ 60 字），追加至 `digest.summary` 尾段，增加脈絡深度。

---

## 架構

### Pipeline 更新

```
fetch → dedup → compress → enrich → digest → judge → report → save → notify
```

新增 `enrich` step 插入於 `compress` 與 `digest` 之間。

### ALL_STEPS 更新

```python
ALL_STEPS = [*FETCH_STEPS, "dedup", "compress", "enrich", "digest", "judge", "report", "save", "notify"]
```

---

## 元件

### 新增 Tools（純函數，無 LLM）

#### `tools/fetchers/hn_comments.py`

```python
def fetch_comments(item_id: str, top_n: int = 10) -> list[str]:
    """
    呼叫 HN Algolia API 取 top N 留言文字。
    URL: https://hn.algolia.com/api/v1/items/{item_id}
    回傳：留言文字列表（去除 HTML tag，每則截至 300 字元）
    失敗時回傳空列表（不 raise）
    """
```

- 從 HN 討論頁 URL 解析 item_id（`item?id=(\d+)` regex）
- 讀取 `response["children"][0:top_n]` 的 `text` 欄位
- 每則留言去除 HTML tag（`re.sub(r'<[^>]+>', '', text)`），截至 300 字元

#### `tools/fetchers/reddit_comments.py`

```python
def fetch_comments(post_url: str, top_n: int = 10) -> list[str]:
    """
    呼叫 Reddit JSON API 取 top N 留言文字。
    URL: {post_url}.json?limit=10&sort=best
    回傳：留言文字列表（每則截至 300 字元）
    失敗時回傳空列表（不 raise）
    """
```

- 對 `post_url` 補上 `.json?limit=10&sort=best`
- 解析 `response[1]["data"]["children"][0:top_n]` 的 `data.body` 欄位
- 過濾 `[deleted]`、`[removed]` 內容

### 修改 Agent

#### `agents/daily_brief/agent.py`

新增方法：

```python
def _phase_enrich(self, ctx: _RunContext, compress_data: dict) -> dict:
    """compress 後、digest 前：對 HN/Reddit *** 文章並行抓留言 → LLM 摘要。"""

def _run_enrich(self, compress_data: dict) -> dict:
    """
    對 compress_data 中 hn/reddit 來源的每篇文章，
    用 ThreadPoolExecutor(max_workers=4) 並行抓留言。
    回傳 enrich_data（與 compress_data 相同結構，新增 comment_summary 欄位）。
    """
```

### 修改 Prompts

#### `agents/daily_brief/prompts.py`

新增：

```python
def build_comment_summary_prompt(source: str, title: str, comments_json: str) -> str:
    """
    輸入：留言列表（JSON array of strings）
    輸出：{"comment_summary": "≤60 字社群觀點摘要"}
    """
```

更新 `build_digest_prompt_from_compress`：若文章有 `comment_summary` 欄位，
在生成摘要時將其納入 prompt context，並指示在 `summary` 尾段追加：

```
💬 社群觀點：[comment_summary 內容]
```

---

## Artifact 結構

### `steps/enrich.json`

與 `compress.json` 結構相同，對 `hn`/`reddit` 來源文章新增 `comment_summary`：

```json
{
  "_meta": { "enriched_at": "2026-05-29T01:00:00" },
  "hn": {
    "themes": ["主題一", "主題二"],
    "articles": [
      {
        "title": "...",
        "url": "https://news.ycombinator.com/item?id=...",
        "one_liner": "...",
        "interest": "***",
        "comment_summary": "社群對此有兩派觀點：A 認為... B 則指出..."
      }
    ]
  },
  "reddit": { "（同上結構）": "..." },
  "hatena": { "（直接複製 compress 內容，無 comment_summary）": "..." },
  "security": { "（直接複製 compress 內容，無 comment_summary）": "..." },
  "rss": { "（直接複製 compress 內容，無 comment_summary）": "..." }
}
```

### Digest summary 格式

```
（原有 3–5 行摘要文字）

💬 社群觀點：主流討論集中在效能問題，部分用戶反映遷移路徑不清晰。
```

若文章無 `comment_summary`（抓取失敗或非 HN/Reddit 來源），`summary` 不變。

---

## 留言抓取規格

| 來源 | API endpoint | 解析路徑 | 每則上限 |
|------|-------------|---------|---------|
| HN | `https://hn.algolia.com/api/v1/items/{id}` | `children[0:10].text` | 300 字元 |
| Reddit | `{post_url}.json?limit=10&sort=best` | `[1].data.children[0:10].data.body` | 300 字元 |

---

## 錯誤處理

| 情境 | 行為 |
|------|------|
| 單篇文章留言 fetch 失敗（timeout / 4xx / JSON 解析錯） | log warning，該文章無 `comment_summary`，繼續 |
| 所有文章 fetch 全部失敗 | enrich.json 仍正常寫入（無 comment_summary），digest 正常執行 |
| enrich LLM 回傳空字串或無效 JSON | 該文章無 `comment_summary`，繼續 |
| enrich artifact 已存在（非 `--force enrich`） | 直接載入，跳過所有網路請求 |
| HN URL 無法解析 item id | skip，log debug |
| Reddit body 為 `[deleted]` 或 `[removed]` | 過濾該則留言 |

---

## 並行執行

`_run_enrich()` 使用 `ThreadPoolExecutor(max_workers=4)` 對所有 *** 文章並行抓取留言（HN + Reddit 合計，通常 5–15 篇）。個別失敗不影響其他文章。

---

## 測試計畫

### 新增測試檔案

```
tests/tools/fetchers/test_hn_comments.py
tests/tools/fetchers/test_reddit_comments.py
tests/agents/test_enrich_step.py
```

### 覆蓋 Case

1. **正常路徑**：mock HTTP 回傳留言 → enrich.json 含 `comment_summary`
2. **部分失敗**：一篇 fetch 失敗 → 其他文章仍有 `comment_summary`，失敗文章無此欄位
3. **全部失敗**：enrich.json 正常寫入（所有文章無 `comment_summary`），digest 可讀取
4. **Idempotent**：enrich artifact 存在時，直接回傳，不發任何 HTTP 請求
5. **HN URL 解析**：`item?id=12345` 正確提取 `12345`；無效格式 skip

---

## 不在此 Issue 範圍內

- Reddit 留言的子留言（只取頂層 top 10）
- 留言排序方式自訂（固定用 `sort=best`）
- Web 背景增強（#2）：另立 issue，共用 `enrich` step
- Hatena / security_blogs / RSS 的留言（這些來源無公開留言 API）
