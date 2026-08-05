"""JudgeStep — producer 邏輯住 _produce/_judge（讀 ctx.judge_llm）；含品質分/歷史側寫。

step 層（RAN/FAILED/guard/default）走 .run()；_judge producer 特徵直接呼叫 _judge。
_append_judge_history 寫 config.OUTPUT_DIR → 各 _judge 測試以 monkeypatch 導向 tmp_path。
"""

import json
from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.judge import JudgeStep
from tests.fakes import FakeLLM, make_step_ctx

from unittest.mock import patch


def _ctx(tmp_path, steps_to_run={"judge"}, force=set(), judge_llm=None):
    return make_step_ctx(
        tmp_path, steps_to_run=steps_to_run, force_steps=force, judge_llm=judge_llm
    )


def _judge(tmp_path, monkeypatch, resp, digests, compress=None, source_data=None):
    """直接驅動 _judge producer；OUTPUT_DIR 導向 tmp_path（隔離歷史側寫）。"""
    import agents.daily_brief.config as cfg

    monkeypatch.setattr(cfg, "OUTPUT_DIR", tmp_path)
    ctx = SimpleNamespace(judge_llm=FakeLLM(default=resp), today="2026-06-21")
    return JudgeStep()._judge(
        ctx, compress or {"hatena": {"themes": [], "articles": []}}, digests, source_data
    )


# ── step 層 gating ───────────────────────────────────────────────

@pytest.mark.unit
def test_judge_step_runs_and_persists(tmp_path, monkeypatch):
    import agents.daily_brief.config as cfg

    monkeypatch.setattr(cfg, "OUTPUT_DIR", tmp_path)
    resp = json.dumps(
        {"scores": {"completeness": {"score": 4, "missed_urls": []}}, "missed_urls": []}
    )
    llm = FakeLLM(default=resp)
    with patch("agents.daily_brief.steps.judge.check_local_llm", return_value=True):
        outcome = JudgeStep().run(
            _ctx(tmp_path, judge_llm=llm), ({"hn": {}}, [{"url": "http://a"}], {})
        )
    assert outcome.status is StepStatus.RAN
    assert JsonCodec().read(tmp_path / "judge.json")["overall"] == 4.0


@pytest.mark.unit
def test_judge_step_fails_when_server_down(tmp_path):
    with patch("agents.daily_brief.steps.judge.check_local_llm", return_value=False):
        outcome = JudgeStep().run(
            _ctx(tmp_path), ({"hn": {}}, [{"url": "http://a"}], {})
        )
    assert outcome.status is StepStatus.FAILED
    assert outcome.value is None
    assert not (tmp_path / "judge.json").exists()


@pytest.mark.unit
def test_judge_step_guard_blocks_without_digests(tmp_path):
    outcome = JudgeStep().run(_ctx(tmp_path), ({"hn": {}}, [], {}))
    assert outcome.status is StepStatus.SKIPPED


@pytest.mark.unit
def test_judge_step_default_is_none(tmp_path):
    outcome = JudgeStep().run(
        _ctx(tmp_path, steps_to_run=set()), ({"hn": {}}, [{"url": "http://a"}], {})
    )
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None


# ── _judge producer 特徵 ─────────────────────────────────────────

@pytest.mark.unit
def test_judge_reads_missed_urls_from_top_level(tmp_path, monkeypatch):
    resp = json.dumps(
        {
            "scores": {
                "relevance": {"score": 5, "reasoning": "ok"},
                "completeness": {"score": 2, "reasoning": "遺漏"},
                "faithfulness": {"score": 5, "reasoning": "ok"},
            },
            "missed_urls": ["https://example.com/m1", "https://example.com/m2"],
        }
    )
    result = _judge(tmp_path, monkeypatch, resp, [])
    completeness = result["scores"]["completeness"]
    assert completeness["missed_urls"] == [
        "https://example.com/m1",
        "https://example.com/m2",
    ]


@pytest.mark.unit
def test_judge_returns_scores_and_overall(tmp_path, monkeypatch):
    resp = json.dumps(
        {
            "scores": {
                "relevance": {"score": 4, "reasoning": "OK"},
                "completeness": {"score": 3, "reasoning": "missed one", "missed_urls": []},
                "faithfulness": {"score": 5, "reasoning": "accurate"},
            }
        }
    )
    result = _judge(tmp_path, monkeypatch, resp, [{"url": "https://u.com"}])
    assert result["scores"]["relevance"]["score"] == 4
    assert result["overall"] == 4.0
    assert "judged_at" in result
    assert "judge_model" in result


@pytest.mark.unit
def test_judge_passes_slim_compress_to_llm(tmp_path, monkeypatch):
    import agents.daily_brief.config as cfg

    monkeypatch.setattr(cfg, "OUTPUT_DIR", tmp_path)
    resp = json.dumps(
        {"scores": {"completeness": {"score": 4, "missed_urls": []}}}
    )
    llm = FakeLLM(default=resp)
    ctx = SimpleNamespace(judge_llm=llm, today="2026-06-21")
    compress = {
        "hatena": {
            "themes": ["AI"],
            "articles": [
                {
                    "title": "完整標題不應出現在 judge prompt",
                    "url": "https://example.com/1",
                    "one_liner": "核心摘要",
                    "bookmarks": 999,
                    "extra_field": "多餘",
                }
            ],
        }
    }
    JudgeStep()._judge(ctx, compress, [{"url": "https://example.com/1"}])
    prompt = llm.prompts[0]
    assert "https://example.com/1" in prompt
    assert "核心摘要" in prompt
    assert "完整標題不應出現在 judge prompt" not in prompt
    assert "extra_field" not in prompt
    assert "bookmarks" not in prompt


@pytest.mark.unit
def test_judge_quality_alert_when_completeness_below_threshold(tmp_path, monkeypatch):
    resp = json.dumps(
        {
            "scores": {
                "relevance": {"score": 5, "reasoning": "ok"},
                "completeness": {"score": 2, "reasoning": "missed many", "missed_urls": ["https://a.com"]},
                "faithfulness": {"score": 5, "reasoning": "ok"},
            }
        }
    )
    result = _judge(tmp_path, monkeypatch, resp, [])
    assert result.get("quality_alert") is True
    assert "completeness" in result.get("quality_alert_reason", "")


@pytest.mark.unit
def test_judge_no_alert_when_completeness_sufficient(tmp_path, monkeypatch):
    resp = json.dumps(
        {
            "scores": {
                "relevance": {"score": 4, "reasoning": "ok"},
                "completeness": {"score": 3, "reasoning": "ok", "missed_urls": []},
                "faithfulness": {"score": 4, "reasoning": "ok"},
            }
        }
    )
    result = _judge(tmp_path, monkeypatch, resp, [])
    assert not result.get("quality_alert")


@pytest.mark.unit
def test_judge_appends_to_history(tmp_path, monkeypatch):
    resp = json.dumps(
        {
            "scores": {
                "relevance": {"score": 5, "reasoning": "ok"},
                "completeness": {"score": 4, "reasoning": "ok", "missed_urls": []},
                "faithfulness": {"score": 5, "reasoning": "ok"},
            }
        }
    )
    import agents.daily_brief.config as cfg

    monkeypatch.setattr(cfg, "OUTPUT_DIR", tmp_path)
    ctx = SimpleNamespace(judge_llm=FakeLLM(default=resp), today="2026-04-14")
    JudgeStep()._judge(ctx, {"hatena": {"themes": [], "articles": []}}, [], date="2026-04-14")

    history = json.loads((tmp_path / "_judge-history.json").read_text(encoding="utf-8"))
    assert len(history) == 1
    assert history[0]["date"] == "2026-04-14"
    assert history[0]["overall"] == 4.7


@pytest.mark.unit
def test_judge_history_accumulates_across_runs(tmp_path, monkeypatch):
    import agents.daily_brief.config as cfg

    monkeypatch.setattr(cfg, "OUTPUT_DIR", tmp_path)
    resp = json.dumps(
        {
            "scores": {
                "relevance": {"score": 4, "reasoning": "ok"},
                "completeness": {"score": 4, "reasoning": "ok", "missed_urls": []},
                "faithfulness": {"score": 4, "reasoning": "ok"},
            }
        }
    )
    for date_str in ("2026-04-13", "2026-04-14"):
        ctx = SimpleNamespace(judge_llm=FakeLLM(default=resp), today=date_str)
        JudgeStep()._judge(ctx, {"hatena": {"themes": [], "articles": []}}, [], date=date_str)

    history = json.loads((tmp_path / "_judge-history.json").read_text(encoding="utf-8"))
    assert {r["date"] for r in history} == {"2026-04-13", "2026-04-14"}


@pytest.mark.unit
def test_judge_pairs_digests_with_original_titles(tmp_path, monkeypatch):
    import agents.daily_brief.config as cfg

    monkeypatch.setattr(cfg, "OUTPUT_DIR", tmp_path)
    resp = json.dumps(
        {"scores": {"completeness": {"score": 4, "missed_urls": []}}, "missed_urls": []}
    )
    llm = FakeLLM(default=resp)
    ctx = SimpleNamespace(judge_llm=llm, today="2026-06-21")
    source_data = {
        "hn": {
            "articles": [
                {
                    "title": "繁中翻譯標題",
                    "url": "https://example.com/1",
                    "original_title": "Raw Original Title",
                    "original_description": "raw desc",
                }
            ]
        }
    }
    digests = [{"title": "繁中翻譯標題", "url": "https://example.com/1"}]
    JudgeStep()._judge(ctx, {}, digests, source_data)
    prompt = llm.prompts[0]
    assert "Raw Original Title" in prompt
    assert "raw desc" in prompt


@pytest.mark.unit
def test_judge_original_title_falls_back_to_source_title(tmp_path, monkeypatch):
    import agents.daily_brief.config as cfg

    monkeypatch.setattr(cfg, "OUTPUT_DIR", tmp_path)
    resp = json.dumps(
        {"scores": {"completeness": {"score": 4, "missed_urls": []}}, "missed_urls": []}
    )
    llm = FakeLLM(default=resp)
    ctx = SimpleNamespace(judge_llm=llm, today="2026-06-21")
    source_data = {
        "hatena": {"articles": [{"title": "Legacy Artifact Title", "url": "https://example.com/2"}]}
    }
    digests = [{"title": "譯", "url": "https://example.com/2"}]
    JudgeStep()._judge(ctx, {}, digests, source_data)
    assert "Legacy Artifact Title" in llm.prompts[0]
