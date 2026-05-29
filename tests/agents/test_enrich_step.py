"""_phase_enrich / _run_enrich 測試。"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


# ── Fixtures ────────────────────────────────────────────────────

def _make_agent(llm_response: str = '{"comment_summary": "社群觀點摘要文字"}'):
    from agents.daily_brief.agent import DailyBriefAgent
    mock_llm = MagicMock()
    mock_llm.complete.return_value = f"```json\n{llm_response}\n```"
    return DailyBriefAgent(llm=mock_llm)


_HN_COMPRESS = {
    "_meta": {"compressed_at": "2026-05-29T00:00:00"},
    "hn": {
        "themes": ["AI"],
        "articles": [
            {"title": "HN Article", "url": "https://news.ycombinator.com/item?id=123", "one_liner": "要點", "interest": "***"},
        ],
    },
    "reddit": {
        "themes": ["Security"],
        "articles": [
            {"title": "Reddit Article", "url": "https://www.reddit.com/r/netsec/comments/abc/title/", "one_liner": "要點", "interest": "***"},
        ],
    },
    "hatena": {"themes": [], "articles": []},
    "security": {"themes": [], "articles": []},
    "rss": {"themes": [], "articles": []},
}


# ── _run_enrich：正常路徑 ────────────────────────────────────────

def test_run_enrich_adds_comment_summary_to_hn():
    agent = _make_agent()
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1", "c2"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            result = agent._run_enrich(_HN_COMPRESS)
    hn_articles = result["hn"]["articles"]
    assert "comment_summary" in hn_articles[0]
    assert hn_articles[0]["comment_summary"] == "社群觀點摘要文字"


def test_run_enrich_adds_comment_summary_to_reddit():
    agent = _make_agent()
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            result = agent._run_enrich(_HN_COMPRESS)
    reddit_articles = result["reddit"]["articles"]
    assert "comment_summary" in reddit_articles[0]


def test_run_enrich_does_not_modify_non_hn_reddit_sources():
    agent = _make_agent()
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            result = agent._run_enrich(_HN_COMPRESS)
    for src in ["hatena", "security", "rss"]:
        for article in result.get(src, {}).get("articles", []):
            assert "comment_summary" not in article


def test_run_enrich_preserves_original_fields():
    agent = _make_agent()
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            result = agent._run_enrich(_HN_COMPRESS)
    hn_article = result["hn"]["articles"][0]
    assert hn_article["title"] == "HN Article"
    assert hn_article["url"] == "https://news.ycombinator.com/item?id=123"
    assert hn_article["one_liner"] == "要點"


# ── _run_enrich：部分失敗（best-effort）─────────────────────────

def test_run_enrich_skips_article_when_fetch_returns_empty():
    agent = _make_agent()
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=[]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            result = agent._run_enrich(_HN_COMPRESS)
    assert "comment_summary" not in result["hn"]["articles"][0]
    assert "comment_summary" in result["reddit"]["articles"][0]


def test_run_enrich_skips_article_when_llm_returns_invalid_json():
    agent = _make_agent(llm_response="invalid json {{{")
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            result = agent._run_enrich(_HN_COMPRESS)
    assert isinstance(result, dict)
    assert "hn" in result


def test_run_enrich_does_not_mutate_compress_data():
    """_run_enrich 不應修改傳入的 compress_data（回傳新 dict）。"""
    import copy
    agent = _make_agent()
    original = copy.deepcopy(_HN_COMPRESS)
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            agent._run_enrich(_HN_COMPRESS)
    assert _HN_COMPRESS == original


# ── _phase_enrich：idempotent ────────────────────────────────────

def test_phase_enrich_loads_existing_artifact(tmp_path):
    from agents.daily_brief.agent import DailyBriefAgent
    agent = _make_agent()
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()

    saved = {"_meta": {}, "hn": {"articles": [{"comment_summary": "cached"}]}}
    (steps_dir / "enrich.json").write_text(json.dumps(saved), encoding="utf-8")

    ctx = MagicMock()
    ctx.steps_to_run = {"enrich"}
    ctx.force_steps = set()
    ctx.steps_dir = steps_dir

    result = agent._phase_enrich(ctx, _HN_COMPRESS)
    assert result["hn"]["articles"][0]["comment_summary"] == "cached"


def test_phase_enrich_skips_when_not_in_steps_to_run(tmp_path):
    from agents.daily_brief.agent import DailyBriefAgent
    agent = _make_agent()
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()

    ctx = MagicMock()
    ctx.steps_to_run = {"digest"}
    ctx.force_steps = set()
    ctx.steps_dir = steps_dir

    result = agent._phase_enrich(ctx, _HN_COMPRESS)
    assert result is _HN_COMPRESS


def test_phase_enrich_writes_artifact(tmp_path):
    from agents.daily_brief.agent import DailyBriefAgent
    agent = _make_agent()
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()

    ctx = MagicMock()
    ctx.steps_to_run = {"enrich"}
    ctx.force_steps = set()
    ctx.steps_dir = steps_dir

    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            agent._phase_enrich(ctx, _HN_COMPRESS)

    assert (steps_dir / "enrich.json").exists()
    saved = json.loads((steps_dir / "enrich.json").read_text())
    assert "_meta" in saved
    assert "enriched_at" in saved["_meta"]
