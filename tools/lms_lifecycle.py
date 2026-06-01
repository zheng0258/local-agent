"""LM Studio model lifecycle management via lms CLI."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

# 動態解析 lms 路徑，回退到已知絕對路徑
LMS_BIN = shutil.which("lms") or "/Applications/LM Studio.app/Contents/Resources/app/.webpack/lms"


def get_loaded_models() -> set[str]:
    """Execute lms ps and return the set of loaded model identifiers."""
    try:
        result = subprocess.run([LMS_BIN, "ps"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        logger.warning("lms not found in PATH, skipping model check")
        return set()
    except subprocess.TimeoutExpired:
        logger.warning("lms ps timed out")
        return set()

    if result.returncode != 0:
        logger.warning("lms ps failed: %s", result.stderr)
        return set()

    loaded: set[str] = set()
    lines = result.stdout.strip().splitlines()
    for line in lines[1:]:
        parts = line.split()
        if parts:
            loaded.add(parts[0])
    return loaded


def _get_max_context(model: str) -> int | None:
    """Query lms ls --json for the model's maxContextLength. Returns None on failure."""
    try:
        result = subprocess.run(
            [LMS_BIN, "ls", "--json"], capture_output=True, text=True, timeout=15
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        for entry in json.loads(result.stdout):
            if entry.get("modelKey") == model:
                return entry.get("maxContextLength")
    except (json.JSONDecodeError, AttributeError):
        pass
    return None


def ensure_models_loaded(models: list[str]) -> bool:
    """Load any models not currently in lms ps. Verifies after loading.

    Returns:
        True  — 至少一個模型是剛才才載入的（需等待 API 穩定）
        False — 所有模型先前已在 lms ps 中（無需額外等待）
    """
    loaded = get_loaded_models()
    to_load = [m for m in models if m not in loaded]
    if not to_load:
        return False

    for model in to_load:
        logger.info("Loading model: %s", model)
        max_ctx = _get_max_context(model)
        if not max_ctx:
            max_ctx = 32768  # fallback: lms ls 未回傳 maxContextLength 時，避免使用預設的 4096
            logger.warning("Loading model %s with fallback context %d (lms ls 未回傳 maxContextLength)", model, max_ctx)
        cmd = [LMS_BIN, "load", model, "-y", "-c", str(max_ctx)]
        logger.info("Loading model %s with context %d", model, max_ctx)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except FileNotFoundError:
            logger.warning("lms not found in PATH, cannot load model: %s", model)
            continue
        except subprocess.TimeoutExpired:
            logger.warning("lms load timed out for %s", model)
            continue
        if result.returncode != 0:
            logger.warning("lms load failed for %s: %s", model, result.stderr)

    final = get_loaded_models()
    for model in models:
        if model not in final:
            logger.warning("Model not present after load attempt: %s", model)
    return True


def unload_model(model: str) -> None:
    """Unload (eject) a single model from LM Studio. Failures are silently ignored."""
    try:
        result = subprocess.run(
            [LMS_BIN, "unload", model], capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            logger.warning("lms unload failed for %s: %s", model, result.stderr)
    except FileNotFoundError:
        logger.warning("lms not found in PATH, cannot unload model: %s", model)
    except subprocess.TimeoutExpired:
        logger.warning("lms unload timed out for %s", model)


def unload_all() -> None:
    """Unload all models from LM Studio. Failures are silently ignored."""
    try:
        subprocess.run([LMS_BIN, "unload", "--all"], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
