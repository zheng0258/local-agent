"""部分重跑的合併語義測試（計畫項目 1）。"""

import pytest


def _full_run_manifest() -> dict:
    return {
        "date": "2026-09-23",
        "trigger": "scheduled",
        "git_sha": "f60492d",
        "started_at": "2026-09-23T02:00:01",
        "ended_at": "2026-09-23T05:07:18",
        "duration_seconds": 11236.933,
        "steps": {
            "hatena": {"status": "ran", "duration_seconds": 781.8},
            "judge": {"status": "ran", "duration_seconds": 126.2},
            "deploy": {"status": "ran", "duration_seconds": 5.5},
        },
    }


def _only_judge_manifest() -> dict:
    return {
        "date": "2026-09-23",
        "trigger": "manual",
        "git_sha": "abc1234",
        "started_at": "2026-09-23T09:30:00",
        "ended_at": "2026-09-23T09:32:00",
        "duration_seconds": 120.0,
        "steps": {
            "hatena": {"status": "skipped", "duration_seconds": 0.0},
            "judge": {"status": "ran", "duration_seconds": 131.4},
            "deploy": {"status": "skipped", "duration_seconds": 0.0},
        },
    }


@pytest.mark.unit
def test_run_merge_partial_patches_only_ran_steps():
    from agents.daily_brief.run_manifest import merge_summary

    merged = merge_summary(_full_run_manifest(), _only_judge_manifest(), partial=True)

    # 沒跑到的步驟沿用完整 run 的紀錄
    assert merged["steps"]["hatena"] == {"status": "ran", "duration_seconds": 781.8}
    assert merged["steps"]["deploy"] == {"status": "ran", "duration_seconds": 5.5}
    # 實際重跑的步驟更新
    assert merged["steps"]["judge"] == {"status": "ran", "duration_seconds": 131.4}
    # 頂層維持首次完整 run 的數字
    assert merged["duration_seconds"] == 11236.933
    assert merged["trigger"] == "scheduled"
    assert merged["started_at"] == "2026-09-23T02:00:01"
    assert merged["git_sha"] == "f60492d"


@pytest.mark.unit
def test_run_merge_full_run_overwrites():
    from agents.daily_brief.run_manifest import merge_summary

    fresh = _full_run_manifest()
    merged = merge_summary(_only_judge_manifest(), fresh, partial=False)
    assert merged == fresh


@pytest.mark.unit
def test_run_merge_without_existing_returns_fresh():
    from agents.daily_brief.run_manifest import merge_summary

    fresh = _only_judge_manifest()
    assert merge_summary(None, fresh, partial=True) == fresh


@pytest.mark.unit
def test_usage_merge_partial_recomputes_totals():
    from tools.usage_meter import merge_summary

    existing = {
        "date": "2026-09-23",
        "totals": {"calls": 3, "prompt_tokens": 30, "completion_tokens": 60, "total_tokens": 90},
        "by_step": {
            "hatena": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "judge": {"calls": 2, "prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60},
        },
        "by_model": {
            "main": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "judge-m": {"calls": 2, "prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60},
        },
    }
    fresh = {
        "date": "2026-09-23",
        "totals": {"calls": 1, "prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        "by_step": {
            "judge": {"calls": 1, "prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        },
        "by_model": {
            "judge-m": {"calls": 1, "prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        },
    }

    merged = merge_summary(existing, fresh, partial=True)

    # 沒跑到的步驟沿用
    assert merged["by_step"]["hatena"] == existing["by_step"]["hatena"]
    # 重跑的步驟被取代（非累加）
    assert merged["by_step"]["judge"] == fresh["by_step"]["judge"]
    # totals 由合併後 by_step 重算：hatena 30 + judge 12 = 42
    assert merged["totals"]["total_tokens"] == 42
    assert merged["totals"]["calls"] == 2


@pytest.mark.unit
def test_usage_merge_full_run_overwrites():
    from tools.usage_meter import merge_summary

    fresh = {
        "date": "2026-09-23",
        "totals": {"calls": 1, "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "by_step": {"judge": {"calls": 1, "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
        "by_model": {"m": {"calls": 1, "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
    }
    assert merge_summary({"date": "x", "by_step": {"old": {}}}, fresh, partial=False) == fresh


@pytest.mark.unit
def test_persist_observations_partial_preserves_full_run_record(tmp_path, monkeypatch):
    """端到端：完整 run 落盤後，模擬 --only judge 重跑，當日紀錄不得被抹成殘缺版。

    這是 2026-09-23 實際踩到的情境——`--only deploy` 會把 16 步 / 236K tokens /
    11,236 秒蓋成只剩一步。
    """
    import json

    from agents.daily_brief import agent as agent_mod
    from agents.daily_brief import health
    from agents.daily_brief.run_manifest import RunManifest
    from tools.usage_meter import UsageMeter, UsageEvent

    day_dir = tmp_path / "2026-09-23"
    steps_dir = day_dir / "steps"
    steps_dir.mkdir(parents=True)
    (day_dir / "telegram.done").touch()

    monkeypatch.setattr(agent_mod, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(health, "HEALTH_HISTORY_FILE", tmp_path / "_health-history.json")
    monkeypatch.setattr(health, "ESCALATION_STATE_FILE", tmp_path / "_health-escalated.json")

    def _persist(meter, manifest, partial):
        agent_mod._persist_observations(
            "2026-09-23", day_dir, steps_dir, meter, manifest, lambda _m: True, partial
        )

    # 完整 run：三步 + 用量
    full_meter = UsageMeter()
    full_meter.current_step = "hatena"
    full_meter.record("main", {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30})
    full_meter.current_step = "judge"
    full_meter.record("judge-m", {"prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60})
    full_manifest = RunManifest(trigger="scheduled", sha="f60492d")
    full_manifest.record_step("hatena", "ran", 781.8)
    full_manifest.record_step("judge", "ran", 126.2)
    full_manifest.record_step("deploy", "ran", 5.5)
    _persist(full_meter, full_manifest, partial=False)

    full_run = json.loads((steps_dir / "_run.json").read_text(encoding="utf-8"))
    full_duration = full_run["duration_seconds"]

    # --only judge 重跑：其餘步驟記成 skipped、用量只有 judge
    rerun_meter = UsageMeter()
    rerun_meter.current_step = "judge"
    rerun_meter.record("judge-m", {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12})
    rerun_manifest = RunManifest(trigger="manual", sha="abc1234")
    rerun_manifest.record_step("hatena", "skipped", 0.0)
    rerun_manifest.record_step("judge", "ran", 131.4)
    rerun_manifest.record_step("deploy", "skipped", 0.0)
    _persist(rerun_meter, rerun_manifest, partial=True)

    run_doc = json.loads((steps_dir / "_run.json").read_text(encoding="utf-8"))
    usage_doc = json.loads((steps_dir / "_usage.json").read_text(encoding="utf-8"))

    # 沒跑到的步驟完整存活
    assert run_doc["steps"]["hatena"]["status"] == "ran"
    assert run_doc["steps"]["deploy"]["duration_seconds"] == 5.5
    assert run_doc["steps"]["judge"]["duration_seconds"] == 131.4
    # 頂層維持首次完整 run
    assert run_doc["duration_seconds"] == full_duration
    assert run_doc["trigger"] == "scheduled"
    # 用量：hatena 沿用、judge 取代、totals 重算
    assert usage_doc["by_step"]["hatena"]["total_tokens"] == 30
    assert usage_doc["by_step"]["judge"]["total_tokens"] == 12
    assert usage_doc["totals"]["total_tokens"] == 42

    # 跨天歷史同樣只有一列且已合併
    run_hist = json.loads((tmp_path / "_run-history.json").read_text(encoding="utf-8"))
    assert len(run_hist) == 1
    assert run_hist[0]["steps"]["hatena"]["status"] == "ran"
