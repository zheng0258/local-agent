"""Step — 步驟化執行的深模組：gating + artifact I/O + supervisor 接線藏在 run() 後面。

公開介面只有 run(ctx, input) -> StepOutcome。_produce / _load / _guard / _default
是內部 seam，子類只 override 自己不一樣的那塊。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from config import get_logger

from .codecs import ArtifactCodec, JsonCodec
from .step_cache import Verdict, decide

logger = get_logger(__name__)


class StepStatus(Enum):
    RAN = "ran"        # 跑了 producer 並寫 artifact
    LOADED = "loaded"  # 用既有 artifact
    SKIPPED = "skipped"  # 不在 steps_to_run / guard 不過 → 回 default
    FAILED = "failed"  # producer 重試耗盡 → 回 default


@dataclass(frozen=True)
class StepOutput:
    """_produce 的回傳：要落盤的物件 + 要傳給下游的 value（兩者可不同）。"""

    persist: Any
    value: Any


@dataclass(frozen=True)
class StepOutcome:
    """Step.run() 的回傳：狀態 + 傳給下游的 value。status 只供 logging/alert，不驅動 cascade。"""

    status: StepStatus
    value: Any


class Step:
    """步驟化執行的模板。子類設定 name + artifact_path，並 override 需要的內部 seam。"""

    name: str = ""
    codec: ArtifactCodec = JsonCodec()

    def artifact_path(self, ctx) -> Path:
        raise NotImplementedError

    # ── 內部 seam（預設吃掉整齊步）─────────────────────────────────
    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        raise NotImplementedError

    def _load(self, decoded, input):
        """LOAD 時把磁碟解碼結果轉成下游 value。預設 identity；dedup/digest override。"""
        return decoded

    def _guard(self, ctx, input) -> bool:
        """RUN 前的前置檢查。預設 input 為真；save/notify/judge override。"""
        return bool(input)

    def _default(self, input):
        """SKIP 與 FAILED 共用的回傳值。預設 None；pass-through 步回 input，producer 回 {}/[]"""
        return None

    # ── 公開介面 ─────────────────────────────────────────────────
    def run(self, ctx, input, reflect: str = "", force: bool = False) -> StepOutcome:
        path = self.artifact_path(ctx)
        if force:
            verdict = Verdict.RUN
        else:
            verdict = decide(
                self.name in ctx.steps_to_run,
                self.codec.exists(path),
                self.name in ctx.force_steps,
            )
        if verdict is Verdict.SKIP:
            return StepOutcome(StepStatus.SKIPPED, self._default(input))
        if verdict is Verdict.LOAD:
            logger.info("Step %-8s: 載入既有 artifact", self.name)
            return StepOutcome(StepStatus.LOADED, self._load(self.codec.read(path), input))
        if not self._guard(ctx, input):
            logger.warning("Step %-8s: 缺少輸入或前置條件，略過", self.name)
            return StepOutcome(StepStatus.SKIPPED, self._default(input))

        logger.info("Step %-8s: 執行中...", self.name)
        forced = force or (self.name in ctx.force_steps)

        def _producer(reflect_context: str = "") -> StepOutput:
            return self._produce(ctx, input, reflect_context or reflect)

        result = ctx.supervisor.run_step(self.name, _producer, force=forced)
        if not result.success:
            return StepOutcome(StepStatus.FAILED, self._default(input))
        output: StepOutput = result.output
        self.codec.write(path, output.persist)
        logger.info("Step %-8s: 完成 → %s", self.name, path.name)
        return StepOutcome(StepStatus.RAN, output.value)
