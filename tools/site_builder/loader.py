"""load_days — 薄 loader（impure）：掃歷史輸出目錄 → 純記憶體語料串。

唯一碰檔案的歷史讀取點，與純核心 (build_site_archive) 解耦：把
`OUTPUT_DIR/<date>/report.md` 全部讀進記憶體，回傳 (date, report_md) 串
（newest first）。純 builder 才負責 markdown→HTML、消毒、模板。

跳過無 report.md 的日子（補跑中 / 失敗天）與非日期目錄。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from .builder import DayBrief, Narrative

# 日期目錄名格式：YYYY-MM-DD（其餘如 .vectordb / _judge-history.json 忽略）。
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 雙語敘事 config 的語言區塊標記：<!-- lang:zh --> / <!-- lang:en -->。
_LANG_MARKER_RE = re.compile(r"<!--\s*lang:(zh|en)\s*-->", re.IGNORECASE)

# 預設敘事 config 檔（in-repo，可直接編輯）。
DEFAULT_NARRATIVE_PATH = Path(__file__).resolve().parent / "config" / "narrative.md"


def load_days(output_dir: Path | str) -> List[DayBrief]:
    """讀 output_dir 下全部 <date>/report.md，回傳 (date, md) 串（newest first）。

    不存在的目錄回空串。注入式 output_dir（測試餵 tmp_path，正式注入 OUTPUT_DIR）。
    """
    base = Path(output_dir)
    if not base.is_dir():
        return []

    days: List[DayBrief] = []
    for child in base.iterdir():
        if not child.is_dir() or not _DATE_RE.match(child.name):
            continue
        report = child / "report.md"
        if not report.is_file():
            continue
        days.append((child.name, report.read_text(encoding="utf-8")))

    days.sort(key=lambda pair: pair[0], reverse=True)
    return days


def load_narrative(path: Path | str = DEFAULT_NARRATIVE_PATH) -> Narrative:
    """讀雙語敘事 config 檔，切出 zh／en 兩版 markdown，回傳 Narrative。

    config 檔以 `<!-- lang:zh -->` / `<!-- lang:en -->` 標記分隔兩個 markdown 區塊；
    標記前的前言（檔頭註解）忽略。唯一碰檔案的敘事讀取點（impure），與純 builder 解耦
    （純 builder 收記憶體 Narrative）。注入式 path：測試餵 fixture 檔，正式用預設 config。
    """
    text = Path(path).read_text(encoding="utf-8")

    sections: dict[str, str] = {}
    current: str | None = None
    buffer: List[str] = []

    def _flush() -> None:
        if current is not None:
            sections[current] = "".join(buffer).strip()

    for line in text.splitlines(keepends=True):
        marker = _LANG_MARKER_RE.search(line)
        if marker:
            _flush()
            current = marker.group(1).lower()
            buffer = []
            continue
        if current is not None:
            buffer.append(line)
    _flush()

    return Narrative(zh_md=sections.get("zh", ""), en_md=sections.get("en", ""))
