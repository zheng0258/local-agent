"""tools/usage_meter.py 單元測試：帳本累加、歸屬、roll-up、歷史 idempotent。"""

from __future__ import annotations

import json

from tools import usage_meter as um


def _meter_with(events):
    """建 meter 並依 (step, model, usage) 序列 record。"""
    meter = um.UsageMeter()
    for step, model, usage in events:
        meter.current_step = step
        meter.record(model, usage)
    return meter


def test_record_attributes_to_current_step():
    meter = _meter_with(
        [
            ("hn", "qwen", {"prompt_tokens": 100, "completion_tokens": 20}),
            ("digest", "qwen", {"prompt_tokens": 200, "completion_tokens": 80}),
        ]
    )
    steps = um.by_step(meter.events)
    assert steps["hn"]["total_tokens"] == 120
    assert steps["digest"]["total_tokens"] == 280
    assert steps["hn"]["calls"] == 1


def test_total_tokens_fallback_from_prompt_plus_completion():
    meter = _meter_with(
        [("hn", "qwen", {"prompt_tokens": 30, "completion_tokens": 12})]
    )
    assert um.totals(meter.events)["total_tokens"] == 42


def test_explicit_total_tokens_is_respected():
    meter = _meter_with(
        [
            (
                "hn",
                "qwen",
                {"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 45},
            )
        ]
    )
    assert um.totals(meter.events)["total_tokens"] == 45


def test_missing_or_zero_usage_is_skipped():
    meter = um.UsageMeter()
    meter.current_step = "hn"
    meter.record("qwen", None)
    meter.record("qwen", {})
    meter.record("qwen", {"prompt_tokens": 0, "completion_tokens": 0})
    assert meter.events == ()
    assert um.totals(meter.events)["calls"] == 0


def test_empty_current_step_falls_back_to_other():
    meter = um.UsageMeter()
    meter.record("qwen", {"prompt_tokens": 5, "completion_tokens": 5})
    assert um.by_step(meter.events)["other"]["total_tokens"] == 10


def test_by_model_splits_main_and_judge():
    meter = _meter_with(
        [
            ("digest", "qwen-27b", {"prompt_tokens": 100, "completion_tokens": 50}),
            ("judge", "qwen-35b", {"prompt_tokens": 40, "completion_tokens": 10}),
        ]
    )
    models = um.by_model(meter.events)
    assert models["qwen-27b"]["total_tokens"] == 150
    assert models["qwen-35b"]["total_tokens"] == 50


def test_summarize_shape():
    meter = _meter_with([("hn", "qwen", {"prompt_tokens": 10, "completion_tokens": 5})])
    summary = um.summarize(meter, "2026-09-18")
    assert summary["date"] == "2026-09-18"
    assert summary["totals"]["total_tokens"] == 15
    assert "hn" in summary["by_step"]
    assert "qwen" in summary["by_model"]


def test_append_history_is_idempotent_per_day(tmp_path):
    hist = tmp_path / "_usage-history.json"
    meter = _meter_with([("hn", "qwen", {"prompt_tokens": 10, "completion_tokens": 5})])
    um.append_history(hist, um.summarize(meter, "2026-09-18"))
    # 同日重跑：更大用量應覆寫，不重複列
    meter2 = _meter_with(
        [("hn", "qwen", {"prompt_tokens": 100, "completion_tokens": 50})]
    )
    um.append_history(hist, um.summarize(meter2, "2026-09-18"))
    records = json.loads(hist.read_text(encoding="utf-8"))
    assert len(records) == 1
    assert records[0]["total_tokens"] == 150


def test_append_history_keeps_multiple_days_sorted(tmp_path):
    hist = tmp_path / "_usage-history.json"
    m = _meter_with([("hn", "qwen", {"prompt_tokens": 10, "completion_tokens": 0})])
    um.append_history(hist, um.summarize(m, "2026-09-18"))
    um.append_history(hist, um.summarize(m, "2026-09-17"))
    records = json.loads(hist.read_text(encoding="utf-8"))
    assert [r["date"] for r in records] == ["2026-09-17", "2026-09-18"]


def test_render_table_handles_empty():
    assert "尚無歷史" in um.render_usage_table([])


def test_render_table_shows_average_and_steps():
    records = [
        {
            "date": "2026-09-17",
            "calls": 10,
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
        },
        {
            "date": "2026-09-18",
            "calls": 12,
            "prompt_tokens": 2000,
            "completion_tokens": 500,
            "total_tokens": 2500,
        },
    ]
    today = {
        "date": "2026-09-18",
        "by_step": {"digest": {"calls": 1, "total_tokens": 800}},
    }
    out = um.render_usage_table(records, today)
    assert "平均/天：2,000" in out
    assert "digest" in out
