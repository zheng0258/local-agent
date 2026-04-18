"""
browser fetcher 測試。

Unit tests：mock Playwright，測邏輯與容錯。
Integration tests：實際啟動瀏覽器，標記 @pytest.mark.integration。
"""

import pytest
from unittest.mock import patch, MagicMock


# ── Unit Tests ───────────────────────────────────────────────────

def test_fetch_page_returns_dict():
    """fetch_page() 必須回傳 dict。"""
    from tools.fetchers.browser import fetch_page
    mock_page = MagicMock()
    mock_page.content.return_value = "<html><body>content</body></html>"
    mock_page.title.return_value = "Test Page"

    with patch("tools.fetchers.browser._fetch_with_playwright_cli", return_value={"url": "https://x.com", "html": "<html>content</html>", "title": "Test"}):
        result = fetch_page("https://x.com")

    assert isinstance(result, dict)


def test_fetch_page_has_required_keys():
    """回傳 dict 必須有 url、html、title 欄位。"""
    with patch("tools.fetchers.browser._fetch_with_playwright_cli", return_value={
        "url": "https://x.com",
        "html": "<html>content</html>",
        "title": "Test Page",
    }):
        from tools.fetchers.browser import fetch_page
        result = fetch_page("https://x.com")

    assert "url" in result
    assert "html" in result
    assert "title" in result


def test_fetch_page_html_truncated():
    """HTML 必須截斷至指定長度（預設 8000）。"""
    big_html = "x" * 20000
    with patch("tools.fetchers.browser._fetch_with_playwright_cli", return_value={
        "url": "https://x.com",
        "html": big_html,
        "title": "T",
    }):
        from tools.fetchers.browser import fetch_page
        result = fetch_page("https://x.com", max_chars=8000)

    assert len(result["html"]) <= 8000


def test_fetch_page_error_returns_error_key():
    """瀏覽器錯誤時回傳含 error 欄位的 dict，不能拋出例外。"""
    with patch("tools.fetchers.browser._fetch_with_playwright_cli", side_effect=Exception("browser crash")):
        from tools.fetchers.browser import fetch_page
        result = fetch_page("https://x.com")

    assert "error" in result
    assert "browser crash" in result["error"]


def test_fetch_pages_returns_list():
    """fetch_pages() 必須回傳 list，長度等於輸入 URL 數。"""
    urls = ["https://a.com", "https://b.com"]
    fake = {"url": "https://a.com", "html": "content", "title": "T"}
    with patch("tools.fetchers.browser.fetch_page", return_value=fake):
        from tools.fetchers.browser import fetch_pages
        result = fetch_pages(urls)

    assert isinstance(result, list)
    assert len(result) == len(urls)


# ── Integration Tests ─────────────────────────────────────────────

@pytest.mark.integration
def test_fetch_page_real_aikido():
    """實際抓取 aikido.dev/blog，確認拿到文章內容（JS 渲染）。"""
    from tools.fetchers.browser import fetch_page
    result = fetch_page("https://www.aikido.dev/blog")

    assert "error" not in result, f"抓取失敗：{result.get('error')}"
    assert len(result["html"]) > 500
    # aikido.dev 是資安公司，頁面應有相關關鍵字
    html_lower = result["html"].lower()
    assert any(kw in html_lower for kw in ["security", "blog", "aikido"]), \
        "頁面內容看起來不對"


@pytest.mark.integration
def test_fetch_page_real_wiz():
    """實際抓取 wiz.io/blog，確認拿到文章內容（JS 渲染）。"""
    from tools.fetchers.browser import fetch_page
    result = fetch_page("https://www.wiz.io/blog")

    assert "error" not in result, f"抓取失敗：{result.get('error')}"
    assert len(result["html"]) > 500
