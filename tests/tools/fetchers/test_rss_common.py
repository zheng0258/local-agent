"""rss_common — 共用 SSL context + feed 抓取。"""

import ssl
from unittest.mock import MagicMock, patch

import pytest

from tools.fetchers import rss_common

pytestmark = pytest.mark.unit


def test_ssl_context_is_verifying():
    """共用 context 必須驗證憑證（不得 CERT_NONE，修正 hatena 舊行為）。"""
    ctx = rss_common.ssl_context()
    assert ctx.verify_mode is ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_fetch_feed_returns_bytes_and_sets_user_agent():
    resp = MagicMock()
    resp.read.return_value = b"<rss/>"
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=resp) as urlopen:
        out = rss_common.fetch_feed("https://example.com/feed.xml")

    assert out == b"<rss/>"
    req = urlopen.call_args[0][0]
    assert req.get_header("User-agent") == "daily-brief/1.0"


def test_fetch_feed_propagates_errors():
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        with pytest.raises(OSError):
            rss_common.fetch_feed("https://example.com/feed.xml")
