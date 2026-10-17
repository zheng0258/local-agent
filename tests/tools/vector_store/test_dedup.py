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


def _cross_source_dup_data():
    # 2026-10-17 實例：同一 URL 同時出現在 hatena 與 reddit
    return {
        "hatena": {
            "articles": [
                {"title": "pwnescape", "url": "https://pwn.ai/blog/pwnescape", "interest": "***"},
                {"title": "文章 A", "url": "https://example.com/a", "interest": "***"},
            ]
        },
        "reddit": {
            "articles": [
                {"title": "pwnescape (reddit)", "url": "https://pwn.ai/blog/pwnescape", "interest": "***"},
                {"title": "文章 B", "url": "https://example.com/b", "interest": "***"},
            ]
        },
    }


def _all_urls(filtered_data: dict) -> list[str]:
    from tools.vector_store.dedup import _flatten_articles

    return [
        a["url"]
        for content in filtered_data.values()
        for a in _flatten_articles(content.get("articles", []))
    ]


@pytest.mark.unit
def test_cross_source_duplicate_url_kept_only_once_in_first_source():
    from tools.vector_store.dedup import dedup_source_data

    col = _make_collection(url_exists=False, query_distance=0.90)
    filtered_data, result = dedup_source_data(
        source_data=_cross_source_dup_data(),
        collection=col,
        embedder=_make_embedder(),
        today="2026-10-17",
    )
    urls = _all_urls(filtered_data)
    assert urls.count("https://pwn.ai/blog/pwnescape") == 1
    assert filtered_data["hatena"]["articles"][0]["url"] == "https://pwn.ai/blog/pwnescape"
    assert [a["url"] for a in filtered_data["reddit"]["articles"]] == ["https://example.com/b"]
    # 計數與資料一致
    assert result.filtered_url == 1
    assert len(urls) == result.kept == len(result.kept_urls)


@pytest.mark.unit
def test_duplicate_url_across_categories_kept_only_once():
    from tools.vector_store.dedup import dedup_source_data

    source_data = {
        "rss": {
            "articles": {
                "AI": [{"title": "X", "url": "https://example.com/x"}],
                "Security": [
                    {"title": "X again", "url": "https://example.com/x"},
                    {"title": "Y", "url": "https://example.com/y"},
                ],
            }
        }
    }
    col = _make_collection(url_exists=False, query_distance=0.90)
    filtered_data, result = dedup_source_data(
        source_data=source_data,
        collection=col,
        embedder=_make_embedder(),
        today="2026-10-17",
    )
    assert filtered_data["rss"]["articles"]["AI"] == [{"title": "X", "url": "https://example.com/x"}]
    assert [a["url"] for a in filtered_data["rss"]["articles"]["Security"]] == ["https://example.com/y"]
    assert len(_all_urls(filtered_data)) == result.kept


@pytest.mark.unit
def test_dedup_does_not_mutate_input():
    import copy

    from tools.vector_store.dedup import dedup_source_data

    source_data = _cross_source_dup_data()
    snapshot = copy.deepcopy(source_data)
    dedup_source_data(
        source_data=source_data,
        collection=_make_collection(url_exists=False, query_distance=0.90),
        embedder=_make_embedder(),
        today="2026-10-17",
    )
    assert source_data == snapshot


@pytest.mark.unit
def test_load_path_matches_run_path_for_cross_source_duplicates():
    """DedupStep._load 以 kept_urls 重濾上游，結果須與 RUN 路徑逐字一致。"""
    from agents.daily_brief.reconcile import filter_source_data_by_urls
    from tools.vector_store.dedup import dedup_source_data

    source_data = _cross_source_dup_data()
    run_data, result = dedup_source_data(
        source_data=source_data,
        collection=_make_collection(url_exists=False, query_distance=0.90),
        embedder=_make_embedder(),
        today="2026-10-17",
    )
    load_data = filter_source_data_by_urls(source_data, set(result.kept_urls))
    assert load_data == run_data
