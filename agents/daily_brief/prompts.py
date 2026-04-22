"""Daily Brief — 所有 LLM prompts。"""

from .config import (
    FALLBACK_TOP_N,
    HATENA_DIGEST_THRESHOLD,
    HN_DIGEST_THRESHOLD,
    REDDIT_DIGEST_THRESHOLD,
)

# ── 系統 prompt ──────────────────────────────────────────────────

SYSTEM = """\
你是一個科技趨勢分析 agent。
輸出語言：繁體中文（英文、日文標題均需翻譯）。
需要結構化輸出時，回傳合法 JSON（可用 ```json 包裹）。
JSON 規範：key 與 value 之間必須用半形冒號加空白 ": " 分隔，禁止使用全形冒號「：」；\
字串值中若含雙引號必須逸脫為 \"。\
"""

# ── 使用者興趣定義（評分依據）────────────────────────────────────

INTEREST_CRITERIA = """\
評分標準（*** / ** / *）：
- *** AI 開發工具（Claude Code、Cursor、Gemini 功能公告、工具比較）
- *** Web 資安 / 滲透測試（OWASP、漏洞、供應鏈攻擊）
- **  OSS 開發 / 獨立開發 / SaaS / Technical SEO
- **  JavaScript / TypeScript 技術棧
- *   職涯 / 財務自由 / Build in Public
- *   其他科技話題\
"""

_FEW_SHOT = """\
評分範例（邊界參考）：
- *** ：「Claude Code 新增 MCP 整合功能」「CVE-2025-XXXX Nginx 遠端執行漏洞」「供應鏈攻擊：axios npm 套件遭入侵」
- **  ：「Next.js 15 效能優化實戰心得」「獨立開發者月收 5000 美元方法論」「TypeScript 5.5 新特性介紹」
- *   ：「2025 年程式設計師薪資報告」「如何提升遠端工作效率」「某技術工具發布 2.0 版」
- 略過：廣告、問卷調查、非科技話題、已知的老文章重新流傳\
"""


def _scoring_block() -> str:
    return f"{INTEREST_CRITERIA}\n\n{_FEW_SHOT}"


# ── Step 1：Hatena 評分 ────────────────────────────────────────────

def build_hatena_prompt(articles_json: str) -> str:
    return f"""\
## 文章清單（Hatena Bookmark IT）

{articles_json}

## 任務

對每篇文章依以下標準評定興趣度：
{_scoring_block()}

## 輸出格式

```json
{{
  "articles": [
    {{"title": "繁體中文標題", "url": "原文URL", "bookmarks": 123, "interest": "***", "category": "AI"}}
  ]
}}
```\
"""

# ── Step 2：HN 評分 ────────────────────────────────────────────────

def build_hn_prompt(articles_json: str) -> str:
    return f"""\
## 文章清單（Hacker News）

{articles_json}

## 任務

對每篇文章評定興趣度：
{_scoring_block()}

連結一律使用 HN 討論頁 URL（https://news.ycombinator.com/item?id=...）。

## 輸出格式

```json
{{
  "articles": [
    {{"title": "繁體中文標題", "url": "https://news.ycombinator.com/item?id=...", "score": 456, "interest": "***", "category": "Security"}}
  ]
}}
```

注意：key 後必須用半形 ": " 分隔，禁用全形冒號「：」；標題中若含雙引號須逸脫為 \"。\
"""

# ── Step 3：Reddit 評分 ────────────────────────────────────────────

def build_reddit_prompt(posts_json: str) -> str:
    return f"""\
## 文章清單（Reddit 16 子版）

{posts_json}

## 任務

對每篇文章評定興趣度：
{_scoring_block()}

## 輸出格式

```json
{{
  "articles": {{
    "資安類": [{{"title": "...", "url": "...", "score": 123, "interest": "***", "category": "資安", "subreddit": "r/cybersecurity"}}],
    "AI 類": [...],
    "AI 開發工具類": [...],
    "核心技術類": [...],
    "OSS・獨立開發類": [...],
    "職涯・實踐類": [...]
  }}
}}
```

注意：標題中若含雙引號須逸脫為 \"；key 後必須用半形 ": " 分隔。\
"""

# ── Step 4：資安部落格 ────────────────────────────────────────────

def build_security_blogs_prompt(content: str) -> str:
    return f"""\
## 資安部落格內容（aikido.dev / wiz.io）

{content}

## 任務

識別最新 1–3 篇文章，評定興趣度（只保留 ***）。
{_scoring_block()}

## 輸出格式

```json
{{
  "articles": [
    {{"title": "...", "url": "...", "source": "aikido.dev", "interest": "***"}}
  ]
}}
```\
"""

# ── Step compress：每來源語義壓縮 ─────────────────────────────────────

def build_compress_prompt(source_name: str, articles_json: str) -> str:
    return f"""\
## {source_name} *** 文章（已由程式預先篩選，全部為最高興趣度）

{articles_json}

## 任務

1. 識別 2–3 個主題群（themes）
2. 為**每一篇**文章產生 ≤20 字繁體中文 one-liner（核心訊息，不加書籤數/票數）
3. 保留全部文章，**禁止丟棄任何一篇**

## 輸出格式

```json
{{
  "themes": ["主題一", "主題二"],
  "articles": [
    {{"title": "繁體中文標題", "url": "原始URL", "one_liner": "20字內核心摘要", "interest": "***"}}
  ]
}}
```\
"""

# ── Step 5：跨來源生成深度摘要 ──────────────────────────────────────

def build_digest_prompt(
    hatena_json: str,
    hn_json: str,
    reddit_json: str,
    security_json: str,
) -> str:
    return f"""\
## 評分後文章（各來源）

### Hatena Bookmark IT
{hatena_json}

### Hacker News
{hn_json}

### Reddit
{reddit_json}

### 資安部落格
{security_json}

## 任務

對符合門檻的文章生成 3–5 行繁體中文深度摘要（核心訊息、影響範圍、值得關注的原因）：

門檻：
- Hatena：interest = *** 且 bookmarks > {HATENA_DIGEST_THRESHOLD}
- HN：interest = *** 且 score > {HN_DIGEST_THRESHOLD}
- Reddit：interest = *** 且 score > {REDDIT_DIGEST_THRESHOLD}
- 資安部落格：所有 *** 文章
- 若某來源無符合門檻者，取該來源前 {FALLBACK_TOP_N} 篇（依分數排序）

標題一律翻譯為繁體中文。

## 輸出格式

```json
{{
  "digests": [
    {{
      "title": "繁體中文標題",
      "url": "原始文章 URL（禁止自行編造）",
      "source": "Hatena / HN / r/子版名稱 / aikido.dev / wiz.io",
      "interest": "***",
      "summary": "3–5 行摘要"
    }}
  ]
}}
```\
"""

# ── Step 6：生成報告 ───────────────────────────────────────────────

def build_report_prompt(
    hatena_json: str,
    hn_json: str,
    reddit_json: str,
    security_json: str,
    digests_json: str,
) -> str:
    return f"""\
## 來源資料（已評分）

### Hatena
{hatena_json}

### Hacker News
{hn_json}

### Reddit
{reddit_json}

### 資安部落格
{security_json}

### 精選摘要（已去重）
{digests_json}

## 任務

生成繁體中文趨勢報告，格式如下（去重已由程式完成，無需重複處理）：

```markdown
# 趨勢話題：{{today}}

## Hatena Bookmark IT（日本市場）
### 注目話題
| 標題 | 書籤數 | 興趣度 | 類別 | 備註 |
|------|--------|--------|------|------|
| [標題](URL) | XXX | *** | AI | 切入點 |

### 全部文章
1. [標題](URL) (XXX users) — 一行摘要

## Hacker News（全球）
...（同上格式）

## Reddit（16 個子版）
...

## 資安部落格
| 標題 | 來源 | 興趣度 | 備註 |
```

## 輸出格式

```json
{{"report_content": "完整 markdown 報告"}}
```\
"""

# ── Step digest v2：吃 compress.json ──────────────────────────────────

def build_digest_prompt_from_compress(compress_json: str) -> str:
    return f"""\
## 壓縮後文章（compress.json，每篇均已是 ***，含 one_liner）

{compress_json}

## 任務

對**每一篇**文章生成 3–5 行繁體中文深度摘要：
- 核心訊息（這項技術/事件是什麼）
- 影響範圍（誰受影響、規模）
- 值得關注的原因（為何現在重要）

禁止：跳過任何一篇、自行編造 URL、修改 URL

## 輸出格式

```json
{{
  "digests": [
    {{
      "title": "繁體中文標題",
      "url": "原始 URL（完整複製，禁止修改）",
      "source": "Hatena / HN / r/子版名稱 / aikido.dev / wiz.io",
      "interest": "***",
      "summary": "3–5 行摘要"
    }}
  ]
}}
```"""


# ── Step report v2：吃 compress.json ─────────────────────────────────

def build_report_prompt_from_compress(compress_json: str, digests_json: str, today: str = "") -> str:
    return f"""\
## 壓縮後來源資料（主題 + 精選文章）

{compress_json}

### 精選摘要（已去重）
{digests_json}

## 任務

生成繁體中文趨勢報告，**嚴格**依照以下格式，不得新增或刪除任何章節：

```markdown
# 趨勢話題：{today}

---

## Hatena Bookmark IT（日本市場）

### 注目話題

| 標題 | 書籤數 | 興趣度 | 類別 | 備註 |
|------|--------|--------|------|------|
| [標題](URL) | 123 | *** | AI 開發工具 | 一句切入點 |

### 全部文章（略）

1. [標題](URL) (123 users) — 一行摘要

---

## Hacker News（全球）

### 注目話題

| 標題 | 分數 | 興趣度 | 類別 | 備註 |
|------|------|--------|------|------|
| [標題](URL) | 1234pt | *** | AI | 一句切入點 |

### 全部文章（部分）

1. [標題](URL) (1234pt) — 一行摘要

---

## Reddit（16 個子版）

### 注目話題

| 標題 | 票數 | 留言數 | 興趣度 | 類別 | 子版 | 備註 |
|------|------|--------|--------|------|------|------|
| [標題](URL) | 1234 | 56 | *** | 資安 | r/cybersecurity | 一句切入點 |

### 依類別列表

**資安類**
1. [標題](URL) (1234 ups) — r/xxx — 一行摘要

**AI 類**
1. [標題](URL) (1234 ups) — r/xxx — 一行摘要

---

## 資安部落格

| 標題 | 來源 | 興趣度 | 備註 |
|------|------|--------|------|
| [標題](URL) | aikido.dev | *** | 一句切入點 |

---

## 今日總結

### 三大焦點議題
1. **【主題標籤】** — 2-3 句說明跨平台共同關注點
2. **【主題標籤】** — 2-3 句說明
3. **【主題標籤】** — 2-3 句說明

### 跨平台熱點重疊
- **話題名稱**：Hatena + HN + Reddit 同步出現 — 一句說明
- **話題名稱**：HN + r/cybersecurity — 一句說明
```

**輸出要求**：
- 直接輸出完整 markdown，不要包成 JSON
- 第一行必須是 `# 趨勢話題：{today}`
- 章節順序與名稱必須與上方完全一致，不得增減
- Reddit 使用 `### 注目話題` + `### 依類別列表` 兩層，禁止展開成個別子版標題
- `## 今日總結` 是最後章節，其後不得新增任何內容
"""


# ── Step judge：LLM-as-Judge 評估 digest 品質 ─────────────────────────

def build_judge_prompt(compress_json: str, digest_json: str) -> str:
    return f"""\
## 可用文章（compress.json -- 已篩選 *** + 主題分群）

{compress_json}

## 生成的摘要（digest.json）

{digest_json}

## 任務

評估摘要品質，回傳三個維度的評分（1-5）與理由。

- Relevance（相關性）：選出的文章是否符合 AI 工具、資安、開發相關主題？
- Completeness（完整性）：compress 中的 *** 文章是否都被納入摘要？
- Faithfulness（忠實度）：摘要是否忠實反映原文標題與 one_liner？有無自行編造內容？

**重要規則**：
- 每個 reasoning 欄位只寫評分理由文字，不要在 reasoning 裡列出任何 URL
- 被遺漏的 URL 統一放在頂層 missed_urls 陣列

## 輸出格式

```json
{{
  "scores": {{
    "relevance":    {{"score": 4, "reasoning": "說明"}},
    "completeness": {{"score": 3, "reasoning": "說明（勿列 URL）"}},
    "faithfulness": {{"score": 5, "reasoning": "說明"}}
  }},
  "missed_urls": [],
  "overall": 4.0
}}
```\
"""

# ── Step 7：Telegram 訊息 ─────────────────────────────────────────

def build_telegram_overview_prompt(all_digests_json: str, today: str) -> str:
    return f"""\
## 精選摘要

{all_digests_json}

## 任務

依主題分群，每群 3–5 個重點，生成 Telegram HTML 格式訊息。

規則：
- 只能使用 Telegram 支援的 HTML tag：<b>、<i>、<u>、<s>、<a href="...">，嚴禁 <br>、<p>、<div>、<span> 等其他 HTML tag
- 嚴格禁用 **、_、`[text](url)`、`[text][ref]` 等任何 Markdown 語法
- 每個 bullet 固定格式：• <b><a href="完整URL">繁體中文標題</a></b> — 2–3 句說明（核心內容與重要性，不加書籤數/票數等數字）
- 重要：<a href="URL"> 和 </a> 之間必須有標題文字，絕對不能寫成 <a href="URL"></b>（缺少 </a> 和標題）
- href 屬性值必須完整複製 all_digests 的 url 欄位，禁止截斷、修改、URL encode 或自行編造
- href 屬性值只能是 http/https 開頭的完整網址，不得放檔名、路徑或其他非 URL 內容
- 標題群組加 emoji：🤖 Claude Code / 🔐 資安 / 🛠️ AI 開發工具 / 💼 職涯 / 📰 其他（依當日實際內容選用）
- 總長度 ≤ 4096 字元
- 第一行：今日重點摘要（{today}）：

輸出範例（嚴格照此格式）：
今日重點摘要（{today}）：

🔐 資安
• <b><a href="https://www.aikido.dev/blog/axios-npm-compromised">axios npm 套件遭入侵：維護者帳號被劫持部署 RAT</a></b> — 說明文字在此

## 輸出格式

```json
{{"tg_overview": "HTML 格式訊息"}}
```\
"""

def build_telegram_digest_prompt(all_digests_json: str, today: str) -> str:
    return f"""\
## 精選摘要

{all_digests_json}

## 任務

從以下精選摘要（已預先篩選高品質文章）中，挑選 5–8 則生成 Telegram HTML 格式深度摘要訊息。

格式規則：
- 只能使用 Telegram 支援的 HTML tag：<b>、<i>、<u>、<s>、<a href="...">，嚴禁 <br>、<p>、<div>、<span> 等其他 HTML tag
- 嚴格禁用 **、_、`[text](url)` 等任何 Markdown 語法
- 第一行：深度摘要（{today}）：
- 每則格式：
  {{n}}. <b><a href="完整URL">繁體中文標題</a></b>
  2–3 句說明（核心內容、影響範圍、值得關注的原因）
- href 屬性值必須完整複製 all_digests 的 url 欄位，禁止截斷或自行編造
- 總長度 ≤ 4096 字元

輸出範例：
深度摘要（{today}）：

1. <b><a href="https://www.aikido.dev/blog/glassworm">GlassWorm IDE 惡意軟體</a></b>
偽裝成 VS Code 擴充套件，內含 dropper，感染多款 IDE，植入後門竊取憑證。立即移除並輪換 secrets。

2. <b><a href="https://news.ycombinator.com/item?id=12345">GitHub CI/CD 供應鏈攻擊</a></b>
利用 pull_request_target 觸發器，三週 500+ 惡意 PR，已入侵 2 個 npm 套件。AI 自動化讓規模化攻擊成本驟降。

## 輸出格式

```json
{{"tg_digest": "HTML 格式摘要"}}
```\
"""
