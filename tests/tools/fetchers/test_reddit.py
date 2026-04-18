"""Reddit fetcher 測試。"""

import pytest
import json
from unittest.mock import patch, MagicMock


def _make_reddit_response(sub: str, n: int = 3) -> str:
    """產生假的 Reddit API 回應。"""
    children = [
        {
            "data": {
                "title": f"Post {i} from r/{sub}",
                "score": 100 * i,
                "num_comments": 10 * i,
                "permalink": f"/r/{sub}/comments/{i}/post_{i}/",
            }
        }
        for i in range(1, n + 1)
    ]
    return json.dumps({"data": {"children": children}})


def test_fetch_returns_dict():
    from tools.fetchers import reddit
    result = reddit.fetch()
    assert isinstance(result, dict)


def test_fetch_keys_match_categories():
    from tools.fetchers import reddit
    from agents.daily_brief.config import REDDIT_SUBREDDITS
    result = reddit.fetch()
    for category in REDDIT_SUBREDDITS:
        assert category in result


def test_fetch_each_category_is_list():
    from tools.fetchers import reddit
    result = reddit.fetch()
    for category, posts in result.items():
        assert isinstance(posts, list), f"{category} 應為 list"


def test_fetch_post_has_required_fields():
    mock_run = MagicMock()
    mock_run.return_value.stdout = _make_reddit_response("netsec")

    with patch("subprocess.run", return_value=mock_run.return_value):
        from tools.fetchers import reddit
        result = reddit.fetch()

    for posts in result.values():
        for post in posts:
            assert "title" in post
            assert "score" in post
            assert "url" in post
            assert "subreddit" in post


def test_fetch_invalid_json_does_not_raise():
    """curl 回傳非 JSON 時不應拋出例外，該 subreddit 跳過。"""
    mock_run = MagicMock()
    mock_run.return_value.stdout = "not valid json"

    with patch("subprocess.run", return_value=mock_run.return_value):
        from tools.fetchers import reddit
        result = reddit.fetch()

    assert isinstance(result, dict)


def test_fetch_empty_response_returns_empty_lists():
    """curl 無輸出時各類別應為空 list。"""
    mock_run = MagicMock()
    mock_run.return_value.stdout = ""

    with patch("subprocess.run", return_value=mock_run.return_value):
        from tools.fetchers import reddit
        result = reddit.fetch()

    for posts in result.values():
        assert posts == []


def test_fetch_requests_limit_5_per_subreddit():
    """每個子版的請求 URL 應包含 limit=5。"""
    captured_urls = []

    def mock_run(cmd, **kwargs):
        captured_urls.append(cmd)
        m = MagicMock()
        m.stdout = ""
        return m

    with patch("subprocess.run", side_effect=mock_run):
        from tools.fetchers import reddit
        reddit.fetch()

    assert len(captured_urls) > 0
    for cmd in captured_urls:
        assert "limit=5" in cmd, f"URL 應含 limit=5，實際：{cmd}"


@pytest.mark.integration
def test_fetch_real_network_returns_posts():
    from tools.fetchers import reddit
    result = reddit.fetch()

    assert isinstance(result, dict)
    total_posts = sum(len(v) for v in result.values())
    assert total_posts > 0, f"所有子版都沒有文章：{result}"
