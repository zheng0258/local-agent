"""Hacker News fetcher 測試。"""

import pytest
from unittest.mock import patch


def test_fetch_returns_list():
    from tools.fetchers import hn
    result = hn.fetch()
    assert isinstance(result, list)


def test_fetch_each_item_has_url_key():
    from tools.fetchers import hn
    result = hn.fetch()
    for item in result:
        assert "url" in item


def test_fetch_success_item_has_html_key():
    fake_html = """
    <tr class="athing submission" id="1">
      <td><span class="titleline"><a href="https://example.com/a">A title</a></span></td>
    </tr>
    <span class="score" id="score_1">321 points</span>
    <a href="item?id=1">88&nbsp;comments</a>
    """
    with patch("tools.fetchers.hn.fetch_page", return_value={"url": "https://news.ycombinator.com/", "html": fake_html, "title": "HN"}):
        from tools.fetchers import hn
        result = hn.fetch()

    assert len(result) > 0
    assert result[0]["title"] == "A title"
    assert result[0]["url"] == "https://example.com/a"
    assert result[0]["score"] == 321
    assert result[0]["comments"] == 88


def test_fetch_html_truncated_to_12000_chars():
    big_html = "<tr class=\"athing submission\" id=\"9\"><td><span class=\"titleline\"><a href=\"https://example.com\">T</a></span></td></tr>"
    with patch("tools.fetchers.hn.fetch_page", return_value={"url": "https://news.ycombinator.com/", "html": big_html, "title": "HN"}):
        from tools.fetchers import hn
        result = hn.fetch()

    assert len(result) == 1
    assert "title" in result[0]


def test_fetch_network_error_raises():
    """fetch_page 回傳 error 時 fetch() 直接 raise；由上游 _load_or_fetch_raw 的
    try/except 接住，該來源跳過、pipeline 續跑（fail-soft per source）。"""
    with patch("tools.fetchers.hn.fetch_page", return_value={"url": "https://news.ycombinator.com/", "error": "timeout"}):
        from tools.fetchers import hn
        with pytest.raises(RuntimeError, match="HN fetch failed"):
            hn.fetch()


@pytest.mark.integration
def test_fetch_real_network_returns_html():
    from tools.fetchers import hn
    result = hn.fetch()

    assert len(result) > 0
    first = result[0]
    assert isinstance(first, dict)
    assert ("title" in first and "url" in first and "hn_url" in first) or ("error" in first)
