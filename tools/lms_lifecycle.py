"""LM Studio model lifecycle management via lms CLI."""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def get_loaded_models() -> set[str]:
    """Execute lms ps and return the set of loaded model identifiers."""
    try:
        result = subprocess.run(["lms", "ps"], capture_output=True, text=True, timeout=10)
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


def ensure_models_loaded(models: list[str]) -> None:
    """Load any models not currently in lms ps. Verifies after loading."""
    loaded = get_loaded_models()
    to_load = [m for m in models if m not in loaded]
    if not to_load:
        return

    for model in to_load:
        logger.info("Loading model: %s", model)
        try:
            result = subprocess.run(
                ["lms", "load", model, "-y"],
                capture_output=True,
                text=True,
                timeout=300,
            )
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


def unload_all() -> None:
    """Unload all models from LM Studio. Failures are silently ignored."""
    try:
        subprocess.run(["lms", "unload", "--all"], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
