"""run_lock — pipeline 的單一寫入者鎖（L0）。

outputs/daily-brief/ 下的 artifact、歷史檔與 LM Studio 都假設同一時間只有一條
pipeline 在寫。2026-10-04、10-17 各一次：舊 launchd runner 與 02:00 cron 並行，
兩條同時壓 LM Studio 致 rss 逾時、compress HTTP 500、模型崩潰卸載——因為沒有鎖。

`fcntl.flock` 非阻塞排他鎖：鎖綁在 open file description 上，持有行程結束（含
crash / kill -9）時由核心自動釋放，不會留下需要人工清除的殘鎖（pidfile 方案的通病）。
鎖檔內容寫持有者 pid，僅供診斷；判定只看 flock。
"""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import OUTPUT_DIR

LOCK_FILE = OUTPUT_DIR / ".run.lock"


class PipelineAlreadyRunning(RuntimeError):
    """已有另一條 pipeline 持有單一寫入者鎖。"""


def _holder_pid(fh) -> str:
    try:
        fh.seek(0)
        return fh.read().strip() or "?"
    except OSError:
        return "?"


@contextmanager
def single_writer(lock_path: Path | None = None) -> Iterator[None]:
    """取得單一寫入者鎖；取不到立即拋 PipelineAlreadyRunning（不等待）。

    lock_path 未給時於呼叫當下解析模組層 LOCK_FILE（測試可 monkeypatch）。
    """
    path = Path(lock_path) if lock_path is not None else LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    # a+：不截斷既有內容，取鎖失敗時才讀得到持有者 pid
    fh = open(path, "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PipelineAlreadyRunning(
                f"已有 pipeline 執行中（pid {_holder_pid(fh)}，鎖檔 {path}）"
            ) from None
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()
