"""_compute_force_steps — folds Fix C stale-detection into force-step computation."""

import json
import time
from pathlib import Path

import pytest

from agents.daily_brief.agent import _compute_force_steps, FETCH_STEPS


def _write(p: Path, mtime: float | None = None):
    p.write_text(json.dumps({"x": 1}), encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(p, (mtime, mtime))


@pytest.mark.unit
def test_compute_force_steps_returns_explicit_force_when_only_mode(tmp_path):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    result = _compute_force_steps({"hn"}, {"compress"}, steps_dir, tmp_path)
    assert result == {"compress"}


@pytest.mark.unit
def test_compute_force_steps_adds_stale_downstream(tmp_path):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    _write(steps_dir / "compress.json", mtime=time.time() - 100)
    _write(steps_dir / "hn.json", mtime=time.time())
    result = _compute_force_steps(set(), set(), steps_dir, tmp_path)
    assert "compress" in result


@pytest.mark.unit
def test_compute_force_steps_no_change_when_fresh(tmp_path):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    _write(steps_dir / "hn.json", mtime=time.time() - 100)
    _write(steps_dir / "compress.json", mtime=time.time())
    result = _compute_force_steps(set(), {"notify"}, steps_dir, tmp_path)
    assert result == {"notify"}
