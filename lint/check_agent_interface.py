"""
檢查所有 agent 是否符合標準介面。

執行：python lint/check_agent_interface.py
CI 中：python lint/check_agent_interface.py && echo "OK"
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

AGENTS_DIR = Path(__file__).parent.parent / "agents"
REQUIRED_ATTRS = ["AGENT_NAME", "run"]
SKIP = {"_template"}


def check() -> list[str]:
    errors: list[str] = []

    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name in SKIP:
            continue

        module_path = f"agents.{agent_dir.name}.agent"
        try:
            mod = importlib.import_module(module_path)
        except ImportError as e:
            errors.append(f"[{agent_dir.name}] agent.py import 失敗：{e}")
            continue

        # 找出 Agent 類別（名稱含 Agent）
        agent_cls = next(
            (
                getattr(mod, name)
                for name in dir(mod)
                if name.endswith("Agent") and not name.startswith("_")
            ),
            None,
        )

        if agent_cls is None:
            errors.append(f"[{agent_dir.name}] 找不到 *Agent 類別")
            continue

        for attr in REQUIRED_ATTRS:
            if not hasattr(agent_cls, attr):
                errors.append(f"[{agent_dir.name}] {agent_cls.__name__} 缺少 {attr!r}")

    return errors


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))
    errors = check()
    if errors:
        print("❌ Agent 介面檢查失敗：")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("✅ 所有 agent 介面檢查通過")
