"""TldrStep — wraps _run_tldr; persist a plain-text English TL;DR as JSON.

對照 test_digest_step.py / test_judge_step.py：fake supervisor 直接執行 fn，
SimpleNamespace ctx 提供 steps_dir / day_dir / steps_to_run / force_steps / supervisor。
"""

from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.tldr import TldrStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn(reflect_context=""))


def _ctx(tmp_path, steps_to_run={"tldr"}, force=set()):
    return SimpleNamespace(
        steps_dir=tmp_path,
        day_dir=tmp_path,
        steps_to_run=steps_to_run,
        force_steps=force,
        supervisor=_FakeSupervisor(),
    )


@pytest.mark.unit
def test_tldr_step_persists_and_passes_text(tmp_path):
    digests = [{"title": "A", "url": "http://a", "summary": "s"}]

    def fake_run_tldr(digests_arg, reflect_context=""):
        return "Today AI tooling moved fast."

    outcome = TldrStep(fake_run_tldr).run(_ctx(tmp_path), digests)

    assert outcome.status is StepStatus.RAN
    assert outcome.value == "Today AI tooling moved fast."
    assert JsonCodec().read(tmp_path / "tldr.json") == {
        "tldr": "Today AI tooling moved fast."
    }


@pytest.mark.unit
def test_tldr_step_load_returns_tldr_field(tmp_path):
    JsonCodec().write(tmp_path / "tldr.json", {"tldr": "Cached TL;DR."})
    outcome = TldrStep(lambda *a, **k: "ignored").run(_ctx(tmp_path), [{"title": "X"}])
    assert outcome.status is StepStatus.LOADED
    assert outcome.value == "Cached TL;DR."


@pytest.mark.unit
def test_tldr_step_guard_blocks_without_digests(tmp_path):
    outcome = TldrStep(lambda *a, **k: "x").run(_ctx(tmp_path), [])
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None
    assert not (tmp_path / "tldr.json").exists()


@pytest.mark.unit
def test_tldr_step_default_is_none_when_not_in_steps(tmp_path):
    outcome = TldrStep(lambda *a, **k: "x").run(
        _ctx(tmp_path, steps_to_run=set()), [{"title": "X"}]
    )
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None
