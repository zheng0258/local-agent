# tests/tw_stock/test_tw_news.py
from unittest.mock import MagicMock, patch

_SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>鉅亨網</title>
    <item>
      <title>台積電大漲</title>
      <link>https://news.cnyes.com/news/id/1</link>
      <pubDate>Thu, 08 May 2026 08:00:00 +0800</pubDate>
      <description>台積電今日大漲 5%</description>
    </item>
    <item>
      <title>舊新聞</title>
      <link>https://news.cnyes.com/news/id/0</link>
      <pubDate>Mon, 01 Jan 2020 00:00:00 +0000</pubDate>
      <description>很舊的新聞</description>
    </item>
  </channel>
</rss>"""


def _mock_ctx(xml: str):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.read.return_value = xml.encode("utf-8")
    return ctx


def test_fetch_returns_list():
    from tools.fetchers.tw_news import fetch
    with patch("urllib.request.urlopen", return_value=_mock_ctx(_SAMPLE_RSS)):
        result = fetch(feeds=[{"name": "t", "url": "http://x", "source": "鉅亨"}])
    assert isinstance(result, list)


def test_fetch_filters_old_articles():
    from tools.fetchers.tw_news import fetch
    with patch("urllib.request.urlopen", return_value=_mock_ctx(_SAMPLE_RSS)):
        result = fetch(
            feeds=[{"name": "t", "url": "http://x", "source": "鉅亨"}],
            max_age_hours=24,
        )
    titles = [a["title"] for a in result]
    assert "舊新聞" not in titles


def test_fetch_article_has_required_fields():
    from tools.fetchers.tw_news import fetch
    with patch("urllib.request.urlopen", return_value=_mock_ctx(_SAMPLE_RSS)):
        result = fetch(
            feeds=[{"name": "t", "url": "http://x", "source": "鉅亨"}],
            max_age_hours=24 * 365 * 10,
        )
    assert len(result) > 0
    a = result[0]
    for key in ("title", "url", "source", "published_at", "description"):
        assert key in a, f"Missing key: {key}"


def test_fetch_handles_network_error_gracefully():
    from tools.fetchers.tw_news import fetch
    with patch("urllib.request.urlopen", side_effect=Exception("net error")):
        result = fetch(feeds=[{"name": "t", "url": "http://x", "source": "鉅亨"}])
    assert result == []


def test_fetch_description_truncated_to_300():
    long_desc = "X" * 500
    rss = _SAMPLE_RSS.replace("台積電今日大漲 5%", long_desc)
    from tools.fetchers.tw_news import fetch
    with patch("urllib.request.urlopen", return_value=_mock_ctx(rss)):
        result = fetch(
            feeds=[{"name": "t", "url": "http://x", "source": "鉅亨"}],
            max_age_hours=24 * 365 * 10,
        )
    if result:
        assert len(result[0]["description"]) <= 300
