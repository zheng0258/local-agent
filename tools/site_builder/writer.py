"""write_site — 薄 writer：把 in-memory {path: html} map 落盤到目錄。

唯一碰檔案的地方；純函數核心 (build_site) 不碰檔案。
"""

from __future__ import annotations

from pathlib import Path


def write_site(site_map: dict[str, str], out_dir: Path) -> None:
    """把 {相對路徑: html} map 寫進 out_dir（自動建立子目錄）。

    key 逐一檢查必須落在 out_dir 內：絕對路徑與 `..` 逃逸一律拒收。站台 key 目前
    由內部日期組成（可信），但 writer 是唯一碰檔案的地方，邊界檢查留在這裡才不會
    隨上游新增 key 來源而失守。
    """
    out_dir = Path(out_dir).resolve()
    for rel_path, html in site_map.items():
        target = (out_dir / rel_path).resolve()
        if not target.is_relative_to(out_dir):
            raise ValueError(f"站台路徑逃逸 out_dir，拒絕寫入：{rel_path!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
