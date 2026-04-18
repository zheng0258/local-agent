"""Security blogs fetcher 測試。"""

import pytest
from unittest.mock import patch


def test_fetch_returns_list():
    from tools.fetchers import security_blogs
    result = security_blogs.fetch()
    assert isinstance(result, list)


def test_fetch_success_contains_source_and_url():
    fake_articles = [{"title": "T", "url": "https://www.aikido.dev/blog/t", "source": "aikido.dev"}]
    with patch("tools.fetchers.security_blogs._fetch_articles", return_value=fake_articles):
        from tools.fetchers import security_blogs
        result = security_blogs.fetch()

    assert len(result) > 0
    assert "url" in result[0]
    assert "source" in result[0]


def test_fetch_combines_results_from_multiple_sources():
    with patch(
        "tools.fetchers.security_blogs._fetch_articles",
        side_effect=[
            [{"title": "A", "url": "https://www.aikido.dev/blog/a", "source": "aikido.dev"}],
            [{"title": "B", "url": "https://www.wiz.io/blog/b", "source": "wiz.io"}],
        ],
    ):
        from tools.fetchers import security_blogs
        result = security_blogs.fetch()

    assert len(result) == 2
    assert result[0]["source"] == "aikido.dev"
    assert result[1]["source"] == "wiz.io"


def test_fetch_network_error_includes_error_message():
    with patch(
        "tools.fetchers.security_blogs._fetch_articles",
        return_value=[{"source": "aikido.dev", "error": "connection refused"}],
    ):
        from tools.fetchers import security_blogs
        result = security_blogs.fetch()

    assert len(result) > 0
    assert "error" in result[0]


@pytest.mark.integration
def test_fetch_real_network_returns_content():
    from tools.fetchers import security_blogs
    result = security_blogs.fetch()

    assert isinstance(result, list)
    assert len(result) > 0
    assert isinstance(result[0], dict)
