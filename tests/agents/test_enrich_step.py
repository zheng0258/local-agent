"""EnrichStep 測試 — producer 邏輯住 _produce/_enrich_article（讀 ctx.llm）。

用 FakeLLM 注入 canned 留言摘要；留言抓取以 patch 模擬。best-effort 特徵留在此。
"""

import json
from unittest.mock import patch

import pytest

from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.enrich import EnrichStep, sanitize_comment_summary
from tests.fakes import FakeLLM, make_step_ctx


def _llm(comment_summary: str = "社群觀點摘要文字") -> FakeLLM:
    return FakeLLM(default=f'```json\n{{"comment_summary": "{comment_summary}"}}\n```')


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


def _run_enrich(tmp_path, llm=None, hn_comments=("c1", "c2"), reddit_comments=("rc1",)):
    ctx = make_step_ctx(tmp_path, steps_to_run={"enrich"}, llm=llm or _llm())
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=list(hn_comments)):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=list(reddit_comments)):
            return EnrichStep().run(ctx, _HN_COMPRESS)


# ── 正常路徑 ────────────────────────────────────────────────────

def test_enrich_adds_comment_summary_to_hn(tmp_path):
    result = _run_enrich(tmp_path).value
    hn_articles = result["hn"]["articles"]
    assert hn_articles[0]["comment_summary"] == "社群觀點摘要文字"


def test_enrich_adds_comment_summary_to_reddit(tmp_path):
    result = _run_enrich(tmp_path).value
    assert "comment_summary" in result["reddit"]["articles"][0]


def test_enrich_does_not_modify_non_hn_reddit_sources(tmp_path):
    result = _run_enrich(tmp_path).value
    for src in ["hatena", "security", "rss"]:
        for article in result.get(src, {}).get("articles", []):
            assert "comment_summary" not in article


def test_enrich_preserves_original_fields(tmp_path):
    hn_article = _run_enrich(tmp_path).value["hn"]["articles"][0]
    assert hn_article["title"] == "HN Article"
    assert hn_article["url"] == "https://news.ycombinator.com/item?id=123"
    assert hn_article["one_liner"] == "要點"


# ── 部分失敗（best-effort）─────────────────────────────────────

def test_enrich_skips_article_when_fetch_returns_empty(tmp_path):
    result = _run_enrich(tmp_path, hn_comments=()).value
    assert "comment_summary" not in result["hn"]["articles"][0]
    assert "comment_summary" in result["reddit"]["articles"][0]


def test_enrich_skips_article_when_llm_returns_invalid_json(tmp_path):
    result = _run_enrich(tmp_path, llm=FakeLLM(default="invalid json {{{")).value
    assert isinstance(result, dict)
    assert "hn" in result


def test_enrich_does_not_mutate_compress_data(tmp_path):
    import copy

    original = copy.deepcopy(_HN_COMPRESS)
    _run_enrich(tmp_path)
    assert _HN_COMPRESS == original


# ── idempotent gating ────────────────────────────────────────────

def test_enrich_step_loads_existing_artifact(tmp_path):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    saved = {"_meta": {}, "hn": {"articles": [{"comment_summary": "cached"}]}}
    (steps_dir / "enrich.json").write_text(json.dumps(saved), encoding="utf-8")

    ctx = make_step_ctx(steps_dir, steps_to_run={"enrich"})
    outcome = EnrichStep().run(ctx, _HN_COMPRESS)
    assert outcome.status is StepStatus.LOADED
    assert outcome.value["hn"]["articles"][0]["comment_summary"] == "cached"


def test_enrich_step_skips_when_not_in_steps_to_run(tmp_path):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    ctx = make_step_ctx(steps_dir, steps_to_run={"digest"})
    outcome = EnrichStep().run(ctx, _HN_COMPRESS)
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is _HN_COMPRESS


def test_enrich_step_writes_artifact(tmp_path):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    ctx = make_step_ctx(steps_dir, steps_to_run={"enrich"}, llm=_llm())
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            EnrichStep().run(ctx, _HN_COMPRESS)

    saved = json.loads((steps_dir / "enrich.json").read_text())
    assert "enriched_at" in saved["_meta"]


def test_sanitize_comment_summary_strips_injection():
    out = sanitize_comment_summary("<b>hi</b> https://evil.com ```x```")
    assert "<b>" not in out
    assert "evil.com" not in out
    assert "```" not in out
    assert "hi" in out
