from unittest.mock import MagicMock

import pytest


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

    # distance=0.10 -> similarity=0.90 > threshold 0.80 => filter
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

    # distance=0.90 -> similarity=0.10 < threshold 0.80 => keep
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
