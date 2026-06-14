"""decide() — cache-or-force gating verdict 的真值表。

被 8 個 _phase_* 重抄的不變量，集中於此並獲得唯一一份測試。
"""

import pytest

from agents.daily_brief.step_cache import Verdict, decide


@pytest.mark.unit
@pytest.mark.parametrize(
    "in_steps,exists,forced,want",
    [
        # 不在 steps_to_run：有 artifact 就載入，否則略過（forced 無關）
        (False, False, False, Verdict.SKIP),
        (False, False, True, Verdict.SKIP),
        (False, True, False, Verdict.LOAD),
        (False, True, True, Verdict.LOAD),
        # 在 steps_to_run：無 artifact 必跑（forced 無關）
        (True, False, False, Verdict.RUN),
        (True, False, True, Verdict.RUN),
        # 在 steps_to_run 且有 artifact：force 決定載入或重跑
        (True, True, False, Verdict.LOAD),
        (True, True, True, Verdict.RUN),
    ],
)
def test_decide(in_steps: bool, exists: bool, forced: bool, want: Verdict) -> None:
    assert decide(in_steps, exists, forced) is want
