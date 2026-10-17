"""decide() — cache-or-force gating verdict 的真值表。

被 8 個 _phase_* 重抄的不變量，集中於此並獲得唯一一份測試。
"""

import pytest

from agents.daily_brief.step_cache import Verdict, decide, upstream_ran


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


# ── 同一次 run 內的上游失效（2026-10-17：rss 下午才 RUN，dedup 卻 LOAD 舊 kept_urls）──


@pytest.mark.unit
@pytest.mark.parametrize(
    "in_steps,exists,forced,want",
    [
        # 上游本次 RUN → 等同 force：有 artifact 也必須重跑
        (True, True, False, Verdict.RUN),
        (True, False, False, Verdict.RUN),
        # --only 收窄（不在 steps_to_run）仍尊重使用者意圖：不因上游而跑
        (False, True, False, Verdict.LOAD),
        (False, False, False, Verdict.SKIP),
    ],
)
def test_decide_upstream_ran_overrides_load(
    in_steps: bool, exists: bool, forced: bool, want: Verdict
) -> None:
    assert decide(in_steps, exists, forced, upstream_ran=True) is want


@pytest.mark.unit
@pytest.mark.parametrize(
    "name,ran,want",
    [
        # 10-17 情境：任一來源本次 RUN → dedup 失效
        ("dedup", {"rss"}, True),
        ("dedup", set(), False),
        # 遞移沿 pipeline 順序：來源 RUN → 更下游亦失效
        ("compress", {"hatena"}, True),
        ("deploy", {"digest"}, True),
        # 同層兄弟互不失效：五個來源並列；digest 的消費者（tldr/judge/report/compose_tg）並列
        ("hn", {"hatena"}, False),
        ("rss", {"hatena", "hn", "reddit", "security"}, False),
        ("judge", {"tldr"}, False),
        ("compose_tg", {"report"}, False),
        # report 重生 → 站台必須重新發佈
        ("deploy", {"report"}, True),
        # 下游 RUN 不回頭失效上游
        ("dedup", {"compress", "deploy"}, False),
        # save / notify 為使用者決定的副作用步（同 Fix C），不參與傳播
        ("save", {"digest"}, False),
        ("notify", {"compose_tg"}, False),
    ],
)
def test_upstream_ran(name: str, ran: set[str], want: bool) -> None:
    assert upstream_ran(name, ran) is want
