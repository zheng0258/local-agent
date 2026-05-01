"""LM Studio model lifecycle management via lms CLI."""

from __future__ import annotations

import json
import logging
import subprocess

logger = logging.getLogger(__name__)

# 絕對路徑，確保在 Cowork sandbox 等無繼承 PATH 的環境也能找到 lms
LMS_BIN = "/Users/guangzhenglee/.cache/lm-studio/bin/lms"


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


def ensure_models_loaded(models: list[str]) -> None:
    """Load any models not currently in lms ps. Verifies after loading."""
    loaded = get_loaded_models()
    to_load = [m for m in models if m not in loaded]
    if not to_load:
        return

    for model in to_load:
        logger.info("Loading model: %s", model)
        max_ctx = _get_max_context(model)
        cmd = [LMS_BIN, "load", model, "-y"]
        if max_ctx:
            cmd += ["-c", str(max_ctx)]
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
