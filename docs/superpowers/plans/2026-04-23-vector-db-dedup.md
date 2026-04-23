# Vector DB 去重實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 daily-brief pipeline 的 fetch → compress 之間插入 `dedup` 步驟，用 ChromaDB + Qwen3-Embedding 過濾 7 天內重複出現的文章（URL 精確比對 + 語意近似比對）。

**Architecture:** 新增 `tools/vector_store/` 模組（embedder / client / dedup），在 `agents/daily_brief/agent.py` 插入 `_phase_dedup()`，去重結果存為 `steps/dedup.json` artifact，包含 `kept_urls` 供後續重跑時重現相同過濾結果。

**Tech Stack:** ChromaDB（PersistentClient）、mlx_lm（Qwen3-Embedding-0.6B-4bit-DWQ，last-token hidden state）、pytest（unit，全部 mock）

---

## 檔案結構

| 動作 | 路徑 | 職責 |
|------|------|------|
| 新建 | `tools/vector_store/__init__.py` | 模組初始化 |
| 新建 | `tools/vector_store/embedder.py` | Qwen3Embedder：mlx_lm 推理，lazy 載入 |
| 新建 | `tools/vector_store/client.py` | ChromaDB PersistentClient + 7 天 TTL 清理 |
| 新建 | `tools/vector_store/dedup.py` | URL 去重 + 語意去重邏輯，回傳 DedupResult |
| 新建 | `tests/tools/__init__.py` | pytest 識別 |
| 新建 | `tests/tools/vector_store/__init__.py` | pytest 識別 |
| 新建 | `tests/tools/vector_store/test_embedder.py` | embedder 單元測試 |
| 新建 | `tests/tools/vector_store/test_client.py` | client 單元測試 |
| 新建 | `tests/tools/vector_store/test_dedup.py` | dedup 單元測試 |
| 修改 | `agents/daily_brief/config.py` | 加 DEDUP_* 常數 + "dedup" StepConfig |
| 修改 | `agents/daily_brief/agent.py` | ALL_STEPS 加 "dedup"、加 `_phase_dedup()`、加 helper |
| 修改 | `tests/test_daily_brief_agent.py` | 加 dedup 步驟順序測試 |
| 修改 | `requirements.txt` | 加 chromadb |
| 修改 | `.gitignore` | 加 `.vectordb/` |

---

## Task 1：依賴與 .gitignore

**Files:**
- Modify: `requirements.txt`
- Modify: `.gitignore`

- [ ] **Step 1：更新 requirements.txt**

將 `requirements.txt` 改為：

```
anthropic>=0.20.0
certifi
chromadb>=0.6.0
json-repair>=0.30.0
```

- [ ] **Step 2：更新 .gitignore**

在 `.gitignore` 末尾加入：

```
outputs/daily-brief/.vectordb/
```

- [ ] **Step 3：確認安裝**

```bash
pip install chromadb
```

預期：無 error，`python3 -c "import chromadb; print(chromadb.__version__)"` 印出版本。

- [ ] **Step 4：Commit**

```bash
git add requirements.txt .gitignore
git commit -m "chore: add chromadb dependency and gitignore .vectordb"
```

---

## Task 2：Embedder

**Files:**
- Create: `tools/vector_store/__init__.py`
- Create: `tools/vector_store/embedder.py`
- Create: `tests/tools/__init__.py`
- Create: `tests/tools/vector_store/__init__.py`
- Create: `tests/tools/vector_store/test_embedder.py`

- [ ] **Step 1：建立目錄與空 init 檔案**

建立以下空檔案：

```bash
touch tools/vector_store/__init__.py
touch tests/tools/__init__.py
touch tests/tools/vector_store/__init__.py
```

- [ ] **Step 2：寫失敗的測試**

建立 `tests/tools/vector_store/test_embedder.py`：

```python
import math
import pytest
from unittest.mock import MagicMock, patch
import mlx.core as mx


def _make_mock_mlx(hidden_dim: int = 1024, seq_len: int = 3):
    mock_model = MagicMock()
    mock_tokenizer = MagicMock()
    mock_model.model.return_value = mx.zeros((1, seq_len, hidden_dim))
    mock_tokenizer.encode.return_value = list(range(seq_len))
    return mock_model, mock_tokenizer


@pytest.mark.unit
def test_embed_returns_vector_of_correct_dim():
    mock_model, mock_tokenizer = _make_mock_mlx()
    with patch("tools.vector_store.embedder.mlx_lm.load", return_value=(mock_model, mock_tokenizer)):
        from tools.vector_store.embedder import Qwen3Embedder
        embedder = Qwen3Embedder()
        result = embedder.embed(["Claude Code Max 付費限制"])
    assert len(result) == 1
    assert len(result[0]) == 1024


@pytest.mark.unit
def test_embed_multiple_texts_returns_multiple_vectors():
    mock_model, mock_tokenizer = _make_mock_mlx()
    with patch("tools.vector_store.embedder.mlx_lm.load", return_value=(mock_model, mock_tokenizer)):
        from tools.vector_store.embedder import Qwen3Embedder
        embedder = Qwen3Embedder()
        result = embedder.embed(["text 1", "text 2", "text 3"])
    assert len(result) == 3
    assert all(len(v) == 1024 for v in result)


@pytest.mark.unit
def test_model_loaded_only_once():
    mock_model, mock_tokenizer = _make_mock_mlx()
    with patch(
        "tools.vector_store.embedder.mlx_lm.load",
        return_value=(mock_model, mock_tokenizer),
    ) as mock_load:
        from tools.vector_store.embedder import Qwen3Embedder
        embedder = Qwen3Embedder()
        embedder.embed(["first call"])
        embedder.embed(["second call"])
    mock_load.assert_called_once()


@pytest.mark.unit
def test_embed_returns_normalized_vector():
    mock_model, mock_tokenizer = _make_mock_mlx()
    mock_model.model.return_value = mx.ones((1, 3, 1024))
    with patch("tools.vector_store.embedder.mlx_lm.load", return_value=(mock_model, mock_tokenizer)):
        from tools.vector_store.embedder import Qwen3Embedder
        embedder = Qwen3Embedder()
        result = embedder.embed(["test"])
    norm = math.sqrt(sum(v * v for v in result[0]))
    assert abs(norm - 1.0) < 1e-4
```

- [ ] **Step 3：執行測試，確認失敗**

```bash
cd /Users/guangzhenglee/Workspace/agent
python3 -m pytest tests/tools/vector_store/test_embedder.py -v 2>&1 | tail -10
```

預期：`ImportError: No module named 'tools.vector_store.embedder'`

- [ ] **Step 4：實作 embedder.py**

建立 `tools/vector_store/embedder.py`：

```python
"""Qwen3Embedder — mlx_lm 本地推理，lazy 載入。"""

from __future__ import annotations

import mlx.core as mx
import mlx_lm


class Qwen3Embedder:
    MODEL_ID = "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ"

    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None

    def _ensure_loaded(self) -> None:
        if self._model is None:
            self._model, self._tokenizer = mlx_lm.load(self.MODEL_ID)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._ensure_loaded()
        results: list[list[float]] = []
        for text in texts:
            tokens = mx.array(self._tokenizer.encode(text)).reshape(1, -1)
            hidden = self._model.model(tokens)  # (1, seq_len, hidden_dim)
            vec = hidden[0, -1, :]              # last token hidden state
            norm = mx.sqrt((vec * vec).sum()) + 1e-8
            vec = vec / norm
            results.append(vec.tolist())        # .tolist() forces MLX lazy → eager
        return results
```

- [ ] **Step 5：執行測試，確認通過**

```bash
python3 -m pytest tests/tools/vector_store/test_embedder.py -v 2>&1 | tail -10
```

預期：`4 passed`

- [ ] **Step 6：Commit**

```bash
git add tools/vector_store/__init__.py tools/vector_store/embedder.py \
        tests/tools/__init__.py tests/tools/vector_store/__init__.py \
        tests/tools/vector_store/test_embedder.py
git commit -m "feat: add Qwen3Embedder using mlx_lm for daily-brief dedup"
```

---

## Task 3：ChromaDB Client

**Files:**
- Create: `tools/vector_store/client.py`
- Create: `tests/tools/vector_store/test_client.py`

- [ ] **Step 1：寫失敗的測試**

建立 `tests/tools/vector_store/test_client.py`：

```python
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import date, timedelta


@pytest.mark.unit
def test_get_collection_returns_collection():
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    with patch("tools.vector_store.client.chromadb.PersistentClient", return_value=mock_client):
        from tools.vector_store.client import get_collection
        result = get_collection(Path("/tmp/testdb"))

    mock_client.get_or_create_collection.assert_called_once_with(
        name="daily_brief_articles",
        metadata={"hnsw:space": "cosine"},
    )
    assert result is mock_collection


@pytest.mark.unit
def test_cleanup_deletes_records_older_than_window():
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": ["url1", "url2", "url3"]}

    from tools.vector_store.client import cleanup_old_records
    deleted = cleanup_old_records(mock_collection, window_days=7)

    assert deleted == 3
    mock_collection.delete.assert_called_once_with(ids=["url1", "url2", "url3"])


@pytest.mark.unit
def test_cleanup_no_old_records_skips_delete():
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": []}

    from tools.vector_store.client import cleanup_old_records
    deleted = cleanup_old_records(mock_collection, window_days=7)

    assert deleted == 0
    mock_collection.delete.assert_not_called()


@pytest.mark.unit
def test_cleanup_uses_correct_cutoff_date():
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": []}
    expected_cutoff = (date.today() - timedelta(days=7)).isoformat()

    from tools.vector_store.client import cleanup_old_records
    cleanup_old_records(mock_collection, window_days=7)

    call_kwargs = mock_collection.get.call_args
    assert call_kwargs[1]["where"] == {"date": {"$lt": expected_cutoff}}
```

- [ ] **Step 2：執行測試，確認失敗**

```bash
python3 -m pytest tests/tools/vector_store/test_client.py -v 2>&1 | tail -10
```

預期：`ImportError: No module named 'tools.vector_store.client'`

- [ ] **Step 3：實作 client.py**

建立 `tools/vector_store/client.py`：

```python
"""ChromaDB PersistentClient 管理 + TTL 清理。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import chromadb

COLLECTION_NAME = "daily_brief_articles"


def get_collection(db_path: Path) -> chromadb.Collection:
    client = chromadb.PersistentClient(path=str(db_path))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def cleanup_old_records(collection: chromadb.Collection, window_days: int) -> int:
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    results = collection.get(where={"date": {"$lt": cutoff}})
    if not results["ids"]:
        return 0
    collection.delete(ids=results["ids"])
    return len(results["ids"])
```

- [ ] **Step 4：執行測試，確認通過**

```bash
python3 -m pytest tests/tools/vector_store/test_client.py -v 2>&1 | tail -10
```

預期：`4 passed`

- [ ] **Step 5：Commit**

```bash
git add tools/vector_store/client.py tests/tools/vector_store/test_client.py
git commit -m "feat: add ChromaDB persistent client with TTL cleanup"
```

---

## Task 4：Dedup 邏輯

**Files:**
- Create: `tools/vector_store/dedup.py`
- Create: `tests/tools/vector_store/test_dedup.py`

- [ ] **Step 1：寫失敗的測試**

建立 `tests/tools/vector_store/test_dedup.py`：

```python
import pytest
from unittest.mock import MagicMock


def _make_embedder(dim: int = 1024):
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1] * dim]
    return embedder


def _make_collection(url_exists: bool = False, query_distance: float = 1.0):
    col = MagicMock()
    if url_exists:
        col.get.return_value = {
            "ids": ["https://example.com"],
            "metadatas": [{"date": "2026-04-20"}],
        }
    else:
        col.get.return_value = {"ids": [], "metadatas": []}
    col.query.return_value = {
        "distances": [[query_distance]],
        "metadatas": [[{"date": "2026-04-20"}]],
    }
    return col


def _source_data():
    return {
        "hatena": {
            "articles": [
                {"title": "文章 A", "url": "https://example.com/a", "interest": "***"},
                {"title": "文章 B", "url": "https://example.com/b", "interest": "***"},
            ]
        }
    }


@pytest.mark.unit
def test_url_seen_article_is_filtered():
    from tools.vector_store.dedup import dedup_source_data
    col = _make_collection(url_exists=True)
    _, result = dedup_source_data(
        source_data=_source_data(),
        collection=col,
        embedder=_make_embedder(),
        today="2026-04-23",
    )
    assert result.filtered_url == 2
    assert result.filtered_semantic == 0
    assert result.kept == 0


@pytest.mark.unit
def test_semantic_dup_article_is_filtered():
    from tools.vector_store.dedup import dedup_source_data
    # distance=0.10 → similarity=0.90 > threshold 0.80 → 過濾
    col = _make_collection(url_exists=False, query_distance=0.10)
    _, result = dedup_source_data(
        source_data=_source_data(),
        collection=col,
        embedder=_make_embedder(),
        today="2026-04-23",
    )
    assert result.filtered_semantic == 2
    assert result.filtered_url == 0
    assert result.kept == 0


@pytest.mark.unit
def test_new_article_passes_through():
    from tools.vector_store.dedup import dedup_source_data
    # distance=0.90 → similarity=0.10 < threshold 0.80 → 保留
    col = _make_collection(url_exists=False, query_distance=0.90)
    filtered_data, result = dedup_source_data(
        source_data=_source_data(),
        collection=col,
        embedder=_make_embedder(),
        today="2026-04-23",
    )
    assert result.kept == 2
    assert result.filtered_url == 0
    assert result.filtered_semantic == 0
    assert len(filtered_data["hatena"]["articles"]) == 2


@pytest.mark.unit
def test_partial_filter_preserves_new_article():
    from tools.vector_store.dedup import dedup_source_data
    col = MagicMock()
    # 第一篇 URL 命中，第二篇不命中且語意距離遠
    col.get.side_effect = [
        {"ids": ["https://example.com/a"], "metadatas": [{"date": "2026-04-20"}]},
        {"ids": [], "metadatas": []},
    ]
    col.query.return_value = {
        "distances": [[0.90]],
        "metadatas": [[{"date": "2026-04-20"}]],
    }
    filtered_data, result = dedup_source_data(
        source_data=_source_data(),
        collection=col,
        embedder=_make_embedder(),
        today="2026-04-23",
    )
    articles = filtered_data["hatena"]["articles"]
    assert len(articles) == 1
    assert articles[0]["url"] == "https://example.com/b"
    assert result.kept == 1
    assert result.filtered_url == 1


@pytest.mark.unit
def test_kept_urls_in_result():
    from tools.vector_store.dedup import dedup_source_data
    col = _make_collection(url_exists=False, query_distance=0.90)
    _, result = dedup_source_data(
        source_data=_source_data(),
        collection=col,
        embedder=_make_embedder(),
        today="2026-04-23",
    )
    assert "https://example.com/a" in result.kept_urls
    assert "https://example.com/b" in result.kept_urls


@pytest.mark.unit
def test_empty_collection_query_exception_keeps_article():
    from tools.vector_store.dedup import dedup_source_data
    col = MagicMock()
    col.get.return_value = {"ids": [], "metadatas": []}
    col.query.side_effect = Exception("collection is empty")
    _, result = dedup_source_data(
        source_data=_source_data(),
        collection=col,
        embedder=_make_embedder(),
        today="2026-04-23",
    )
    assert result.kept == 2
```

- [ ] **Step 2：執行測試，確認失敗**

```bash
python3 -m pytest tests/tools/vector_store/test_dedup.py -v 2>&1 | tail -10
```

預期：`ImportError: No module named 'tools.vector_store.dedup'`

- [ ] **Step 3：實作 dedup.py**

建立 `tools/vector_store/dedup.py`：

```python
"""URL 去重 + 語意去重。回傳過濾後的 source_data 與統計 DedupResult。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import chromadb

from .embedder import Qwen3Embedder


@dataclass
class DedupResult:
    total: int
    kept: int
    filtered_url: int
    filtered_semantic: int
    kept_urls: list[str]
    filtered_items: list[dict] = field(default_factory=list)


def dedup_source_data(
    source_data: dict,
    collection: chromadb.Collection,
    embedder: Qwen3Embedder,
    today: str,
    window_days: int = 7,
    threshold: float = 0.80,
) -> tuple[dict, DedupResult]:
    cutoff = (date.fromisoformat(today) - timedelta(days=window_days)).isoformat()

    kept_urls: list[str] = []
    filtered_items: list[dict] = []
    filtered_url = 0
    filtered_semantic = 0
    total = 0

    new_ids: list[str] = []
    new_docs: list[str] = []
    new_embeddings: list[list[float]] = []
    new_metas: list[dict] = []

    for source_name, source_content in source_data.items():
        articles = source_content.get("articles", [])
        for article in _flatten_articles(articles):
            url = article.get("url", "")
            title = article.get("title", "")
            if not url:
                continue
            total += 1

            existing = collection.get(ids=[url], where={"date": {"$gte": cutoff}})
            if existing["ids"]:
                filtered_url += 1
                filtered_items.append({
                    "url": url,
                    "title": title,
                    "reason": "url_seen",
                    "original_date": existing["metadatas"][0].get("date", ""),
                })
                continue

            embedding = embedder.embed([title])[0]
            try:
                query_result = collection.query(
                    query_embeddings=[embedding],
                    n_results=3,
                    where={"date": {"$gte": cutoff}},
                    include=["distances", "metadatas"],
                )
                distances = query_result.get("distances", [[]])[0]
                if distances and (1.0 - distances[0]) >= threshold:
                    nearest_meta = query_result["metadatas"][0][0]
                    filtered_semantic += 1
                    filtered_items.append({
                        "url": url,
                        "title": title,
                        "reason": "semantic_dup",
                        "original_date": nearest_meta.get("date", ""),
                    })
                    continue
            except Exception:
                pass  # collection 為空時 query 可能拋例外，直接保留

            kept_urls.append(url)
            new_ids.append(url)
            new_docs.append(title)
            new_embeddings.append(embedding)
            new_metas.append({
                "date": today,
                "source": source_name,
                "interest": article.get("interest", ""),
            })

    if new_ids:
        collection.upsert(
            ids=new_ids,
            documents=new_docs,
            embeddings=new_embeddings,
            metadatas=new_metas,
        )

    kept_set = set(kept_urls)
    return _filter_source_data_by_urls(source_data, kept_set), DedupResult(
        total=total,
        kept=len(kept_urls),
        filtered_url=filtered_url,
        filtered_semantic=filtered_semantic,
        kept_urls=kept_urls,
        filtered_items=filtered_items,
    )


def _flatten_articles(articles: list | dict) -> list[dict]:
    if isinstance(articles, list):
        return articles
    if isinstance(articles, dict):
        return [a for cat in articles.values() if isinstance(cat, list) for a in cat]
    return []


def _filter_source_data_by_urls(source_data: dict, kept_urls: set[str]) -> dict:
    filtered: dict = {}
    for source_name, content in source_data.items():
        articles = content.get("articles", [])
        if isinstance(articles, list):
            filtered[source_name] = {
                **content,
                "articles": [a for a in articles if a.get("url") in kept_urls],
            }
        elif isinstance(articles, dict):
            filtered[source_name] = {
                **content,
                "articles": {
                    cat: [a for a in cat_arts if a.get("url") in kept_urls]
                    for cat, cat_arts in articles.items()
                    if isinstance(cat_arts, list)
                },
            }
        else:
            filtered[source_name] = content
    return filtered
```

- [ ] **Step 4：執行測試，確認通過**

```bash
python3 -m pytest tests/tools/vector_store/test_dedup.py -v 2>&1 | tail -15
```

預期：`6 passed`

- [ ] **Step 5：Commit**

```bash
git add tools/vector_store/dedup.py tests/tools/vector_store/test_dedup.py
git commit -m "feat: add URL + semantic dedup logic with DedupResult"
```

---

## Task 5：Config 更新

**Files:**
- Modify: `agents/daily_brief/config.py`

- [ ] **Step 1：在 config.py 加入 dedup 常數**

在 `agents/daily_brief/config.py` 的 `INDEX_FILE = ...` 行之後加入：

```python
# ── Dedup 設定 ────────────────────────────────────────────────────

DEDUP_SIMILARITY_THRESHOLD = 0.80
DEDUP_WINDOW_DAYS = 7
VECTOR_DB_PATH = OUTPUT_DIR / ".vectordb"
```

- [ ] **Step 2：在 STEP_CONFIGS 加入 "dedup"**

在 `STEP_CONFIGS` dict 中，`"hatena": StepConfig(...)` 之前插入：

```python
    "dedup": StepConfig(
        max_retries=1,
        strategy="plain",
        task_description="向量去重：過濾 7 天內 URL 重複或語意相似（> 0.80）文章",
    ),
```

- [ ] **Step 3：確認 import 正常**

```bash
python3 -c "
from agents.daily_brief.config import (
    DEDUP_SIMILARITY_THRESHOLD, DEDUP_WINDOW_DAYS, VECTOR_DB_PATH, STEP_CONFIGS
)
print(DEDUP_SIMILARITY_THRESHOLD, DEDUP_WINDOW_DAYS, 'dedup' in STEP_CONFIGS)
"
```

預期：`0.8 7 True`

- [ ] **Step 4：Commit**

```bash
git add agents/daily_brief/config.py
git commit -m "feat: add dedup config constants to daily_brief config"
```

---

## Task 6：Agent 整合

**Files:**
- Modify: `agents/daily_brief/agent.py`
- Modify: `tests/test_daily_brief_agent.py`

- [ ] **Step 1：更新 ALL_STEPS**

在 `agents/daily_brief/agent.py` 第 38 行，將：

```python
ALL_STEPS = [*FETCH_STEPS, "compress", "digest", "judge", "report", "save", "notify"]
```

改為：

```python
ALL_STEPS = [*FETCH_STEPS, "dedup", "compress", "digest", "judge", "report", "save", "notify"]
```

- [ ] **Step 2：加入測試**

在 `tests/test_daily_brief_agent.py` 中，在 `test_all_steps_contains_compress_and_judge` 之後加入：

```python
def test_all_steps_contains_dedup():
    assert "dedup" in ALL_STEPS
```

並將現有的 `test_all_steps_order` 替換為：

```python
def test_all_steps_order():
    assert ALL_STEPS.index("security") < ALL_STEPS.index("dedup")
    assert ALL_STEPS.index("dedup") < ALL_STEPS.index("compress")
    assert ALL_STEPS.index("compress") < ALL_STEPS.index("digest")
    assert ALL_STEPS.index("digest") < ALL_STEPS.index("judge")
    assert ALL_STEPS.index("judge") < ALL_STEPS.index("report")
    assert ALL_STEPS.index("digest") < ALL_STEPS.index("report")
    assert ALL_STEPS.index("report") < ALL_STEPS.index("save")
    assert ALL_STEPS.index("save") < ALL_STEPS.index("notify")
```

- [ ] **Step 3：執行測試，確認通過**

```bash
python3 -m pytest tests/test_daily_brief_agent.py -v 2>&1 | tail -15
```

預期：全部 PASS。

- [ ] **Step 4：在 agent.py 末尾加入輔助函數**

在 `_format_obsidian_digest` 函數之前插入：

```python
def _filter_source_data_by_urls(source_data: dict, kept_urls: set[str]) -> dict:
    filtered: dict = {}
    for source_name, content in source_data.items():
        articles = content.get("articles", [])
        if isinstance(articles, list):
            filtered[source_name] = {
                **content,
                "articles": [a for a in articles if a.get("url") in kept_urls],
            }
        elif isinstance(articles, dict):
            filtered[source_name] = {
                **content,
                "articles": {
                    cat: [a for a in cat_arts if a.get("url") in kept_urls]
                    for cat, cat_arts in articles.items()
                    if isinstance(cat_arts, list)
                },
            }
        else:
            filtered[source_name] = content
    return filtered
```

- [ ] **Step 5：在 DailyBriefAgent 加入 `_phase_dedup` 方法**

在 `_phase_compress` 方法定義之前插入：

```python
def _phase_dedup(self, ctx: _RunContext, source_data: dict) -> dict:
    dedup_artifact = ctx.steps_dir / "dedup.json"
    if "dedup" not in ctx.steps_to_run:
        return source_data
    if dedup_artifact.exists() and "dedup" not in ctx.force_steps:
        logger.info("Step dedup     : 載入既有 artifact")
        artifact = json.loads(dedup_artifact.read_text(encoding="utf-8"))
        kept_urls = set(artifact.get("kept_urls", []))
        return _filter_source_data_by_urls(source_data, kept_urls)

    logger.info("Step dedup     : 執行中...")
    from agents.daily_brief.config import (
        DEDUP_SIMILARITY_THRESHOLD,
        DEDUP_WINDOW_DAYS,
        VECTOR_DB_PATH,
    )
    from tools.vector_store.client import cleanup_old_records, get_collection
    from tools.vector_store.dedup import dedup_source_data
    from tools.vector_store.embedder import Qwen3Embedder

    VECTOR_DB_PATH.mkdir(parents=True, exist_ok=True)
    collection = get_collection(VECTOR_DB_PATH)
    cleanup_old_records(collection, DEDUP_WINDOW_DAYS)
    embedder = Qwen3Embedder()

    filtered_data, result = dedup_source_data(
        source_data=source_data,
        collection=collection,
        embedder=embedder,
        today=ctx.today,
        window_days=DEDUP_WINDOW_DAYS,
        threshold=DEDUP_SIMILARITY_THRESHOLD,
    )

    artifact_data = {
        "total": result.total,
        "kept": result.kept,
        "filtered_url": result.filtered_url,
        "filtered_semantic": result.filtered_semantic,
        "kept_urls": result.kept_urls,
        "filtered_items": result.filtered_items,
    }
    dedup_artifact.write_text(
        json.dumps(artifact_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        "Step dedup     : 完成 → %d/%d 文章保留（url過濾:%d, 語意過濾:%d）",
        result.kept,
        result.total,
        result.filtered_url,
        result.filtered_semantic,
    )
    return filtered_data
```

- [ ] **Step 6：在 `run()` 插入 `_phase_dedup` 呼叫**

在 `run()` 方法中找到：

```python
        source_data = self._phase_fetch(ctx)
        if source_data is None:
            return "Pipeline 中止：fetch 成功不足（需 ≥ 2）"
        compress_data = self._phase_compress(ctx, source_data)
```

改為：

```python
        source_data = self._phase_fetch(ctx)
        if source_data is None:
            return "Pipeline 中止：fetch 成功不足（需 ≥ 2）"
        source_data = self._phase_dedup(ctx, source_data)
        compress_data = self._phase_compress(ctx, source_data)
```

- [ ] **Step 7：執行全套測試**

```bash
python3 -m pytest tests/test_daily_brief_agent.py tests/tools/vector_store/ -v 2>&1 | tail -20
```

預期：全部 PASS。

- [ ] **Step 8：Commit**

```bash
git add agents/daily_brief/agent.py tests/test_daily_brief_agent.py
git commit -m "feat: integrate dedup step into daily-brief pipeline"
```

---

## Task 7：端對端驗證

- [ ] **Step 1：執行 lint 驗證**

```bash
python3 lint/check_agent_interface.py
```

預期：無 error。

- [ ] **Step 2：確認 embedding 模型已載入**

```bash
lms status 2>&1 | grep embedding
```

若無回應，執行：

```bash
lms load qwen3-embedding-0.6b-dwq
```

- [ ] **Step 3：用 --only dedup 單步測試**

```bash
python3 main.py "/daily-brief --only dedup" 2>&1 | tail -20
```

預期輸出含：`Step dedup     : 完成 → X/Y 文章保留（url過濾:N, 語意過濾:M）`

- [ ] **Step 4：確認 dedup.json 結構**

```bash
python3 -c "
import json
from pathlib import Path
from datetime import date
p = Path(f'outputs/daily-brief/{date.today()}/steps/dedup.json')
d = json.loads(p.read_text())
print('total:', d['total'])
print('kept:', d['kept'])
print('filtered_url:', d['filtered_url'])
print('filtered_semantic:', d['filtered_semantic'])
print('kept_urls count:', len(d.get('kept_urls', [])))
"
```

- [ ] **Step 5：確認第二次執行使用 artifact cache**

```bash
python3 main.py "/daily-brief --only dedup" 2>&1 | grep "dedup"
```

預期：`Step dedup     : 載入既有 artifact`

- [ ] **Step 6：執行全套單元測試**

```bash
python3 -m pytest tests/ -m "not integration" -v 2>&1 | tail -20
```

預期：0 failed。

- [ ] **Step 7：Final commit**

```bash
git add .
git commit -m "feat: complete vector DB dedup integration for daily-brief pipeline"
```

---

## Spec 覆蓋確認

| Spec 要求 | 對應 Task |
|-----------|-----------|
| URL 精確比對（7 天內） | Task 4：dedup.py Step 1 比對邏輯 |
| 語意相似比對（threshold 0.80） | Task 4：dedup.py Step 2 query 邏輯 |
| ChromaDB persistent 純本地 | Task 3：client.py PersistentClient |
| Qwen3-Embedding 0.6B mlx_lm | Task 2：embedder.py last-token hidden state |
| dedup artifact 含 kept_urls | Task 6：_phase_dedup artifact_data |
| artifact cache 重跑可重現 | Task 6：Step 5 載入 artifact 分支 |
| 7 天 TTL 清理 | Task 3：cleanup_old_records |
| ALL_STEPS 加 "dedup" | Task 6：Step 1 |
| config 常數（閾值/天數/路徑） | Task 5 |
| .gitignore .vectordb/ | Task 1 |
