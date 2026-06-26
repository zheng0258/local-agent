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

from .builder import DayBrief

# 日期目錄名格式：YYYY-MM-DD（其餘如 .vectordb / _judge-history.json 忽略）。
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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
