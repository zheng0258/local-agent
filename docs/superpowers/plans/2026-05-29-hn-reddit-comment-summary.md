# HN / Reddit 留言摘要（enrich step）實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 對每日 daily-brief 中評為 `***` 的 HN 與 Reddit 文章，抓取 top 10 留言並以 LLM 生成社群觀點摘要（≤ 60 字），追加至 `digest.summary` 尾段。

**Architecture:** 新增獨立 `enrich` step 插入 `compress` 與 `digest` 之間，產生 `steps/enrich.json`（= compress.json 結構 + HN/Reddit 文章的 `comment_summary` 欄位）。两個純函數 fetcher tool（`hn_comments.py`、`reddit_comments.py`）負責網路請求，agent 的 `_run_enrich()` 用 `ThreadPoolExecutor` 並行呼叫，個別失敗 best-effort 跳過。

**Tech Stack:** Python 3.11+、`urllib.request`（stdlib）、`subprocess curl`（Reddit）、`ThreadPoolExecutor`、現有 LLM backend

---

## 檔案地圖

| 操作 | 路徑 | 職責 |
|------|------|------|
| Create | `tools/fetchers/hn_comments.py` | HN Algolia API 留言抓取（純函數） |
| Create | `tools/fetchers/reddit_comments.py` | Reddit JSON API 留言抓取（純函數） |
| Create | `tests/tools/fetchers/test_hn_comments.py` | hn_comments 單元測試 |
| Create | `tests/tools/fetchers/test_reddit_comments.py` | reddit_comments 單元測試 |
| Create | `tests/agents/test_enrich_step.py` | _phase_enrich / _run_enrich 整合測試 |
| Modify | `agents/daily_brief/prompts.py` | 新增 `build_comment_summary_prompt`；更新 `build_digest_prompt_from_compress` |
| Modify | `agents/daily_brief/agent.py` | 新增 `_phase_enrich`、`_run_enrich`；更新 `ALL_STEPS`、`run()` |
| Modify | `agents/daily_brief/config.py` | 新增 `enrich` 至 `STEP_CONFIGS` |
| Modify | `AGENTS.md` | 更新步驟列表 |
| Modify | `CLAUDE.md` | 更新步驟列表 |

---

## Task 1：`hn_comments.py` tool（TDD）

**Files:**
- Create: `tests/tools/fetchers/test_hn_comments.py`
- Create: `tools/fetchers/hn_comments.py`

---

- [ ] **Step 1.1：撰寫失敗測試**

建立 `tests/tools/fetchers/test_hn_comments.py`：

```python
"""HN comments fetcher 測試。"""

import json
from unittest.mock import patch, MagicMock


HN_URL = "https://news.ycombinator.com/item?id=48296794"

# ── fetch_comments(item_id) ──────────────────────────────────────

def test_fetch_comments_returns_list_of_strings():
    from tools.fetchers.hn_comments import fetch_comments
    fake_api = json.dumps({
        "id": 48296794,
        "children": [
            {"id": 1, "text": "Great article!", "children": []},
            {"id": 2, "text": "I disagree.", "children": []},
        ]
    })
    with patch("tools.fetchers.hn_comments._curl_get", return_value=fake_api):
        result = fetch_comments("48296794")
    assert isinstance(result, list)
    assert result == ["Great article!", "I disagree."]


def test_fetch_comments_strips_html_tags():
    from tools.fetchers.hn_comments import fetch_comments
    fake_api = json.dumps({
        "children": [
            {"id": 1, "text": "<p>Hello <b>world</b></p>", "children": []},
        ]
    })
    with patch("tools.fetchers.hn_comments._curl_get", return_value=fake_api):
        result = fetch_comments("123")
    assert result == ["Hello world"]


def test_fetch_comments_truncates_at_300_chars():
    from tools.fetchers.hn_comments import fetch_comments
    long_text = "x" * 500
    fake_api = json.dumps({"children": [{"id": 1, "text": long_text, "children": []}]})
    with patch("tools.fetchers.hn_comments._curl_get", return_value=fake_api):
        result = fetch_comments("123")
    assert len(result[0]) == 300


def test_fetch_comments_respects_top_n():
    from tools.fetchers.hn_comments import fetch_comments
    children = [{"id": i, "text": f"comment {i}", "children": []} for i in range(15)]
    fake_api = json.dumps({"children": children})
    with patch("tools.fetchers.hn_comments._curl_get", return_value=fake_api):
        result = fetch_comments("123", top_n=5)
    assert len(result) == 5


def test_fetch_comments_skips_none_text():
    from tools.fetchers.hn_comments import fetch_comments
    fake_api = json.dumps({
        "children": [
            {"id": 1, "text": None, "children": []},
            {"id": 2, "text": "valid", "children": []},
        ]
    })
    with patch("tools.fetchers.hn_comments._curl_get", return_value=fake_api):
        result = fetch_comments("123")
    assert result == ["valid"]


def test_fetch_comments_returns_empty_on_network_error():
    from tools.fetchers.hn_comments import fetch_comments
    with patch("tools.fetchers.hn_comments._curl_get", side_effect=RuntimeError("timeout")):
        result = fetch_comments("123")
    assert result == []


def test_fetch_comments_returns_empty_on_invalid_json():
    from tools.fetchers.hn_comments import fetch_comments
    with patch("tools.fetchers.hn_comments._curl_get", return_value="not json"):
        result = fetch_comments("123")
    assert result == []


# ── parse_item_id(url) ───────────────────────────────────────────

def test_parse_item_id_valid():
    from tools.fetchers.hn_comments import parse_item_id
    assert parse_item_id("https://news.ycombinator.com/item?id=48296794") == "48296794"


def test_parse_item_id_invalid_returns_none():
    from tools.fetchers.hn_comments import parse_item_id
    assert parse_item_id("https://news.ycombinator.com/") is None
    assert parse_item_id("https://example.com") is None
```

- [ ] **Step 1.2：確認測試失敗**

```bash
cd $HOME/Workspace/agent && python -m pytest tests/tools/fetchers/test_hn_comments.py -v 2>&1 | head -20
```

預期：`ModuleNotFoundError` 或 `ImportError`

- [ ] **Step 1.3：實作 `tools/fetchers/hn_comments.py`**

```python
"""HN 留言抓取 — 使用 HN Algolia API。"""

from __future__ import annotations

import json
import re
import subprocess


def parse_item_id(hn_url: str) -> str | None:
    """從 HN 討論頁 URL 提取 item id。"""
    m = re.search(r"item\?id=(\d+)", hn_url)
    return m.group(1) if m else None


def fetch_comments(item_id: str, top_n: int = 10) -> list[str]:
    """
    呼叫 HN Algolia API 取 top N 留言文字。
    失敗時回傳空列表（不 raise）。
    """
    try:
        raw = _curl_get(f"https://hn.algolia.com/api/v1/items/{item_id}")
        data = json.loads(raw)
        children = data.get("children") or []
        result: list[str] = []
        for child in children[:top_n]:
            text = child.get("text")
            if not text:
                continue
            clean = re.sub(r"<[^>]+>", "", text).strip()[:300]
            if clean:
                result.append(clean)
        return result
    except Exception:
        return []


def _curl_get(url: str, timeout: int = 15) -> str:
    proc = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout), url],
        capture_output=True, text=True, timeout=timeout + 5,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed: {proc.stderr[:100]}")
    return proc.stdout
```

- [ ] **Step 1.4：確認測試通過**

```bash
cd $HOME/Workspace/agent && python -m pytest tests/tools/fetchers/test_hn_comments.py -v
```

預期：全部 PASS

- [ ] **Step 1.5：Commit**

```bash
git add tools/fetchers/hn_comments.py tests/tools/fetchers/test_hn_comments.py
git commit -m "feat: add hn_comments fetcher with Algolia API"
```

---

## Task 2：`reddit_comments.py` tool（TDD）

**Files:**
- Create: `tests/tools/fetchers/test_reddit_comments.py`
- Create: `tools/fetchers/reddit_comments.py`

---

- [ ] **Step 2.1：撰寫失敗測試**

建立 `tests/tools/fetchers/test_reddit_comments.py`：

```python
"""Reddit comments fetcher 測試。"""

import json
from unittest.mock import patch


REDDIT_POST_URL = "https://www.reddit.com/r/netsec/comments/abc123/some_title"


def _make_reddit_response(comments: list[str]) -> str:
    children = [
        {"kind": "t1", "data": {"body": c, "score": 100 - i}}
        for i, c in enumerate(comments)
    ]
    return json.dumps([
        {"data": {}},
        {"data": {"children": children}},
    ])


def test_fetch_comments_returns_list_of_strings():
    from tools.fetchers.reddit_comments import fetch_comments
    fake = _make_reddit_response(["comment A", "comment B"])
    with patch("tools.fetchers.reddit_comments._curl_get", return_value=fake):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == ["comment A", "comment B"]


def test_fetch_comments_truncates_at_300_chars():
    from tools.fetchers.reddit_comments import fetch_comments
    long_body = "y" * 500
    fake = _make_reddit_response([long_body])
    with patch("tools.fetchers.reddit_comments._curl_get", return_value=fake):
        result = fetch_comments(REDDIT_POST_URL)
    assert len(result[0]) == 300


def test_fetch_comments_respects_top_n():
    from tools.fetchers.reddit_comments import fetch_comments
    comments = [f"comment {i}" for i in range(15)]
    fake = _make_reddit_response(comments)
    with patch("tools.fetchers.reddit_comments._curl_get", return_value=fake):
        result = fetch_comments(REDDIT_POST_URL, top_n=5)
    assert len(result) == 5


def test_fetch_comments_filters_deleted():
    from tools.fetchers.reddit_comments import fetch_comments
    fake = _make_reddit_response(["[deleted]", "[removed]", "valid comment"])
    with patch("tools.fetchers.reddit_comments._curl_get", return_value=fake):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == ["valid comment"]


def test_fetch_comments_returns_empty_on_network_error():
    from tools.fetchers.reddit_comments import fetch_comments
    with patch("tools.fetchers.reddit_comments._curl_get", side_effect=RuntimeError("403")):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == []


def test_fetch_comments_returns_empty_on_invalid_json():
    from tools.fetchers.reddit_comments import fetch_comments
    with patch("tools.fetchers.reddit_comments._curl_get", return_value="bad json"):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == []


def test_fetch_comments_url_gets_json_suffix():
    """_curl_get 被呼叫時，URL 必須以 .json 開頭（含 query string）。"""
    from tools.fetchers.reddit_comments import fetch_comments
    called_urls: list[str] = []

    def _capture_url(url: str) -> str:
        called_urls.append(url)
        raise RuntimeError("stop")

    with patch("tools.fetchers.reddit_comments._curl_get", side_effect=_capture_url):
        fetch_comments(REDDIT_POST_URL)

    assert called_urls[0].endswith(".json?limit=10&sort=best")
```

- [ ] **Step 2.2：確認測試失敗**

```bash
cd $HOME/Workspace/agent && python -m pytest tests/tools/fetchers/test_reddit_comments.py -v 2>&1 | head -20
```

預期：`ModuleNotFoundError` 或 `ImportError`

- [ ] **Step 2.3：實作 `tools/fetchers/reddit_comments.py`**

```python
"""Reddit 留言抓取 — 使用 Reddit JSON API（Bash curl）。"""

from __future__ import annotations

import json
import subprocess


_DELETED = frozenset({"[deleted]", "[removed]"})
_HEADERS = ["User-Agent: daily-brief/1.0"]


def fetch_comments(post_url: str, top_n: int = 10) -> list[str]:
    """
    呼叫 Reddit JSON API 取 top N 留言文字。
    失敗時回傳空列表（不 raise）。
    """
    try:
        # 移除尾部斜線，補上 .json query string
        url = post_url.rstrip("/") + ".json?limit=10&sort=best"
        raw = _curl_get(url)
        data = json.loads(raw)
        children = data[1]["data"]["children"]
        result: list[str] = []
        for child in children[:top_n]:
            body = child.get("data", {}).get("body", "")
            if body in _DELETED or not body:
                continue
            result.append(body[:300])
        return result
    except Exception:
        return []


def _curl_get(url: str, timeout: int = 15) -> str:
    header_flags: list[str] = []
    for h in _HEADERS:
        header_flags += ["-H", h]
    proc = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout)] + header_flags + [url],
        capture_output=True, text=True, timeout=timeout + 5,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed: {proc.stderr[:100]}")
    return proc.stdout
```

- [ ] **Step 2.4：確認測試通過**

```bash
cd $HOME/Workspace/agent && python -m pytest tests/tools/fetchers/test_reddit_comments.py -v
```

預期：全部 PASS

- [ ] **Step 2.5：Commit**

```bash
git add tools/fetchers/reddit_comments.py tests/tools/fetchers/test_reddit_comments.py
git commit -m "feat: add reddit_comments fetcher with JSON API"
```

---

## Task 3：Prompts 新增與更新（TDD）

**Files:**
- Modify: `agents/daily_brief/prompts.py`（新增 `build_comment_summary_prompt`；更新 `build_digest_prompt_from_compress`）
- Modify: `tests/test_daily_brief_prompts.py`（新增測試）

---

- [ ] **Step 3.1：在 `tests/test_daily_brief_prompts.py` 末尾新增失敗測試**

在檔案末尾（`test_fetch_prompts_contain_few_shot_examples` 函式之後）追加：

```python

# ── build_comment_summary_prompt ────────────────────────────────

def test_build_comment_summary_prompt_exists():
    assert hasattr(prompts, "build_comment_summary_prompt")


def test_build_comment_summary_prompt_output_key():
    p = prompts.build_comment_summary_prompt("hn", "Some Title", '["comment 1"]')
    assert '"comment_summary"' in p


def test_build_comment_summary_prompt_includes_title_and_source():
    p = prompts.build_comment_summary_prompt("reddit", "My Article", "[]")
    assert "My Article" in p
    assert "reddit" in p


def test_build_comment_summary_prompt_specifies_60_char_limit():
    p = prompts.build_comment_summary_prompt("hn", "T", "[]")
    assert "60" in p


# ── build_digest_prompt_from_compress（更新）───────────────────

def test_build_digest_prompt_from_compress_mentions_comment_summary():
    """更新後的 prompt 應提及 comment_summary 欄位與社群觀點追加。"""
    p = prompts.build_digest_prompt_from_compress("{}")
    assert "comment_summary" in p
    assert "社群觀點" in p
```

- [ ] **Step 3.2：確認新測試失敗**

```bash
cd $HOME/Workspace/agent && python -m pytest tests/test_daily_brief_prompts.py -v -k "comment_summary or social" 2>&1 | tail -15
```

預期：`AttributeError` 或 `AssertionError`

- [ ] **Step 3.3：在 `agents/daily_brief/prompts.py` 新增 `build_comment_summary_prompt`**

在 `build_telegram_overview_prompt` 函式之前（約第 496 行）插入：

```python
# ── Step enrich：留言社群觀點摘要 ───────────────────────────────

def build_comment_summary_prompt(source: str, title: str, comments_json: str) -> str:
    return f"""\
{_NO_THINK}## 文章資訊

來源：{source}
標題：{title}

## 社群留言（top 10）

{comments_json}

## 任務

根據以上留言，以 ≤ 60 字繁體中文摘要社群觀點（主流看法、爭議點、實用建議等）。

## 輸出格式

```json
{{"comment_summary": "≤60 字社群觀點摘要"}}
```\
"""
```

- [ ] **Step 3.4：更新 `build_digest_prompt_from_compress`**

將現有的 `build_digest_prompt_from_compress` 函式（約第 330-359 行）替換為：

```python
def build_digest_prompt_from_compress(compress_json: str) -> str:
    return f"""\
## 壓縮後文章（compress.json，每篇均已是 ***，含 one_liner）

{compress_json}

## 任務

對**每一篇**文章生成 3–5 行繁體中文深度摘要：
- 核心訊息（這項技術/事件是什麼）
- 影響範圍（誰受影響、規模）
- 值得關注的原因（為何現在重要）
- 若文章有 comment_summary 欄位，在 summary 尾段另起一行追加：
  💬 社群觀點：[comment_summary 的內容]

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
      "summary": "3–5 行摘要（若有 comment_summary，尾段追加 💬 社群觀點：...）"
    }}
  ]
}}
```"""
```

- [ ] **Step 3.5：確認所有 prompt 測試通過**

```bash
cd $HOME/Workspace/agent && python -m pytest tests/test_daily_brief_prompts.py -v
```

預期：全部 PASS（包含原有測試）

- [ ] **Step 3.6：Commit**

```bash
git add agents/daily_brief/prompts.py tests/test_daily_brief_prompts.py
git commit -m "feat: add build_comment_summary_prompt and update digest prompt for comment_summary"
```

---

## Task 4：`_phase_enrich` + `_run_enrich` + config 更新（TDD）

**Files:**
- Create: `tests/agents/test_enrich_step.py`
- Modify: `agents/daily_brief/config.py`（新增 `enrich` 至 `STEP_CONFIGS`）
- Modify: `agents/daily_brief/agent.py`（新增 `_phase_enrich`、`_run_enrich`）

---

- [ ] **Step 4.1：撰寫失敗測試**

建立 `tests/agents/test_enrich_step.py`：

```python
"""_phase_enrich / _run_enrich 測試。"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


# ── Fixtures ────────────────────────────────────────────────────

def _make_agent(llm_response: str = '{"comment_summary": "社群觀點摘要文字"}'):
    from agents.daily_brief.agent import DailyBriefAgent
    mock_llm = MagicMock()
    mock_llm.complete.return_value = f"```json\n{llm_response}\n```"
    return DailyBriefAgent(llm=mock_llm)


_HN_COMPRESS = {
    "_meta": {"compressed_at": "2026-05-29T00:00:00"},
    "hn": {
        "themes": ["AI"],
        "articles": [
            {"title": "HN Article", "url": "https://news.ycombinator.com/item?id=123", "one_liner": "要點", "interest": "***"},
        ],
    },
    "reddit": {
        "themes": ["Security"],
        "articles": [
            {"title": "Reddit Article", "url": "https://www.reddit.com/r/netsec/comments/abc/title/", "one_liner": "要點", "interest": "***"},
        ],
    },
    "hatena": {"themes": [], "articles": []},
    "security": {"themes": [], "articles": []},
    "rss": {"themes": [], "articles": []},
}


# ── _run_enrich：正常路徑 ────────────────────────────────────────

def test_run_enrich_adds_comment_summary_to_hn():
    agent = _make_agent()
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1", "c2"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            result = agent._run_enrich(_HN_COMPRESS)
    hn_articles = result["hn"]["articles"]
    assert "comment_summary" in hn_articles[0]
    assert hn_articles[0]["comment_summary"] == "社群觀點摘要文字"


def test_run_enrich_adds_comment_summary_to_reddit():
    agent = _make_agent()
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            result = agent._run_enrich(_HN_COMPRESS)
    reddit_articles = result["reddit"]["articles"]
    assert "comment_summary" in reddit_articles[0]


def test_run_enrich_does_not_modify_non_hn_reddit_sources():
    agent = _make_agent()
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            result = agent._run_enrich(_HN_COMPRESS)
    # hatena / security / rss 不應有 comment_summary
    for src in ["hatena", "security", "rss"]:
        for article in result.get(src, {}).get("articles", []):
            assert "comment_summary" not in article


def test_run_enrich_preserves_original_fields():
    agent = _make_agent()
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            result = agent._run_enrich(_HN_COMPRESS)
    hn_article = result["hn"]["articles"][0]
    assert hn_article["title"] == "HN Article"
    assert hn_article["url"] == "https://news.ycombinator.com/item?id=123"
    assert hn_article["one_liner"] == "要點"


# ── _run_enrich：部分失敗（best-effort）─────────────────────────

def test_run_enrich_skips_article_when_fetch_returns_empty():
    agent = _make_agent()
    # hn fetch 回傳空列表（如網路失敗）
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=[]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            result = agent._run_enrich(_HN_COMPRESS)
    # HN 文章無 comment_summary（因為沒有留言可摘要）
    assert "comment_summary" not in result["hn"]["articles"][0]
    # Reddit 仍有 comment_summary
    assert "comment_summary" in result["reddit"]["articles"][0]


def test_run_enrich_skips_article_when_llm_returns_invalid_json():
    agent = _make_agent(llm_response="invalid json {{{")
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            result = agent._run_enrich(_HN_COMPRESS)
    # LLM 失敗時，文章無 comment_summary，但不崩潰
    assert isinstance(result, dict)
    assert "hn" in result


def test_run_enrich_does_not_mutate_compress_data():
    """_run_enrich 不應修改傳入的 compress_data（回傳新 dict）。"""
    import copy
    agent = _make_agent()
    original = copy.deepcopy(_HN_COMPRESS)
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            agent._run_enrich(_HN_COMPRESS)
    assert _HN_COMPRESS == original


# ── _phase_enrich：idempotent ────────────────────────────────────

def test_phase_enrich_loads_existing_artifact(tmp_path):
    from agents.daily_brief.agent import DailyBriefAgent, _RunContext
    agent = _make_agent()
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()

    saved = {"_meta": {}, "hn": {"articles": [{"comment_summary": "cached"}]}}
    (steps_dir / "enrich.json").write_text(json.dumps(saved), encoding="utf-8")

    ctx = MagicMock()
    ctx.steps_to_run = {"enrich"}
    ctx.force_steps = set()
    ctx.steps_dir = steps_dir

    result = agent._phase_enrich(ctx, _HN_COMPRESS)
    assert result["hn"]["articles"][0]["comment_summary"] == "cached"


def test_phase_enrich_skips_when_not_in_steps_to_run(tmp_path):
    from agents.daily_brief.agent import DailyBriefAgent
    agent = _make_agent()
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()

    ctx = MagicMock()
    ctx.steps_to_run = {"digest"}  # enrich 不在其中
    ctx.force_steps = set()
    ctx.steps_dir = steps_dir

    result = agent._phase_enrich(ctx, _HN_COMPRESS)
    # 無 artifact → 直接回傳 compress_data
    assert result is _HN_COMPRESS


def test_phase_enrich_writes_artifact(tmp_path):
    from agents.daily_brief.agent import DailyBriefAgent
    agent = _make_agent()
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()

    ctx = MagicMock()
    ctx.steps_to_run = {"enrich"}
    ctx.force_steps = set()
    ctx.steps_dir = steps_dir

    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            agent._phase_enrich(ctx, _HN_COMPRESS)

    assert (steps_dir / "enrich.json").exists()
    saved = json.loads((steps_dir / "enrich.json").read_text())
    assert "_meta" in saved
    assert "enriched_at" in saved["_meta"]
```

- [ ] **Step 4.2：確認測試失敗**

```bash
cd $HOME/Workspace/agent && python -m pytest tests/agents/test_enrich_step.py -v 2>&1 | head -20
```

預期：`ImportError` 或 `AttributeError`（`_run_enrich` 尚不存在）

- [ ] **Step 4.3：在 `agents/daily_brief/config.py` 新增 `enrich` StepConfig**

在 `STEP_CONFIGS` dict（約第 66 行）的 `"compress"` 條目之前插入：

```python
    "enrich": StepConfig(
        max_retries=1,
        strategy="plain",
        task_description="對 HN/Reddit *** 文章抓取 top 10 留言並 LLM 摘要社群觀點（best-effort）",
    ),
```

- [ ] **Step 4.4：在 `agents/daily_brief/agent.py` 新增 `_run_enrich` 與 `_phase_enrich`**

在 `_run_compress` 方法（約第 556 行）之前插入以下兩個方法：

```python
    def _phase_enrich(self, ctx: _RunContext, compress_data: dict) -> dict:
        """compress 後、digest 前：對 HN/Reddit *** 文章並行抓留言 → LLM 摘要。"""
        enrich_artifact = ctx.steps_dir / "enrich.json"
        if "enrich" not in ctx.steps_to_run:
            if enrich_artifact.exists():
                return json.loads(enrich_artifact.read_text(encoding="utf-8"))
            return compress_data
        if enrich_artifact.exists() and "enrich" not in ctx.force_steps:
            logger.info("Step enrich    : 載入既有 artifact")
            return json.loads(enrich_artifact.read_text(encoding="utf-8"))
        if not compress_data:
            logger.warning("Step enrich    : 無壓縮資料，略過（先執行 compress step）")
            return compress_data

        logger.info("Step enrich    : 執行中...")
        enrich_data = self._run_enrich(compress_data)
        enrich_artifact.write_text(
            json.dumps(enrich_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        enriched_count = sum(
            1
            for src in ["hn", "reddit"]
            for a in enrich_data.get(src, {}).get("articles", [])
            if isinstance(a, dict) and "comment_summary" in a
        )
        logger.info("Step enrich    : 完成 → enrich.json（%d 篇含留言摘要）", enriched_count)
        return enrich_data

    def _run_enrich(self, compress_data: dict) -> dict:
        """對 compress_data 中 HN/Reddit *** 文章並行抓留言並 LLM 摘要。"""
        import copy
        import re as _re
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from tools.fetchers import hn_comments, reddit_comments

        result = copy.deepcopy(compress_data)
        result["_meta"] = {"enriched_at": datetime.now().isoformat(timespec="seconds")}

        # 收集待 enrich 的 (source, article_index) 清單
        to_enrich: list[tuple[str, int]] = []
        for src in ["hn", "reddit"]:
            for idx, article in enumerate(result.get(src, {}).get("articles", [])):
                if isinstance(article, dict):
                    to_enrich.append((src, idx))

        def _enrich_one(src: str, idx: int) -> tuple[str, int, str | None]:
            try:
                article = result[src]["articles"][idx]
                url = article.get("url", "")
                if src == "hn":
                    item_id = hn_comments.parse_item_id(url)
                    if not item_id:
                        logger.debug("HN URL 無法解析 item_id: %s", url)
                        return src, idx, None
                    comments = hn_comments.fetch_comments(item_id, top_n=10)
                else:
                    comments = reddit_comments.fetch_comments(url, top_n=10)

                if not comments:
                    return src, idx, None

                prompt = prompts.build_comment_summary_prompt(
                    source=src,
                    title=article.get("title", ""),
                    comments_json=json.dumps(comments, ensure_ascii=False),
                )
                raw = self._complete(prompt)
                parsed = parse_llm_json(raw)
                summary = parsed.get("comment_summary", "").strip()
                return src, idx, summary if summary else None
            except Exception as exc:
                logger.warning("enrich %s[%d] 失敗: %s", src, idx, exc)
                return src, idx, None

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(_enrich_one, src, idx): (src, idx)
                for src, idx in to_enrich
            }
            for future in as_completed(futures):
                src, idx, comment_summary = future.result()
                if comment_summary:
                    result[src]["articles"][idx]["comment_summary"] = comment_summary

        return result

```

- [ ] **Step 4.5：確認所有 enrich 測試通過**

```bash
cd $HOME/Workspace/agent && python -m pytest tests/agents/test_enrich_step.py -v
```

預期：全部 PASS

- [ ] **Step 4.6：Commit**

```bash
git add agents/daily_brief/agent.py agents/daily_brief/config.py tests/agents/test_enrich_step.py
git commit -m "feat: add _phase_enrich and _run_enrich to DailyBriefAgent"
```

---

## Task 5：Pipeline 接線 + 文件更新

**Files:**
- Modify: `agents/daily_brief/agent.py`（更新 `ALL_STEPS`、`run()` 呼叫鏈）
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

---

- [ ] **Step 5.1：更新 `ALL_STEPS`（`agent.py` 第 44 行附近）**

將：
```python
ALL_STEPS = [*FETCH_STEPS, "dedup", "compress", "digest", "judge", "report", "save", "notify"]
```

改為：
```python
ALL_STEPS = [*FETCH_STEPS, "dedup", "compress", "enrich", "digest", "judge", "report", "save", "notify"]
```

- [ ] **Step 5.2：在 `run()` 呼叫鏈插入 `_phase_enrich`**

找到 `agent.py` 中的 `run()` 方法，將：
```python
        compress_data = self._phase_compress(ctx, source_data)
        digests = self._phase_digest(ctx, compress_data)
        compress_data, digests = self._phase_judge(ctx, compress_data, digests)
        self._phase_report(ctx, compress_data, digests)
```

改為：
```python
        compress_data = self._phase_compress(ctx, source_data)
        enrich_data = self._phase_enrich(ctx, compress_data)
        digests = self._phase_digest(ctx, enrich_data)
        enrich_data, digests = self._phase_judge(ctx, enrich_data, digests)
        self._phase_report(ctx, enrich_data, digests)
```

- [ ] **Step 5.3：確認原有測試仍全部通過**

```bash
cd $HOME/Workspace/agent && python -m pytest tests/ -v --ignore=tests/harness -x 2>&1 | tail -20
```

預期：全部 PASS（無回歸）

- [ ] **Step 5.4：更新 `AGENTS.md` 步驟列表**

找到 `AGENTS.md` 的 `## DailyBrief 步驟` 表格，在 `compress` 行之後插入：

```markdown
| enrich | 對 HN/Reddit *** 文章抓 top 10 留言 → LLM 社群觀點摘要（best-effort） | `steps/enrich.json` |
```

同時更新「執行順序」說明行：
```
執行順序：`hatena` → `hn` → `reddit` → `security` → `rss` → `compress` → `enrich` → `digest` → `judge` → `report` → `save` → `notify`
```

- [ ] **Step 5.5：更新 `CLAUDE.md` 步驟相關說明**

1. 在 `## 執行方式` 區塊的 `# 可用 step 名稱` 那行，補上 `enrich`：
   ```
   # 可用 step 名稱：hatena / hn / reddit / security / rss / dedup / compress / enrich / digest / judge / report / save / notify
   ```

2. 在 `**輸出目錄結構**` 的 `steps/` 列表，`compress.json` 之後插入：
   ```
   │   ├── enrich.json      # HN/Reddit 留言摘要（comment_summary 欄位）
   ```

- [ ] **Step 5.6：Commit**

```bash
git add agents/daily_brief/agent.py AGENTS.md CLAUDE.md
git commit -m "feat: wire enrich step into pipeline and update docs"
```

---

## 完成確認

執行以下指令確認整個測試套件通過：

```bash
cd $HOME/Workspace/agent && python -m pytest tests/ -v --ignore=tests/harness 2>&1 | tail -30
```

預期：全部 PASS，無 `ERROR` 或 `FAILED`。

執行 lint 驗證介面合規：

```bash
cd $HOME/Workspace/agent && python lint/check_agent_interface.py && python lint/check_fetcher_interface.py
```

預期：無錯誤訊息。
