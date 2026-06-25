"""site_builder — 純函數站台建造器。

`build_site_archive(days)` 吃完整歷史語料（(date, report_md) 串，newest first），
回傳 in-memory `{相對路徑: html}` map：首頁 + 每天一頁存檔頁。
`build_site` 為單天便利包裝。核心不碰 git / LLM / 網路 / 檔案。
`load_days` 是唯一碰檔案的歷史讀取點（impure，掃 OUTPUT_DIR/<date>/report.md）；
薄 writer (`write_site`) 才把 map 落盤。
"""

from __future__ import annotations

from .builder import build_site, build_site_archive
from .loader import load_days
from .writer import write_site

__all__ = ["build_site", "build_site_archive", "load_days", "write_site"]
