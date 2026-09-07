"""完整性校正 seam（completeness.reconcile_completeness）的直接單元測試。

重點：這段迴圈現在有自己的 interface，可直接餵 ctx + 資料驗證，
不必像過去那樣驅動整個 DailyBriefAgent.run() 才能觸發。
"""

import json

import pytest

from agents.daily_brief.completeness import COMPLETENESS_FLOOR, reconcile_completeness
from tests.fakes import FakeLLM, FakeSupervisor, make_step_ctx

pytestmark = pytest.mark.unit


_COMPRESS = {
    "hatena": {
        "themes": ["AI"],
        "articles": [{"url": "https://example.com/new", "one_liner": "new one liner"}],
    }
}


def _judge_json(completeness: int, missed=None):
    return json.dumps(
        {
            "scores": {"completeness": {"score": completeness}},
            "missed_urls": missed or [],
        }
    )


def _seed_judge_dir(tmp_path, today):
    # judge step 寫 _judge-history.json 需要 OUTPUT_DIR/... 存在；用 tmp 當 steps_dir 即可
    (tmp_path / today / "steps").mkdir(parents=True, exist_ok=True)


def test_reconcile_returns_original_digests_when_complete(tmp_path):
    """completeness ≥ 門檻 → 不重生 digest，回傳原 digests，且不進 reflect。"""
    digests = [{"url": "https://example.com/a", "summary": "a"}]
    ctx = make_step_ctx(
        tmp_path,
        supervisor=FakeSupervisor(forbid_reflect=True),
        judge_llm=FakeLLM(responses=[_judge_json(COMPLETENESS_FLOOR)]),
        llm=FakeLLM(),
    )
    result = reconcile_completeness(ctx, _COMPRESS, digests, {})
    assert result == digests


def test_reconcile_regenerates_digest_when_incomplete(tmp_path):
    """completeness < 門檻 → 進 reflect、重生 digest（用主 llm 的新回應）、重評。"""
    old_digests = [{"url": "https://example.com/old", "summary": "old"}]
    new_digest_resp = json.dumps(
        {"digests": [{"id": 0, "summary": "new"}]}
    )
    ctx = make_step_ctx(
        tmp_path,
        supervisor=FakeSupervisor(hint="補齊遺漏"),
        judge_llm=FakeLLM(
            responses=[_judge_json(2, ["https://example.com/new"]), _judge_json(4)]
        ),
        llm=FakeLLM(responses=[new_digest_resp]),
    )
    result = reconcile_completeness(ctx, _COMPRESS, old_digests, {})
    # digest 被重生：回傳的是新 digest（含 example.com/new，由 compress 依 id 重建 url）
    assert any("example.com/new" in d.get("url", "") for d in result)
    # judge 跑了兩次（初評 + 重評）
    assert ctx.judge_llm.prompts and len(ctx.judge_llm.prompts) == 2


def test_reconcile_skips_when_digest_forced(tmp_path):
    """digest 在 force_steps（使用者明示重跑）→ 不校正，避免與使用者意圖打架。"""
    digests = [{"url": "https://example.com/a", "summary": "a"}]
    ctx = make_step_ctx(
        tmp_path,
        force_steps={"digest"},
        supervisor=FakeSupervisor(forbid_reflect=True),
        judge_llm=FakeLLM(responses=[_judge_json(1, ["https://example.com/x"])]),
    )
    result = reconcile_completeness(ctx, _COMPRESS, digests, {})
    assert result == digests
