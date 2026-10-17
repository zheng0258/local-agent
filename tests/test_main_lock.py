"""main.py — /daily-brief 取不到單一寫入者鎖時，不碰模型、以非零碼退出。"""

import sys

import pytest

import main
from agents.daily_brief import run_lock
from agents.daily_brief.run_lock import single_writer

pytestmark = pytest.mark.unit


class _FakeLLM:
    def complete(self, prompt, system=""):  # pragma: no cover - 不應被呼叫
        raise AssertionError("不應呼叫 LLM")


@pytest.fixture
def lock_path(tmp_path, monkeypatch):
    path = tmp_path / ".run.lock"
    monkeypatch.setattr(run_lock, "LOCK_FILE", path)
    monkeypatch.setattr(main, "get_llm", lambda: _FakeLLM())
    return path


def test_exits_nonzero_when_pipeline_already_running(lock_path, monkeypatch):
    touched = []
    monkeypatch.setattr(main, "ensure_llm_ready", lambda: touched.append("ready") or True)
    monkeypatch.setattr(main, "unload_all", lambda: touched.append("unload"))
    monkeypatch.setattr(sys, "argv", ["main.py", "/daily-brief"])

    with single_writer(lock_path):
        with pytest.raises(SystemExit) as exc:
            main.main()

    assert exc.value.code == main.EXIT_ALREADY_RUNNING != 0
    # 不得喚醒 / 卸載模型——unload_all 會把正在跑的那條 pipeline 的模型踢掉
    assert touched == []


def test_readonly_health_not_blocked_by_lock(lock_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "/daily-brief --health"])
    monkeypatch.setattr(
        main.DailyBriefAgent, "run", lambda self, args: "health-table"
    )

    with single_writer(lock_path):
        main.main()  # 唯讀短路不取鎖，不應退出

    assert "health-table" in capsys.readouterr().out


def test_runs_pipeline_under_lock(lock_path, monkeypatch):
    seen = {}

    def fake_run(self, args):
        # 執行期間鎖被持有：另一個寫入者取不到
        with pytest.raises(run_lock.PipelineAlreadyRunning):
            with single_writer(lock_path):
                pass
        seen["ran"] = True
        return "ok"

    monkeypatch.setattr(main, "ensure_llm_ready", lambda: True)
    monkeypatch.setattr(main, "ensure_models_loaded", lambda models: None)
    monkeypatch.setattr(main, "unload_all", lambda: None)
    monkeypatch.setattr(main.DailyBriefAgent, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["main.py", "/daily-brief"])

    main.main()

    assert seen == {"ran": True}
    with single_writer(lock_path):  # 結束後已釋放
        pass
