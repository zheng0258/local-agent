"""DedupStep — _load re-filters by kept_urls; _default passes through; _produce persists artifact."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.dedup import DedupStep
from tests.fakes import make_step_ctx


def _ctx(tmp_path, steps_to_run={"dedup"}, force=set()):
    return make_step_ctx(tmp_path, steps_to_run=steps_to_run, force_steps=force)


_SRC = {
    "hn": {"articles": [
        {"url": "http://keep", "title": "k"},
        {"url": "http://drop", "title": "d"},
    ]},
}


@pytest.mark.unit
def test_dedup_step_load_refilters_by_kept_urls(tmp_path):
    JsonCodec().write(tmp_path / "dedup.json", {"kept_urls": ["http://keep"]})
    outcome = DedupStep().run(_ctx(tmp_path), _SRC)
    assert outcome.status is StepStatus.LOADED
    urls = [a["url"] for a in outcome.value["hn"]["articles"]]
    assert urls == ["http://keep"]


@pytest.mark.unit
def test_dedup_step_default_passes_input_through(tmp_path):
    outcome = DedupStep().run(_ctx(tmp_path, steps_to_run=set()), _SRC)
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is _SRC


@pytest.mark.unit
def test_dedup_step_produce_persists_artifact_and_passes_filtered(tmp_path):
    filtered = {"hn": {"articles": [{"url": "http://keep", "title": "k"}]}}
    result = SimpleNamespace(total=2, kept=1, filtered_url=0, filtered_semantic=1,
                             kept_urls=["http://keep"], filtered_items=[])

    with patch("agents.daily_brief.steps.dedup.dedup_source_data",
               return_value=(filtered, result)), \
         patch("agents.daily_brief.steps.dedup.get_collection"), \
         patch("agents.daily_brief.steps.dedup.cleanup_old_records"), \
         patch("agents.daily_brief.steps.dedup.Qwen3Embedder"):
        outcome = DedupStep().run(_ctx(tmp_path), _SRC)

    assert outcome.status is StepStatus.RAN
    assert outcome.value == filtered
    saved = JsonCodec().read(tmp_path / "dedup.json")
    assert saved["kept_urls"] == ["http://keep"]
    assert saved["kept"] == 1 and saved["total"] == 2
