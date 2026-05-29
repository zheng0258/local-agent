"""Reddit comments fetcher 測試。"""

import json
from unittest.mock import patch


REDDIT_POST_URL = "https://www.reddit.com/r/netsec/comments/abc123/some_title"


def _make_reddit_response(comments: list[str]) -> str:
    children = [
        {"kind": "t1", "data": {"body": c, "score": 100 - i}}
        for i, c in enumerate(comments)
    ]
    return json.dumps([
        {"data": {}},
        {"data": {"children": children}},
    ])


def test_fetch_comments_returns_list_of_strings():
    from tools.fetchers.reddit_comments import fetch_comments
    fake = _make_reddit_response(["comment A", "comment B"])
    with patch("tools.fetchers.reddit_comments._curl_get", return_value=fake):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == ["comment A", "comment B"]


def test_fetch_comments_truncates_at_300_chars():
    from tools.fetchers.reddit_comments import fetch_comments
    long_body = "y" * 500
    fake = _make_reddit_response([long_body])
    with patch("tools.fetchers.reddit_comments._curl_get", return_value=fake):
        result = fetch_comments(REDDIT_POST_URL)
    assert len(result[0]) == 300


def test_fetch_comments_respects_top_n():
    from tools.fetchers.reddit_comments import fetch_comments
    comments = [f"comment {i}" for i in range(15)]
    fake = _make_reddit_response(comments)
    with patch("tools.fetchers.reddit_comments._curl_get", return_value=fake):
        result = fetch_comments(REDDIT_POST_URL, top_n=5)
    assert len(result) == 5


def test_fetch_comments_filters_deleted():
    from tools.fetchers.reddit_comments import fetch_comments
    fake = _make_reddit_response(["[deleted]", "[removed]", "valid comment"])
    with patch("tools.fetchers.reddit_comments._curl_get", return_value=fake):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == ["valid comment"]


def test_fetch_comments_returns_empty_on_network_error():
    from tools.fetchers.reddit_comments import fetch_comments
    with patch("tools.fetchers.reddit_comments._curl_get", side_effect=RuntimeError("403")):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == []


def test_fetch_comments_returns_empty_on_invalid_json():
    from tools.fetchers.reddit_comments import fetch_comments
    with patch("tools.fetchers.reddit_comments._curl_get", return_value="bad json"):
        result = fetch_comments(REDDIT_POST_URL)
    assert result == []


def test_fetch_comments_url_gets_json_suffix():
    """_curl_get 被呼叫時，URL 必須以 .json 開頭（含 query string）。"""
    from tools.fetchers.reddit_comments import fetch_comments
    called_urls: list[str] = []

    def _capture_url(url: str) -> str:
        called_urls.append(url)
        raise RuntimeError("stop")

    with patch("tools.fetchers.reddit_comments._curl_get", side_effect=_capture_url):
        fetch_comments(REDDIT_POST_URL)

    assert called_urls[0].endswith(".json?limit=10&sort=best")
