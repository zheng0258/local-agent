"""Security blogs fetcher 測試。

Unit tests：以 fixture feed XML 餵 mocked urlopen，不打真網路。
Integration tests：實際發送請求，標記 @pytest.mark.integration。
"""

import pytest
from unittest.mock import MagicMock, patch


# ── Fixtures ─────────────────────────────────────────────────────────────────

# aikido.dev 風格：Webflow 產生的 RSS 2.0，description 為純文字
_AIKIDO_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
<channel>
<title>Aikido Security's Blog</title>
<link>https://www.aikido.dev</link>
<item>
<title>Top Burp Suite alternatives for web application security testing</title>
<link>https://www.aikido.dev/blog/burp-suite-alternatives</link>
<guid>https://www.aikido.dev/blog/burp-suite-alternatives</guid>
<description>Compare the top Burp Suite alternatives for DAST and AI pentesting.</description>
<pubDate>Tue, 07 Jul 2026 18:44:00 GMT</pubDate>
</item>
</channel>
</rss>"""


# wiz.io 風格：jpmonette/feed 產生的 RSS 2.0，title/description 為 CDATA
_WIZ_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>Wiz Blog | RSS feed</title>
<link>https://www.wiz.io</link>
<item>
<title><![CDATA[Build AI Security Agents with Wiz MCP]]></title>
<link>https://www.wiz.io/blog/introducing-wiz-mcp</link>
<guid isPermaLink="false">https://www.wiz.io/blog/introducing-wiz-mcp</guid>
<pubDate>Thu, 02 Jul 2026 11:00:00 GMT</pubDate>
<description><![CDATA[Power AI-driven security with trusted security context.]]></description>
<content:encoded><![CDATA[Power AI-driven security with trusted security context.]]></content:encoded>
<author>Snegha Ramnarayanan</author>
</item>
</channel>
</rss>"""


def _feed_with_items(count: int) -> bytes:
    items = "".join(
        f"<item><title>Article {i}</title>"
        f"<link>https://www.aikido.dev/blog/a{i}</link>"
        f"<description>d{i}</description></item>"
        for i in range(count)
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<rss version="2.0"><channel>{items}</channel></rss>'
    ).encode()


def _mock_urlopen_response(xml_bytes: bytes) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.read.return_value = xml_bytes
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ── Unit Tests ───────────────────────────────────────────────────────────────

def test_fetch_parses_rss_feed_items():
    """fetch() 以 RSS feed 解析文章，回傳 title/url/source/description。"""
    with patch(
        "urllib.request.urlopen",
        return_value=_mock_urlopen_response(_AIKIDO_FEED),
    ):
        from tools.fetchers import security_blogs
        result = security_blogs.fetch()

    aikido = [a for a in result if a.get("source") == "aikido.dev" and "error" not in a]
    assert len(aikido) == 1
    article = aikido[0]
    assert article["title"] == (
        "Top Burp Suite alternatives for web application security testing"
    )
    assert article["url"] == "https://www.aikido.dev/blog/burp-suite-alternatives"
    assert article["description"].startswith("Compare the top Burp Suite alternatives")


def test_fetch_combines_both_sources_and_unwraps_cdata():
    """兩來源依序抓取合併；wiz.io 的 CDATA title/description 正確解出純文字。"""
    with patch(
        "urllib.request.urlopen",
        side_effect=[
            _mock_urlopen_response(_AIKIDO_FEED),
            _mock_urlopen_response(_WIZ_FEED),
        ],
    ):
        from tools.fetchers import security_blogs
        result = security_blogs.fetch()

    sources = [a["source"] for a in result]
    assert sources == ["aikido.dev", "wiz.io"]
    wiz = result[1]
    assert wiz["title"] == "Build AI Security Agents with Wiz MCP"
    assert wiz["url"] == "https://www.wiz.io/blog/introducing-wiz-mcp"
    assert wiz["description"] == "Power AI-driven security with trusted security context."


def test_fetch_caps_articles_per_source():
    """單一來源最多取前 10 篇（wiz feed 有 600+ items，必須截斷）。"""
    with patch(
        "urllib.request.urlopen",
        side_effect=[
            _mock_urlopen_response(_feed_with_items(12)),
            _mock_urlopen_response(_feed_with_items(3)),
        ],
    ):
        from tools.fetchers import security_blogs
        result = security_blogs.fetch()

    aikido = [a for a in result if a["source"] == "aikido.dev"]
    wiz = [a for a in result if a["source"] == "wiz.io"]
    assert len(aikido) == 10
    assert [a["title"] for a in aikido] == [f"Article {i}" for i in range(10)]
    assert len(wiz) == 3


def test_fetch_network_error_returns_error_dict_per_source():
    """網路錯誤時每來源回傳含 source + error 的 dict，不拋例外。"""
    with patch(
        "urllib.request.urlopen", side_effect=Exception("connection refused")
    ):
        from tools.fetchers import security_blogs
        result = security_blogs.fetch()

    assert len(result) == 2
    assert {a["source"] for a in result} == {"aikido.dev", "wiz.io"}
    for item in result:
        assert "connection refused" in item["error"]


def test_fetch_one_source_fails_other_still_returned():
    """單一來源失敗不影響另一來源的文章。"""
    with patch(
        "urllib.request.urlopen",
        side_effect=[
            Exception("HTTP 500"),
            _mock_urlopen_response(_WIZ_FEED),
        ],
    ):
        from tools.fetchers import security_blogs
        result = security_blogs.fetch()

    errors = [a for a in result if "error" in a]
    ok = [a for a in result if "error" not in a]
    assert len(errors) == 1 and errors[0]["source"] == "aikido.dev"
    assert len(ok) == 1 and ok[0]["source"] == "wiz.io"


def test_fetch_malformed_xml_returns_error_dict():
    """feed 內容非合法 XML 時回傳 error dict，不拋例外。"""
    with patch(
        "urllib.request.urlopen",
        return_value=_mock_urlopen_response(b"<html>not a feed</html"),
    ):
        from tools.fetchers import security_blogs
        result = security_blogs.fetch()

    assert len(result) == 2
    for item in result:
        assert "error" in item


def test_fetch_description_truncated_to_200_chars():
    """description 截斷至 200 字元（維持原 artifact schema 上限）。"""
    long_desc = "x" * 500
    feed = (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
        "<item><title>T</title><link>https://www.aikido.dev/blog/t</link>"
        f"<description>{long_desc}</description></item>"
        "</channel></rss>"
    ).encode()
    with patch(
        "urllib.request.urlopen", return_value=_mock_urlopen_response(feed)
    ):
        from tools.fetchers import security_blogs
        result = security_blogs.fetch()

    ok = [a for a in result if "error" not in a]
    assert all(len(a["description"]) == 200 for a in ok)


# ── Integration Tests ────────────────────────────────────────────────────────

@pytest.mark.integration
def test_fetch_real_network_returns_content():
    """實際抓取兩站 RSS feed，確認回傳格式正確。"""
    from tools.fetchers import security_blogs
    result = security_blogs.fetch()

    assert isinstance(result, list)
    assert len(result) > 0
    first = result[0]
    assert isinstance(first, dict)
    assert ("title" in first and "url" in first and "source" in first) or (
        "error" in first
    )
