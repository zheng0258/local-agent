"""DeployStep — SentinelCodec(deploy.done), guards on today's report.md.

對照 test_save_step.py / test_notify_step.py：fake supervisor + fake builder +
fake pusher，斷言 gating 與 sentinel，不碰真 git。
"""

from types import SimpleNamespace

import pytest

from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.deploy import DeployStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn())


class _FailingSupervisor:
    """模擬 supervisor：producer 拋例外 → success=False（重試耗盡行為）。"""

    def run_step(self, name, fn, force=False):
        try:
            return SimpleNamespace(success=True, output=fn())
        except Exception:
            return SimpleNamespace(success=False, output=None)


def _ctx(tmp_path, steps_to_run={"deploy"}, force=set()):
    return SimpleNamespace(
        steps_dir=tmp_path,
        day_dir=tmp_path,
        steps_to_run=steps_to_run,
        force_steps=force,
        supervisor=_FakeSupervisor(),
    )


def _fake_build():
    # 零參 thunk：內部已封裝「讀全部歷史天 → build_site_archive」全量重建。
    return {
        "index.html": "<html>index</html>",
        "archive/2026-06-25.html": "<html>25</html>",
        "archive/2026-06-24.html": "<html>24</html>",
    }


@pytest.mark.unit
def test_deploy_step_runs_builds_pushes_and_touches_sentinel(tmp_path):
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")
    pushed = {}

    def fake_push(build_dir):
        # push 在 build 目錄仍存活時被呼叫；當下檢查全量站台產出已落盤
        from pathlib import Path

        pushed["had_index"] = (Path(build_dir) / "index.html").exists()
        # 全量重建：存檔頁也應隨整站一起落盤
        pushed["had_archive"] = (
            Path(build_dir) / "archive" / "2026-06-25.html"
        ).exists()
        pushed["called"] = True

    outcome = DeployStep(build=_fake_build, push=fake_push, today="2026-06-25").run(
        _ctx(tmp_path), input=None
    )

    assert outcome.status is StepStatus.RAN
    assert (tmp_path / "deploy.done").exists()
    assert pushed["called"] is True
    assert pushed["had_index"] is True
    assert pushed["had_archive"] is True


@pytest.mark.unit
def test_deploy_step_guard_blocks_without_report_md(tmp_path):
    pushed = {"n": 0}

    def fake_push(build_dir):
        pushed["n"] += 1

    outcome = DeployStep(build=_fake_build, push=fake_push, today="2026-06-25").run(
        _ctx(tmp_path), input=None
    )

    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "deploy.done").exists()
    assert pushed["n"] == 0


@pytest.mark.unit
def test_deploy_step_loads_when_sentinel_exists(tmp_path):
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")
    (tmp_path / "deploy.done").touch()
    pushed = {"n": 0}

    def fake_push(build_dir):
        pushed["n"] += 1

    outcome = DeployStep(build=_fake_build, push=fake_push, today="2026-06-25").run(
        _ctx(tmp_path), input=None
    )

    assert outcome.status is StepStatus.LOADED
    assert pushed["n"] == 0


@pytest.mark.unit
def test_deploy_step_force_reruns_and_pushes(tmp_path):
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")
    (tmp_path / "deploy.done").touch()
    pushed = {"n": 0}

    def fake_push(build_dir):
        pushed["n"] += 1

    ctx = _ctx(tmp_path, steps_to_run={"deploy"}, force={"deploy"})
    outcome = DeployStep(build=_fake_build, push=fake_push, today="2026-06-25").run(
        ctx, input=None
    )

    assert outcome.status is StepStatus.RAN
    assert pushed["n"] == 1


@pytest.mark.unit
def test_run_deploy_push_resolves_repo_root_without_nameerror(tmp_path, monkeypatch):
    """迴歸：真正注入給 DeployStep 的 push callable 是 agent._run_deploy_push，
    其 repo_root 必須引用已定義名稱（曾誤用未 import 的 _PROJECT_ROOT → NameError）。
    git 子程序全 mock，只驗證走到 git 流程而非 NameError。"""
    from pathlib import Path

    from agents.daily_brief.agent import DailyBriefAgent

    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        # 模擬 `git worktree add ... <worktree>`：建出 worktree 目錄讓後續 iterdir 成立
        if "worktree" in cmd and "add" in cmd:
            for tok in cmd:
                if "gh-pages-wt-" in str(tok) and str(tok).endswith("wt"):
                    Path(tok).mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    agent = DailyBriefAgent(llm=object(), judge_llm=object())
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "index.html").write_text("<html></html>", encoding="utf-8")

    agent._run_deploy_push(build_dir)  # 不應拋 NameError

    assert any("worktree" in c and "add" in c for c in calls)
    assert any("push" in c for c in calls)


@pytest.mark.unit
def test_deploy_step_push_failure_fails_without_sentinel(tmp_path):
    # AC6：push 失敗沿用 Step FAILED 行為（不寫 sentinel，不 block 其他遞送）
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")

    def failing_push(build_dir):
        raise RuntimeError("git push 失敗")

    ctx = _ctx(tmp_path)
    ctx.supervisor = _FailingSupervisor()
    outcome = DeployStep(build=_fake_build, push=failing_push, today="2026-06-25").run(
        ctx, input=None
    )

    assert outcome.status is StepStatus.FAILED
    assert not (tmp_path / "deploy.done").exists()
