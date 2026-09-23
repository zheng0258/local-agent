"""Reddit comments fetcher 測試。"""

import json
import os
import pytest
from types import SimpleNamespace
from unittest.mock import patch


REDDIT_POST_URL = "https://www.reddit.com/r/netsec/comments/abc123/some_title"
_FAKE_CREDS = {"REDDIT_CLIENT_ID": "fake_id", "REDDIT_CLIENT_SECRET": "fake_secret"}
_FAKE_TOKEN = "fake_token"


def _make_reddit_response(comments: list[str]) -> str:
    children = [
        {"kind": "t1", "data": {"body": c, "score": 100 - i}}
        for i, c in enumerate(comments)
    ]
    return json.dumps([
        {"data": {}},
        {"data": {"children": children}},
    ])


def _with_token(fake_response: str):
    """同時 mock credentials + _get_token + _curl_get。"""
    return (
        patch.dict(os.environ, _FAKE_CREDS),
        patch("tools.fetchers.reddit_comments._get_token", return_value=_FAKE_TOKEN),
        patch("tools.fetchers.reddit_comments._curl_get", return_value=fake_response),
    )


def test_fetch_comments_returns_list_of_strings():
    from tools.fetchers.reddit_comments import fetch_comments
    fake = _make_reddit_response(["comment A", "comment B"])
    with patch.dict(os.environ, _FAKE_CREDS), \
         patch("tools.fetchers.reddit_comments._get_token", return_value=_FAKE_TOKEN), \
         patch("tools.fetchers.reddit_comments._curl_get", return_value=fake):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == ["comment A", "comment B"]


def test_fetch_comments_truncates_at_300_chars():
    from tools.fetchers.reddit_comments import fetch_comments
    long_body = "y" * 500
    fake = _make_reddit_response([long_body])
    with patch.dict(os.environ, _FAKE_CREDS), \
         patch("tools.fetchers.reddit_comments._get_token", return_value=_FAKE_TOKEN), \
         patch("tools.fetchers.reddit_comments._curl_get", return_value=fake):
        result = fetch_comments(REDDIT_POST_URL)
    assert len(result[0]) == 300


def test_fetch_comments_respects_top_n():
    from tools.fetchers.reddit_comments import fetch_comments
    comments = [f"comment {i}" for i in range(15)]
    fake = _make_reddit_response(comments)
    with patch.dict(os.environ, _FAKE_CREDS), \
         patch("tools.fetchers.reddit_comments._get_token", return_value=_FAKE_TOKEN), \
         patch("tools.fetchers.reddit_comments._curl_get", return_value=fake):
        result = fetch_comments(REDDIT_POST_URL, top_n=5)
    assert len(result) == 5


def test_fetch_comments_filters_deleted():
    from tools.fetchers.reddit_comments import fetch_comments
    fake = _make_reddit_response(["[deleted]", "[removed]", "valid comment"])
    with patch.dict(os.environ, _FAKE_CREDS), \
         patch("tools.fetchers.reddit_comments._get_token", return_value=_FAKE_TOKEN), \
         patch("tools.fetchers.reddit_comments._curl_get", return_value=fake):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == ["valid comment"]


def test_fetch_comments_returns_empty_on_network_error():
    from tools.fetchers.reddit_comments import fetch_comments
    with patch.dict(os.environ, _FAKE_CREDS), \
         patch("tools.fetchers.reddit_comments._get_token", return_value=_FAKE_TOKEN), \
         patch("tools.fetchers.reddit_comments._curl_get", side_effect=RuntimeError("403")):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == []


def test_fetch_comments_returns_empty_on_invalid_json():
    from tools.fetchers.reddit_comments import fetch_comments
    with patch.dict(os.environ, _FAKE_CREDS), \
         patch("tools.fetchers.reddit_comments._get_token", return_value=_FAKE_TOKEN), \
         patch("tools.fetchers.reddit_comments._curl_get", return_value="bad json"):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == []


def test_fetch_comments_returns_empty_without_credentials():
    from tools.fetchers.reddit_comments import fetch_comments
    env_without_creds = {k: v for k, v in os.environ.items()
                         if k not in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET")}
    with patch.dict(os.environ, env_without_creds, clear=True):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == []


def test_fetch_comments_url_uses_oauth_api():
    """_curl_get 應傳入 OAuth API URL（oauth.reddit.com）。"""
    from tools.fetchers.reddit_comments import fetch_comments
    called_urls: list[str] = []

    def _capture_url(url: str, token: str, **kwargs) -> str:
        called_urls.append(url)
        raise RuntimeError("stop")

    with patch.dict(os.environ, _FAKE_CREDS), \
         patch("tools.fetchers.reddit_comments._get_token", return_value=_FAKE_TOKEN), \
         patch("tools.fetchers.reddit_comments._curl_get", side_effect=_capture_url):
        fetch_comments(REDDIT_POST_URL)

    assert len(called_urls) == 1
    assert "oauth.reddit.com" in called_urls[0]
    assert "limit=" in called_urls[0]
    assert "sort=best" in called_urls[0]


@pytest.mark.unit
def test_get_token_keeps_client_secret_off_argv():
    """client secret 絕不進 argv（`ps -ww` 全機可讀）；改由 stdin 的 curl config 供給。"""
    from tools.fetchers import reddit_comments

    seen = {}

    def fake_run(args, **kwargs):
        seen["argv"] = args
        seen["input"] = kwargs.get("input", "")
        return SimpleNamespace(stdout='{"access_token": "tok"}', stderr="", returncode=0)

    with patch("subprocess.run", side_effect=fake_run):
        assert reddit_comments._get_token("my-id", "my-secret") == "tok"

    assert "my-secret" not in " ".join(seen["argv"])
    assert "--user" not in seen["argv"]
    assert "--config" in seen["argv"]
    assert 'user = "my-id:my-secret"' in seen["input"]


@pytest.mark.unit
def test_curl_get_keeps_bearer_token_off_argv():
    """bearer token 同理：不進 argv，走 stdin config 的 header 選項。"""
    from tools.fetchers import reddit_comments

    seen = {}

    def fake_run(args, **kwargs):
        seen["argv"] = args
        seen["input"] = kwargs.get("input", "")
        return SimpleNamespace(stdout="body", stderr="", returncode=0)

    with patch("subprocess.run", side_effect=fake_run):
        assert reddit_comments._curl_get("https://oauth.reddit.com/x", "secret-tok") == "body"

    assert "secret-tok" not in " ".join(seen["argv"])
    assert 'header = "Authorization: bearer secret-tok"' in seen["input"]


@pytest.mark.unit
def test_curl_quote_escapes_config_metacharacters():
    """curl config 為雙引號字串：secret 內的 \\ 與 " 必須轉義，否則選項被截斷。"""
    from tools.fetchers.reddit_comments import _curl_quote

    assert _curl_quote(r'a"b\c') == r'a\"b\\c'
