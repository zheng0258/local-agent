"""DeployStep — 把完整歷史存檔發佈成公開站台。

SentinelCodec：成功後 touch deploy.done（存在 = 已發佈 → 下次 LOAD 略過）。
guard：今日 report.md 必須存在（gate-on-success）。
注入 build 為**零參 thunk**（loader 讀全部歷史天 → build_site_archive → {path: html}
全量 map），確保每次發佈全量重建整站、公開站與本機真實狀態一致；以及一個 push
副作用 callable（把 build 產物 force-push 到 gh-pages branch，git 隔離藏在 push 內部）。
_produce 把 builder 產出寫進獨立 build 目錄後交給 push。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

from config import get_logger

from ..codecs import SentinelCodec
from ..step import Step, StepOutput
from tools.site_builder import write_site

logger = get_logger(__name__)


class DeployStep(Step):
    name = "deploy"
    codec = SentinelCodec()

    def __init__(
        self,
        build: Callable[[], dict[str, str]],
        push: Callable[[Path], None],
        today: str,
    ) -> None:
        self._build = build
        self._push = push
        self._today = today

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "deploy.done"

    def _guard(self, ctx, input) -> bool:
        # gate-on-success：今日有 report.md 才發佈
        return (ctx.day_dir / "report.md").exists()

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        # 全量重建：build thunk 內部讀全部歷史天 → 整站 map。
        site_map = self._build()
        with tempfile.TemporaryDirectory(prefix="site-build-") as tmp:
            build_dir = Path(tmp)
            write_site(site_map, build_dir)
            logger.info("Deploy: 全量建造 %d 個檔案 → push", len(site_map))
            self._push(build_dir)
        return StepOutput(persist=None, value=None)

    def _default(self, input):
        return None
