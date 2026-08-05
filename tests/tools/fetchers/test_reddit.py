"""Reddit fetcher 測試（RSS-based）。"""

import os
import pytest
from unittest.mock import MagicMock, patch

from agents.daily_brief.config import REDDIT_SUBREDDITS

_ATOM_NS = "http://www.w3.org/2005/Atom"


def _make_rss(sub: str, titles: list[str]) -> str:
    entries = ""
    for i, title in enumerate(titles):
        entries += f"""
  <entry xmlns="{_ATOM_NS}">
    <title>{title}</title>
    <link href="https://www.reddit.com/r/{sub}/comments/{i}/post_{i}/"/>
    <content type="html">submitted by /u/user &lt;span&gt;&lt;a href="https://example.com/article"&gt;[link]&lt;/a&gt;&lt;/span&gt;</content>
  </entry>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="{_ATOM_NS}">
  <title>r/{sub}</title>{entries}
</feed>"""


def _http_response(status: int, body: str = "", reset: float | None = None) -> str:
    """組出 curl -D - 風格的原始輸出（HTTP 標頭 + 空白行 + body）。"""
    headers = f"HTTP/2 {status}\r\n"
    if reset is not None:
        headers += f"x-ratelimit-remaining: 0.0\r\nx-ratelimit-reset: {reset}\r\n"
    return headers + "\r\n" + body


def _mock_run_with_rss(sub_titles: dict[str, list[str]]):
    """mock subprocess.run，依 URL 中子版名稱回傳對應 RSS。"""
    def side_effect(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 0
        url = cmd[-1] if isinstance(cmd, list) else ""
        matched_sub = next((s for s in sub_titles if f"/r/{s}/" in url), None)
        m.stdout = _make_rss(matched_sub, sub_titles[matched_sub]) if matched_sub else ""
        return m
    return side_effect


@pytest.mark.integration
def test_fetch_returns_list():
    from tools.fetchers import reddit
    result = reddit.fetch()
    assert isinstance(result, list)


def test_fetch_posts_have_category_field():
    from tools.fetchers import reddit
    with patch("subprocess.run", side_effect=_mock_run_with_rss({"netsec": ["Post 1", "Post 2"]})):
        result = reddit.fetch()
    posts_with_category = [p for p in result if "category" in p]
    assert len(posts_with_category) == len(result)


def test_fetch_category_values_match_config():
    from tools.fetchers import reddit
    with patch("subprocess.run", side_effect=_mock_run_with_rss({"netsec": ["Post 1"]})):
        result = reddit.fetch()
    categories = {p["category"] for p in result}
    assert categories <= set(REDDIT_SUBREDDITS.keys())


def test_fetch_post_has_required_fields():
    from tools.fetchers import reddit
    with patch("subprocess.run", side_effect=_mock_run_with_rss({"netsec": ["Test Post"]})):
        result = reddit.fetch()
    for post in result:
        assert "title" in post
        assert "score" in post
        assert "url" in post
        assert "subreddit" in post
        assert "category" in post


def test_fetch_extracts_orig_url_from_content():
    from tools.fetchers import reddit
    with patch("subprocess.run", side_effect=_mock_run_with_rss({"netsec": ["Test Post"]})):
        result = reddit.fetch()
    posts_with_orig = [p for p in result if p.get("orig_url") == "https://example.com/article"]
    assert len(posts_with_orig) > 0


def test_fetch_invalid_rss_does_not_raise():
    from tools.fetchers import reddit
    m = MagicMock()
    m.returncode = 0
    m.stdout = "not valid xml"
    with patch("subprocess.run", return_value=m):
        result = reddit.fetch()
    assert isinstance(result, list)


def test_fetch_requests_limit_per_subreddit():
    from tools.fetchers import reddit
    captured = []

    def mock_run(cmd, **kwargs):
        captured.append(cmd)
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        return m

    with patch("subprocess.run", side_effect=mock_run):
        reddit.fetch()

    assert len(captured) > 0
    for cmd in captured:
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        assert "limit=" in cmd_str, f"URL 應含 limit=，實際：{cmd_str}"
        assert ".rss" in cmd_str, f"URL 應使用 .rss endpoint，實際：{cmd_str}"


def test_fetch_uses_iphone_user_agent():
    from tools.fetchers import reddit
    captured = []

    def mock_run(cmd, **kwargs):
        captured.append(cmd)
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        return m

    with patch("subprocess.run", side_effect=mock_run):
        reddit.fetch()

    assert len(captured) > 0
    for cmd in captured:
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        assert "iPhone" in cmd_str or "Mozilla" in cmd_str


def test_top_n_is_three():
    from tools.fetchers import reddit
    assert reddit.TOP_N == 3


def test_fetch_requests_limit_3():
    from tools.fetchers import reddit
    captured = []

    def mock_run(cmd, **kwargs):
        captured.append(" ".join(cmd) if isinstance(cmd, list) else cmd)
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        return m

    with patch("subprocess.run", side_effect=mock_run):
        reddit.fetch()

    assert len(captured) > 0
    for cmd_str in captured:
        assert "limit=3" in cmd_str, f"URL 應含 limit=3，實際：{cmd_str}"


def test_split_response_parses_status_and_reset():
    from tools.fetchers import reddit
    raw = _http_response(200, body=_make_rss("netsec", ["Post"]), reset=42)
    status, body, reset = reddit._split_response(raw)
    assert status == 200
    assert reset == 42.0
    assert "<entry" in body


def test_split_response_no_status_line_is_body():
    from tools.fetchers import reddit
    status, body, reset = reddit._split_response("just a body")
    assert status is None
    assert body == "just a body"
    assert reset is None


def test_fetch_parses_header_prefixed_response():
    from tools.fetchers import reddit

    def mock_run(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 0
        url = cmd[-1]
        if "/r/netsec/" in url:
            m.stdout = _http_response(200, body=_make_rss("netsec", ["Header Post"]), reset=1)
        else:
            m.stdout = _http_response(200, body="", reset=1)
        return m

    with patch("subprocess.run", side_effect=mock_run), \
            patch("tools.fetchers.reddit.time.sleep"):
        result = reddit.fetch()

    assert any(p["title"] == "Header Post" for p in result)


def test_fetch_429_retries_then_recovers():
    from tools.fetchers import reddit
    calls = {"netsec": 0}
    rss = _make_rss("netsec", ["Recovered Post"])

    def mock_run(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 0
        url = cmd[-1]
        if "/r/netsec/" in url:
            calls["netsec"] += 1
            m.stdout = (
                _http_response(429, reset=1)
                if calls["netsec"] == 1
                else _http_response(200, body=rss, reset=1)
            )
        else:
            m.stdout = _http_response(200, body="", reset=1)
        return m

    with patch("subprocess.run", side_effect=mock_run), \
            patch("tools.fetchers.reddit.time.sleep"):
        result = reddit.fetch()

    assert calls["netsec"] == 2, "429 後應重試一次"
    assert any(p["title"] == "Recovered Post" for p in result)


def test_fetch_sleeps_between_requests_using_reset():
    from tools.fetchers import reddit

    def mock_run(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 0
        m.stdout = _http_response(200, body="", reset=5)
        return m

    with patch("subprocess.run", side_effect=mock_run), \
            patch("tools.fetchers.reddit.time.sleep") as slp:
        reddit.fetch()

    slept = [c.args[0] for c in slp.call_args_list if c.args]
    # reset=5 + buffer=2 → 後續請求前應等待 ~7s
    assert any(abs(s - 7.0) < 0.01 for s in slept), f"未依 reset 等待，實際 sleep：{slept}"


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("CI_NETWORK"),
    reason="需要網路連線（設定 CI_NETWORK=1 開啟）",
)
def test_fetch_real_network_returns_posts():
    from tools.fetchers import reddit
    result = reddit.fetch()
    assert isinstance(result, list)
    assert len(result) > 0, f"所有子版都沒有文章：{result}"
