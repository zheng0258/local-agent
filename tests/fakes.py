"""daily-brief Step 框架的共用 test doubles。

取代原本散落 ~17 份的 FakeSupervisor 與 ~13 份手刻 ctx SimpleNamespace。

- FakeSupervisor —— 滿足 Supervisor Protocol（run_step）的 canonical adapter；
  額外提供 reflect_for_completeness 給 orchestrator 層測試共用（不在 Protocol 表面上）。
- make_step_ctx —— 建一個「真的」frozen _RunContext 給 step 層測試，杜絕仿製品 drift。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agents.daily_brief.agent import ALL_STEPS, _RunContext
from agents.daily_brief.step import StepResult


class FakeSupervisor:
    """canonical supervisor test double。

    run_step 行為鏡射真 SupervisorAgent：
      - name 在 fail 集合 → 直接回 FAILED（不呼叫 producer）
      - producer 拋例外 → 回 FAILED（模擬重試耗盡的吞例外）
      - 否則 → 回 RAN，output = producer 回傳的 StepOutput
    另記錄 calls（名稱序）與 forced（各 step 收到的 force 旗標）供斷言。
    """

    def __init__(
        self,
        *,
        fail: frozenset[str] = frozenset(),
        forbid_reflect: bool = False,
        hint: str = "",
    ) -> None:
        self._fail = set(fail)
        self._forbid_reflect = forbid_reflect
        self._hint = hint
        self.calls: list[str] = []
        self.forced: dict[str, bool] = {}

    def run_step(
        self, name: str, fn: Callable[..., Any], force: bool = False
    ) -> StepResult:
        self.calls.append(name)
        self.forced[name] = force
        if name in self._fail:
            return StepResult(
                name=name, success=False, output=None, error="fake failure", attempts=1
            )
        try:
            return StepResult(
                name=name, success=True, output=fn(), error=None, attempts=1
            )
        except Exception as exc:  # 鏡射 supervisor 重試耗盡後的 FAILED
            return StepResult(
                name=name, success=False, output=None, error=str(exc), attempts=1
            )

    def reflect_for_completeness(
        self, missed_urls: list[str], original_digest_prompt: str
    ) -> str:
        if self._forbid_reflect:
            raise AssertionError("不應進入 feedback loop")
        return self._hint


def make_step_ctx(
    tmp_path: Path,
    *,
    supervisor: Any = None,
    steps_to_run: set[str] | None = None,
    force_steps: frozenset[str] | set[str] = frozenset(),
    notify_fn: Callable[[str], bool] = lambda _msg: True,
    today: str = "2026-06-21",
) -> _RunContext:
    """建真 _RunContext；steps_dir/day_dir 皆指向 tmp_path。

    steps_to_run 預設 = 全部 step（被測 step 落在 RUN）；要測 SKIP 傳 set()。
    supervisor 預設 = FakeSupervisor()。
    """
    return _RunContext(
        today=today,
        day_dir=tmp_path,
        steps_dir=tmp_path,
        force_steps=set(force_steps),
        steps_to_run=set(ALL_STEPS) if steps_to_run is None else set(steps_to_run),
        supervisor=supervisor if supervisor is not None else FakeSupervisor(),
        notify_fn=notify_fn,
    )
