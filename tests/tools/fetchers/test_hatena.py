"""
Hatena fetcher 測試。

Unit tests：mock HTTP，測邏輯與容錯。
Integration tests：實際發送請求，標記 @pytest.mark.integration。
"""

import pytest
from unittest.mock import patch, MagicMock


# ── Unit Tests ──────────────────────────────────────────────────────────────

def test_fetch_returns_list():
    """fetch() 必須回傳 list。"""
    from tools.fetchers import hatena
    result = hatena.fetch()
    assert isinstance(result, list)


def test_fetch_each_item_has_url_key():
    """每個項目必須有 url 欄位。"""
    from tools.fetchers import hatena
    result = hatena.fetch()
    for item in result:
        assert "url" in item


def test_fetch_success_returns_articles_list():
    """成功時回傳平坦文章列表。"""
    fake_rss = b"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:hatena="http://www.hatena.ne.jp/info/xmlns#">
  <item rdf:about="https://x.com">
    <title>A</title>
    <link>https://x.com</link>
    <hatena:bookmarkcount>123</hatena:bookmarkcount>
    <description>desc</description>
  </item>
</rdf:RDF>"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_rss
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        from tools.fetchers import hatena
        result = hatena.fetch()

    assert len(result) > 0
    assert "title" in result[0]
    assert "url" in result[0]
    assert "bookmarks" in result[0]


def _fake_rss(title: str = "Test Article", link: str = "https://example.com/1", bookmarks: int = 150) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:hatena="http://www.hatena.ne.jp/info/xmlns#">
  <item rdf:about="{link}">
    <title>{title}</title>
    <link>{link}</link>
    <hatena:bookmarkcount>{bookmarks}</hatena:bookmarkcount>
    <description>Test description</description>
  </item>
</rdf:RDF>""".encode()


def test_fetch_article_has_required_fields():
    """每篇文章必須有 title、url、bookmarks 欄位。"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = _fake_rss()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        from tools.fetchers import hatena
        result = hatena.fetch()

    assert len(result) > 0
    for article in result:
        if "error" in article:
            continue
        assert "title" in article
        assert "url" in article
        assert "bookmarks" in article


def test_fetch_network_error_returns_error_key():
    """網路錯誤時回傳含 error 欄位的 dict，不能拋出例外。"""
    with patch("urllib.request.urlopen", side_effect=Exception("network failure")):
        from tools.fetchers import hatena
        result = hatena.fetch()

    assert len(result) > 0
    for item in result:
        assert "error" in item
        assert "network failure" in item["error"]


def test_fetch_ssl_error_returns_error_key():
    """SSL 錯誤時回傳含 error 欄位的 dict，不能拋出例外。"""
    import ssl
    ssl_error = ssl.SSLError("CERTIFICATE_VERIFY_FAILED")

    with patch("urllib.request.urlopen", side_effect=ssl_error):
        from tools.fetchers import hatena
        result = hatena.fetch()

    assert len(result) > 0
    for item in result:
        assert "error" in item


# ── Integration Tests ────────────────────────────────────────────────────────

@pytest.mark.integration
def test_fetch_real_network_returns_articles():
    """實際抓取 Hatena RSS，確認回傳格式正確。"""
    from tools.fetchers import hatena
    result = hatena.fetch()

    assert len(result) > 0
    first = result[0]
    assert isinstance(first, dict)
    assert ("title" in first and "url" in first) or ("error" in first)
