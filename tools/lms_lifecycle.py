"""LM Studio model lifecycle management via lms CLI."""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def get_loaded_models() -> set[str]:
    """Execute lms ps and return the set of loaded model identifiers."""
    try:
        result = subprocess.run(["lms", "ps"], capture_output=True, text=True)
    except FileNotFoundError:
        logger.warning("lms not found in PATH, skipping model check")
        return set()

    if result.returncode != 0:
        logger.warning("lms ps failed: %s", result.stderr)
        return set()

    loaded: set[str] = set()
    lines = result.stdout.strip().splitlines()
    for line in lines[1:]:  # skip header
        parts = line.split()
        if parts:
            loaded.add(parts[0])
    return loaded
