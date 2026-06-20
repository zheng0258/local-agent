"""CompressStep — wraps _run_compress + _check_source_health behind Step.run()."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.compress import CompressStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn())


def _ctx(tmp_path):
    return SimpleNamespace(
        steps_dir=tmp_path,
        day_dir=tmp_path,
        steps_to_run={"compress"},
        force_steps=set(),
        supervisor=_FakeSupervisor(),
    )


@pytest.mark.unit
def test_compress_step_runs_producer_and_persists(tmp_path):
    captured = {}

    def fake_run_compress(source_data, reflect_context=""):
        captured["source"] = source_data
        captured["reflect"] = reflect_context
        return {"hn": {"themes": ["t"], "articles": []}}

    def fake_health(compress_data):
        captured["health"] = compress_data

    step = CompressStep(run_compress=fake_run_compress, check_health=fake_health)
    outcome = step.run(_ctx(tmp_path), {"hn": {"articles": [{"interest": "***"}]}})

    assert outcome.status is StepStatus.RAN
    assert outcome.value == {"hn": {"themes": ["t"], "articles": []}}
    assert captured["source"] == {"hn": {"articles": [{"interest": "***"}]}}
    assert captured["health"] == outcome.value          # health 收到產出
    assert JsonCodec().read(tmp_path / "compress.json") == outcome.value


@pytest.mark.unit
def test_compress_step_artifact_path(tmp_path):
    step = CompressStep(run_compress=lambda *a, **k: {}, check_health=lambda d: None)
    assert step.artifact_path(SimpleNamespace(steps_dir=tmp_path)) == tmp_path / "compress.json"


@pytest.mark.unit
def test_compress_step_default_is_empty_dict(tmp_path):
    step = CompressStep(run_compress=lambda *a, **k: {}, check_health=lambda d: None)
    ctx = SimpleNamespace(steps_dir=tmp_path, steps_to_run=set(), force_steps=set(),
                          supervisor=_FakeSupervisor())
    outcome = step.run(ctx, {"hn": {}})   # 不在 steps_to_run、無 artifact → SKIP
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value == {}
