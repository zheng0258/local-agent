"""DigestStep — wraps _run_digest; persist≠value (persist digest_data, pass digests)."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.digest import DigestStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn(reflect_context=""))


def _ctx(tmp_path, steps_to_run={"digest"}, force=set()):
    return SimpleNamespace(steps_dir=tmp_path, day_dir=tmp_path,
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_FakeSupervisor())


@pytest.mark.unit
def test_digest_step_persists_digest_data_passes_digests(tmp_path):
    digests = [{"title": "A", "url": "http://a", "_source": "hn"}]
    digest_data = {"generated_at": "t", "digests": digests}

    def fake_run_digest(compress_data, reflect_context=""):
        return digests, digest_data

    outcome = DigestStep(fake_run_digest).run(_ctx(tmp_path), {"hn": {"articles": [1]}})

    assert outcome.status is StepStatus.RAN
    assert outcome.value == digests
    assert JsonCodec().read(tmp_path / "digest.json") == digest_data


@pytest.mark.unit
def test_digest_step_load_returns_digests_field(tmp_path):
    digests = [{"title": "X", "url": "http://x"}]
    JsonCodec().write(tmp_path / "digest.json", {"generated_at": "t", "digests": digests})
    outcome = DigestStep(lambda *a, **k: ([], {})).run(_ctx(tmp_path), {"hn": {}})
    assert outcome.status is StepStatus.LOADED
    assert outcome.value == digests


@pytest.mark.unit
def test_digest_step_default_is_empty_list(tmp_path):
    outcome = DigestStep(lambda *a, **k: ([], {})).run(
        _ctx(tmp_path, steps_to_run=set()), {"hn": {}})
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value == []
