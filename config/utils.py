from __future__ import annotations

import json
import os
import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


def load_project_env() -> None:
    """從專案根目錄 .env 載入環境變數（已存在的變數不覆蓋，支援 inline comment）。"""
    if not _ENV_FILE.exists():
        return
    with _ENV_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.split(" #")[0].strip()
            os.environ.setdefault(k.strip(), v)


def parse_llm_json(raw: str | None) -> dict:
    """Parse JSON from LLM output with fence stripping and repair fallback."""
    if not isinstance(raw, str):
        raw = str(raw)

    def _strip_fence(s: str) -> str:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
        text = m.group(1) if m else s
        return re.sub(r"^\s*json\s*\n", "", text, count=1, flags=re.IGNORECASE)

    text = _strip_fence(raw)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    try:
        from json_repair import repair_json

        repaired = json.loads(repair_json(text))
        if isinstance(repaired, dict):
            return repaired
    except Exception:
        pass

    raise ValueError(
        f"parse_llm_json: LLM 回傳無法解析為 JSON dict（前 120 字元）: {raw[:120]!r}"
    )
