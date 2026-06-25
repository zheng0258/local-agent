"""site_builder — 純函數站台建造器（tracer bullet）。

吃最新一天 Brief 語料（report markdown + 日期），回傳 in-memory
`{相對路徑: html 字串}` map。核心不碰 git / LLM / 網路 / 檔案；
薄 writer (`write_site`) 才把 map 落盤。
"""

from __future__ import annotations

from .builder import build_site
from .writer import write_site

__all__ = ["build_site", "write_site"]
