"""Step base class + value types."""

from pathlib import Path

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import Step, StepOutcome, StepOutput, StepStatus
from tests.fakes import FakeSupervisor, make_step_ctx


@pytest.mark.unit
def test_step_status_members():
    assert {s.name for s in StepStatus} == {"RAN", "LOADED", "SKIPPED", "FAILED"}


@pytest.mark.unit
def test_step_output_holds_persist_and_value():
    out = StepOutput(persist={"on": "disk"}, value=[1, 2, 3])
    assert out.persist == {"on": "disk"}
    assert out.value == [1, 2, 3]


@pytest.mark.unit
def test_step_outcome_holds_status_and_value():
    oc = StepOutcome(status=StepStatus.RAN, value={"k": 1})
    assert oc.status is StepStatus.RAN
    assert oc.value == {"k": 1}


class _DoublerStep(Step):
    """測試用最小 step：value = input * 2，persist = {'v': value}。"""

    name = "compress"  # 借用 STEP_CONFIGS 既有的鍵，避免 KeyError（fake supervisor 不查表）

    def __init__(self, artifact: Path):
        self._artifact = artifact

    def artifact_path(self, ctx):
        return self._artifact

    def _produce(self, ctx, input, reflect_context=""):
        value = input * 2
        return StepOutput(persist={"v": value}, value=value)


@pytest.mark.unit
def test_run_executes_and_persists_when_in_steps(tmp_path):
    art = tmp_path / "compress.json"
    sup = FakeSupervisor()
    ctx = make_step_ctx(tmp_path, steps_to_run={"compress"}, supervisor=sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.RAN
    assert outcome.value == 42
    assert JsonCodec().read(art) == {"v": 42}
    assert sup.calls == ["compress"]


@pytest.mark.unit
def test_run_loads_existing_artifact_without_supervisor(tmp_path):
    art = tmp_path / "compress.json"
    JsonCodec().write(art, {"v": 999})
    sup = FakeSupervisor()
    ctx = make_step_ctx(tmp_path, steps_to_run={"compress"}, supervisor=sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.LOADED
    assert outcome.value == {"v": 999}   # _load 預設 = identity（回 decoded）
    assert sup.calls == []


@pytest.mark.unit
def test_run_force_reruns_even_if_artifact_exists(tmp_path):
    art = tmp_path / "compress.json"
    JsonCodec().write(art, {"v": 999})
    sup = FakeSupervisor()
    ctx = make_step_ctx(tmp_path, steps_to_run={"compress"}, force_steps={"compress"}, supervisor=sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.RAN
    assert outcome.value == 42
    assert sup.calls == ["compress"]


@pytest.mark.unit
def test_run_skips_when_not_in_steps_and_no_artifact(tmp_path):
    art = tmp_path / "compress.json"
    sup = FakeSupervisor()
    ctx = make_step_ctx(tmp_path, steps_to_run=set(), supervisor=sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None         # 預設 _default 回 None
    assert sup.calls == []


@pytest.mark.unit
def test_run_guard_blocks_falsy_input(tmp_path):
    art = tmp_path / "compress.json"
    sup = FakeSupervisor()
    ctx = make_step_ctx(tmp_path, steps_to_run={"compress"}, supervisor=sup)
    outcome = _DoublerStep(art).run(ctx, 0)   # 0 → bool(input) False → guard 擋
    assert outcome.status is StepStatus.SKIPPED
    assert sup.calls == []


@pytest.mark.unit
def test_run_failed_returns_default(tmp_path):
    art = tmp_path / "compress.json"
    sup = FakeSupervisor(fail=frozenset({"compress"}))
    ctx = make_step_ctx(tmp_path, steps_to_run={"compress"}, supervisor=sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.FAILED
    assert outcome.value is None
    assert not art.exists()              # 失敗不落盤


@pytest.mark.unit
def test_run_force_param_forces_run_even_when_not_in_steps(tmp_path):
    art = tmp_path / "compress.json"
    JsonCodec().write(art, {"v": 999})
    sup = FakeSupervisor()
    ctx = make_step_ctx(tmp_path, steps_to_run=set(), supervisor=sup)
    outcome = _DoublerStep(art).run(ctx, 21, force=True)
    assert outcome.status is StepStatus.RAN
    assert outcome.value == 42
    assert sup.calls == ["compress"]


@pytest.mark.unit
def test_run_force_param_passed_to_supervisor(tmp_path):
    art = tmp_path / "compress.json"
    sup = FakeSupervisor()
    ctx = make_step_ctx(tmp_path, steps_to_run={"compress"}, supervisor=sup)
    _DoublerStep(art).run(ctx, 21, force=True)
    assert sup.forced == {"compress": True}
