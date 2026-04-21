from __future__ import annotations

import json
import re


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
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        from json_repair import repair_json

        repaired = json.loads(repair_json(text))
        if isinstance(repaired, dict):
            return repaired
    except Exception:
        pass

    return {"raw": raw}
