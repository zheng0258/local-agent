"""write_site — 薄 writer：把 in-memory {path: html} map 落盤到目錄。

唯一碰檔案的地方；純函數核心 (build_site) 不碰檔案。
"""

from __future__ import annotations

from pathlib import Path


def write_site(site_map: dict[str, str], out_dir: Path) -> None:
    """把 {相對路徑: html} map 寫進 out_dir（自動建立子目錄）。"""
    out_dir = Path(out_dir)
    for rel_path, html in site_map.items():
        target = out_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
