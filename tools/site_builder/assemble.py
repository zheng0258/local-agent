"""build_full_site — 整站組裝的單一深入口。

把「讀全部歷史天 + 敘事 config + 今日重點 + 系統狀態 → 站頁 map，再合併 judge/health
歷史原文端點」這串六步組裝收進一次呼叫。原本攤在 agent.run() 的 deploy thunk 裡：
orchestrator 得知道要 load 哪幾種輸入、餵參順序、以及合併不變式。收進此入口後，
呼叫端只需 `build_full_site(OUTPUT_DIR)`。

合併不變式：judge/health 歷史原文以乾淨檔名（judge-history.json / health-history.json）
發佈為機器可讀端點，置於合併右側 → 站頁 map 覆寫不到這兩個 key。
"""

from __future__ import annotations

from pathlib import Path

from .builder import build_site_archive
from .loader import (
    load_days,
    load_latest_tldr,
    load_narrative,
    load_raw_histories,
    load_status,
)


def build_full_site(output_dir: Path | str) -> dict[str, str]:
    """讀 output_dir 下全部歷史 → 完整站台 `{相對路徑: 內容}` map（含機器可讀端點）。"""
    site = build_site_archive(
        load_days(output_dir),
        narrative=load_narrative(),
        latest_tldr=load_latest_tldr(output_dir),
        status=load_status(output_dir),
    )
    return {**site, **load_raw_histories(output_dir)}
