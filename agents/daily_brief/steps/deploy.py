"""DeployStep — 把最新一天的 Brief 發佈成公開站台（tracer bullet）。

SentinelCodec：成功後 touch deploy.done（存在 = 已發佈 → 下次 LOAD 略過）。
guard：今日 report.md 必須存在（gate-on-success）。
注入純 builder（report_md, date → {path: html} map）與一個 push 副作用 callable
（把 build 產物 force-push 到 gh-pages branch，git 隔離藏在 push 內部）。
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
        build: Callable[[str, str], dict[str, str]],
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
        report_md = (ctx.day_dir / "report.md").read_text(encoding="utf-8")
        site_map = self._build(report_md, self._today)
        with tempfile.TemporaryDirectory(prefix="site-build-") as tmp:
            build_dir = Path(tmp)
            write_site(site_map, build_dir)
            logger.info("Deploy: 建造 %d 個檔案 → push", len(site_map))
            self._push(build_dir)
        return StepOutput(persist=None, value=None)

    def _default(self, input):
        return None
