"""SaveStep — 把 report.md + digest 存進 Obsidian vault。

SentinelCodec：成功後 touch vault.done（存在 = 已存過 → 下次 LOAD 略過）。
guard：需有 digests、report.md 已存在、且 vault 已配置（VAULT_ROOT）。
vault 未配置時整步略過（不 touch vault.done、不入 health 記錄）。
producer 注入自 _run_save（純副作用）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from config import get_logger

from ..codecs import SentinelCodec
from ..step import Step, StepOutput

logger = get_logger(__name__)


class SaveStep(Step):
    name = "save"
    codec = SentinelCodec()

    def __init__(self, run_save: Callable[..., None], today: str) -> None:
        self._run_save = run_save
        self._today = today

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "vault.done"

    def _guard(self, ctx, input) -> bool:
        from ..config import VAULT_DAILY_BRIEF_DIR

        if not (bool(input) and (ctx.day_dir / "report.md").exists()):
            return False
        if VAULT_DAILY_BRIEF_DIR is None:
            return False  # 未配置 VAULT_ROOT：save 停用，靜默略過
        # 已配置但 vault 根目錄不存在（誤填 / iCloud 未掛載）→ 警告並略過，
        # 不用 mkdir(parents=True) 建出一棵假目錄樹。
        vault_root = VAULT_DAILY_BRIEF_DIR.parent.parent
        if not vault_root.exists():
            logger.warning("Save: VAULT_ROOT 路徑不存在，略過存檔：%s", vault_root)
            return False
        return True

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        self._run_save(ctx.day_dir, self._today, input)
        return StepOutput(persist=None, value=None)

    def _default(self, input):
        return None
