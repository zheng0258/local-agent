"""RSS/Atom fetcher 共用工具：SSL context + feed 抓取。

三個 RSS 來源（hatena / security_blogs / rss）原各自建 SSL context 與抓取邏輯；
hatena 曾用不安全的 CERT_NONE，統一走 certifi。安全 XML 解析請用 defusedxml。
parse 邏輯仍住各 fetcher（Hatena RDF 多格式 / security RSS2.0 / rss feedparser 各異）。
"""

from __future__ import annotations

import ssl
import urllib.request

DESCRIPTION_MAX_CHARS = 200
_USER_AGENT = "daily-brief/1.0"
_DEFAULT_TIMEOUT = 30


def ssl_context() -> ssl.SSLContext:
    """優先用 certifi 憑證（繞過 macOS python.org 安裝的 SSL 問題）；不用 CERT_NONE。"""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch_feed(url: str, timeout: int = _DEFAULT_TIMEOUT) -> bytes:
    """抓一個 feed 的原始 bytes（帶 UA、走 certifi SSL）。

    呼叫端負責 try/except 與各自的錯誤契約（RSS 來源多為 append error dict）。
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
        return resp.read()
