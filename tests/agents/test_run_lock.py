"""run_lock — pipeline 單一寫入者鎖（fcntl.flock 非阻塞排他）測試。"""

import subprocess
import sys
import textwrap

import pytest

from agents.daily_brief import run_lock
from agents.daily_brief.run_lock import PipelineAlreadyRunning, single_writer

pytestmark = pytest.mark.unit


def test_acquires_and_creates_lock_file(tmp_path):
    lock = tmp_path / "nested" / ".run.lock"
    with single_writer(lock):
        assert lock.exists()


def test_second_writer_is_rejected(tmp_path):
    lock = tmp_path / ".run.lock"
    with single_writer(lock):
        with pytest.raises(PipelineAlreadyRunning):
            with single_writer(lock):
                pass


def test_lock_released_after_exit(tmp_path):
    lock = tmp_path / ".run.lock"
    with single_writer(lock):
        pass
    with single_writer(lock):  # 不應拋
        pass


def test_lock_released_when_body_raises(tmp_path):
    lock = tmp_path / ".run.lock"
    with pytest.raises(ValueError):
        with single_writer(lock):
            raise ValueError("boom")
    with single_writer(lock):
        pass


def test_holder_pid_recorded(tmp_path):
    import os

    lock = tmp_path / ".run.lock"
    with single_writer(lock):
        assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_rejection_message_names_holder(tmp_path):
    import os

    lock = tmp_path / ".run.lock"
    with single_writer(lock):
        with pytest.raises(PipelineAlreadyRunning, match=str(os.getpid())):
            with single_writer(lock):
                pass


def test_default_path_resolved_at_call_time(tmp_path, monkeypatch):
    lock = tmp_path / ".run.lock"
    monkeypatch.setattr(run_lock, "LOCK_FILE", lock)
    with single_writer():
        assert lock.exists()


def test_other_process_holding_lock_blocks_us(tmp_path):
    """跨行程：另一支 pipeline（子行程）持鎖時，本行程取鎖失敗。"""
    lock = tmp_path / ".run.lock"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import fcntl, sys, time
                fh = open({str(lock)!r}, "a+")
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                print("locked", flush=True)
                sys.stdin.read()
                """
            ),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(PipelineAlreadyRunning):
            with single_writer(lock):
                pass
    finally:
        holder.stdin.close()
        holder.wait(timeout=10)
    with single_writer(lock):  # 對方結束後可取得
        pass
