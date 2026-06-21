"""Step base class + value types."""

import pytest

from agents.daily_brief.step import StepOutcome, StepOutput, StepStatus


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


# --- append to tests/agents/test_step.py ---
from pathlib import Path
from types import SimpleNamespace

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import Step


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


class _FakeSupervisor:
    """run_step 直接呼叫 fn()（plain 慣例），記錄被呼叫次數。"""

    def __init__(self, succeed=True):
        self.succeed = succeed
        self.calls = 0

    def run_step(self, name, fn, force=False):
        self.calls += 1
        if not self.succeed:
            return SimpleNamespace(success=False, output=None)
        return SimpleNamespace(success=True, output=fn())


def _ctx(tmp_path, steps_to_run, force_steps, supervisor):
    return SimpleNamespace(
        steps_dir=tmp_path,
        day_dir=tmp_path,
        steps_to_run=steps_to_run,
        force_steps=force_steps,
        supervisor=supervisor,
    )


@pytest.mark.unit
def test_run_executes_and_persists_when_in_steps(tmp_path):
    art = tmp_path / "compress.json"
    sup = _FakeSupervisor()
    ctx = _ctx(tmp_path, {"compress"}, set(), sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.RAN
    assert outcome.value == 42
    assert JsonCodec().read(art) == {"v": 42}
    assert sup.calls == 1


@pytest.mark.unit
def test_run_loads_existing_artifact_without_supervisor(tmp_path):
    art = tmp_path / "compress.json"
    JsonCodec().write(art, {"v": 999})
    sup = _FakeSupervisor()
    ctx = _ctx(tmp_path, {"compress"}, set(), sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.LOADED
    assert outcome.value == {"v": 999}   # _load 預設 = identity（回 decoded）
    assert sup.calls == 0


@pytest.mark.unit
def test_run_force_reruns_even_if_artifact_exists(tmp_path):
    art = tmp_path / "compress.json"
    JsonCodec().write(art, {"v": 999})
    sup = _FakeSupervisor()
    ctx = _ctx(tmp_path, {"compress"}, {"compress"}, sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.RAN
    assert outcome.value == 42
    assert sup.calls == 1


@pytest.mark.unit
def test_run_skips_when_not_in_steps_and_no_artifact(tmp_path):
    art = tmp_path / "compress.json"
    sup = _FakeSupervisor()
    ctx = _ctx(tmp_path, set(), set(), sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None         # 預設 _default 回 None
    assert sup.calls == 0


@pytest.mark.unit
def test_run_guard_blocks_falsy_input(tmp_path):
    art = tmp_path / "compress.json"
    sup = _FakeSupervisor()
    ctx = _ctx(tmp_path, {"compress"}, set(), sup)
    outcome = _DoublerStep(art).run(ctx, 0)   # 0 → bool(input) False → guard 擋
    assert outcome.status is StepStatus.SKIPPED
    assert sup.calls == 0


@pytest.mark.unit
def test_run_failed_returns_default(tmp_path):
    art = tmp_path / "compress.json"
    sup = _FakeSupervisor(succeed=False)
    ctx = _ctx(tmp_path, {"compress"}, set(), sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.FAILED
    assert outcome.value is None
    assert not art.exists()              # 失敗不落盤


@pytest.mark.unit
def test_run_force_param_forces_run_even_when_not_in_steps(tmp_path):
    art = tmp_path / "compress.json"
    JsonCodec().write(art, {"v": 999})
    sup = _FakeSupervisor()
    ctx = _ctx(tmp_path, set(), set(), sup)
    outcome = _DoublerStep(art).run(ctx, 21, force=True)
    assert outcome.status is StepStatus.RAN
    assert outcome.value == 42
    assert sup.calls == 1


@pytest.mark.unit
def test_run_force_param_passed_to_supervisor(tmp_path):
    art = tmp_path / "compress.json"

    class _RecordingSupervisor:
        def __init__(self):
            self.forces = []

        def run_step(self, name, fn, force=False):
            self.forces.append(force)
            return SimpleNamespace(success=True, output=fn())

    sup = _RecordingSupervisor()
    ctx = _ctx(tmp_path, {"compress"}, set(), sup)
    _DoublerStep(art).run(ctx, 21, force=True)
    assert sup.forces == [True]
