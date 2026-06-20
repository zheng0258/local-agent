"""ArtifactCodec — 一個 step 主 artifact 的格式/定位 seam（笨的格式轉換，不懂意義）。

typed view（解讀成 SourceCompress / Digest 等）不住這裡，住各 step 的 _load。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class ArtifactCodec(Protocol):
    def exists(self, path: Path) -> bool: ...
    def write(self, path: Path, obj: Any) -> None: ...
    def read(self, path: Path) -> Any: ...


class JsonCodec:
    """dict/list ↔ JSON 檔（UTF-8、不轉義、indent=2）。多數 step 用。"""

    def exists(self, path: Path) -> bool:
        return path.exists()

    def write(self, path: Path, obj: Any) -> None:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    def read(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))


class TextCodec:
    """純文字 ↔ 檔（report.md 用）。"""

    def exists(self, path: Path) -> bool:
        return path.exists()

    def write(self, path: Path, obj: Any) -> None:
        path.write_text(str(obj), encoding="utf-8")

    def read(self, path: Path) -> Any:
        return path.read_text(encoding="utf-8")


class SentinelCodec:
    """完成旗標（vault.done / telegram.done）。write=touch、read=None。"""

    def exists(self, path: Path) -> bool:
        return path.exists()

    def write(self, path: Path, obj: Any) -> None:
        path.touch()

    def read(self, path: Path) -> Any:
        return None
