"""HN comments fetcher 測試。"""

import json
from unittest.mock import patch, MagicMock


HN_URL = "https://news.ycombinator.com/item?id=48296794"

# ── fetch_comments(item_id) ──────────────────────────────────────

def test_fetch_comments_returns_list_of_strings():
    from tools.fetchers.hn_comments import fetch_comments
    fake_api = json.dumps({
        "id": 48296794,
        "children": [
            {"id": 1, "text": "Great article!", "children": []},
            {"id": 2, "text": "I disagree.", "children": []},
        ]
    })
    with patch("tools.fetchers.hn_comments._curl_get", return_value=fake_api):
        result = fetch_comments("48296794")
    assert isinstance(result, list)
    assert result == ["Great article!", "I disagree."]


def test_fetch_comments_strips_html_tags():
    from tools.fetchers.hn_comments import fetch_comments
    fake_api = json.dumps({
        "children": [
            {"id": 1, "text": "<p>Hello <b>world</b></p>", "children": []},
        ]
    })
    with patch("tools.fetchers.hn_comments._curl_get", return_value=fake_api):
        result = fetch_comments("123")
    assert result == ["Hello world"]


def test_fetch_comments_truncates_at_300_chars():
    from tools.fetchers.hn_comments import fetch_comments
    long_text = "x" * 500
    fake_api = json.dumps({"children": [{"id": 1, "text": long_text, "children": []}]})
    with patch("tools.fetchers.hn_comments._curl_get", return_value=fake_api):
        result = fetch_comments("123")
    assert len(result[0]) == 300


def test_fetch_comments_respects_top_n():
    from tools.fetchers.hn_comments import fetch_comments
    children = [{"id": i, "text": f"comment {i}", "children": []} for i in range(15)]
    fake_api = json.dumps({"children": children})
    with patch("tools.fetchers.hn_comments._curl_get", return_value=fake_api):
        result = fetch_comments("123", top_n=5)
    assert len(result) == 5


def test_fetch_comments_skips_none_text():
    from tools.fetchers.hn_comments import fetch_comments
    fake_api = json.dumps({
        "children": [
            {"id": 1, "text": None, "children": []},
            {"id": 2, "text": "valid", "children": []},
        ]
    })
    with patch("tools.fetchers.hn_comments._curl_get", return_value=fake_api):
        result = fetch_comments("123")
    assert result == ["valid"]


def test_fetch_comments_returns_empty_on_network_error():
    from tools.fetchers.hn_comments import fetch_comments
    with patch("tools.fetchers.hn_comments._curl_get", side_effect=RuntimeError("timeout")):
        result = fetch_comments("123")
    assert result == []


def test_fetch_comments_returns_empty_on_invalid_json():
    from tools.fetchers.hn_comments import fetch_comments
    with patch("tools.fetchers.hn_comments._curl_get", return_value="not json"):
        result = fetch_comments("123")
    assert result == []


# ── parse_item_id(url) ───────────────────────────────────────────

def test_parse_item_id_valid():
    from tools.fetchers.hn_comments import parse_item_id
    assert parse_item_id("https://news.ycombinator.com/item?id=48296794") == "48296794"


def test_parse_item_id_invalid_returns_none():
    from tools.fetchers.hn_comments import parse_item_id
    assert parse_item_id("https://news.ycombinator.com/") is None
    assert parse_item_id("https://example.com") is None
