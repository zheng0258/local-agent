"""NotifyStep — send-only 的 Telegram 發送（兩封），逐封冪等。

input 是 compose 步驟產出的 {"overview": str, "digest": str}（純文字，本步不生成）。
每封各有 sub-sentinel（telegram_overview.done / telegram_digest.done）：已送出的那封
重試不重送。兩封都送出後才 touch telegram.done（整體完成標記，SentinelCodec 的主 artifact）。
任一封發送失敗 → raise → supervisor 記 FAILED、telegram.done 不寫入（沿用 --force notify 重試）。
send callable 注入（測試注入 fake，無網路）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from config import get_logger

from ..codecs import SentinelCodec
from ..step import Step, StepOutput

logger = get_logger(__name__)


class NotifyStep(Step):
    name = "notify"
    codec = SentinelCodec()

    def __init__(self, send: Callable[[str], bool], today: str) -> None:
        self._send = send
        self._today = today

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "telegram.done"

    def _guard(self, ctx, input) -> bool:
        return isinstance(input, dict) and bool(
            input.get("overview") or input.get("digest")
        )

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        overview = input.get("overview", "")
        digest = input.get("digest", "")

        self._deliver_once(ctx, "telegram_overview.done", overview)
        self._deliver_once(ctx, "telegram_digest.done", digest)
        return StepOutput(persist=None, value=None)

    def _deliver_once(self, ctx, sentinel_name: str, text: str) -> None:
        """逐封冪等：sub-sentinel 已存在 → 不重送；發送失敗 → raise（不寫 sub-sentinel）。"""
        if not text:
            return
        sentinel = ctx.day_dir / sentinel_name
        if sentinel.exists():
            logger.info("Step notify   : %s 已送出，略過重送", sentinel_name)
            return
        if not self._send(text):
            logger.error(
                "Step notify   : %s 發送失敗，telegram.done 不寫入", sentinel_name
            )
            raise RuntimeError(f"Telegram 訊息發送失敗（{sentinel_name}）")
        sentinel.touch()

    def _default(self, input):
        return None
