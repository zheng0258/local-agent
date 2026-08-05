"""
檢查所有 fetcher 是否實作 fetch() 函數。

執行：python lint/check_fetcher_interface.py
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

FETCHERS_DIR = Path(__file__).parent.parent / "tools" / "fetchers"
SKIP = {"_template", "__init__", "browser", "rss_common", "schema", "hn_comments", "reddit_comments"}


def check() -> list[str]:
    errors: list[str] = []

    for f in sorted(FETCHERS_DIR.glob("*.py")):
        name = f.stem
        if name in SKIP:
            continue

        module_path = f"tools.fetchers.{name}"
        try:
            mod = importlib.import_module(module_path)
        except ImportError as e:
            errors.append(f"[{name}] import 失敗：{e}")
            continue

        if not callable(getattr(mod, "fetch", None)):
            errors.append(f"[{name}] 缺少 fetch() 函數")

    return errors


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))
    errors = check()
    if errors:
        print("❌ Fetcher 介面檢查失敗：")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("✅ 所有 fetcher 介面檢查通過")
