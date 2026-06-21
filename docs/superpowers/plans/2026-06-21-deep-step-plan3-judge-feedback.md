# Deep Step Abstraction — Plan 3: JudgeStep + Lift the Completeness Feedback Loop (Candidate 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `judge` to a deep `JudgeStep` and lift the `completeness < 3` digest-rerun feedback loop out of `_phase_judge` into explicit `run()` orchestration — removing the `retry_state` closure, the prompt re-serialization, and the split artifact writes (candidate 3). Every test stays green.

**Architecture:** `JudgeStep` does only judge scoring + persist `judge.json` + append `_judge-history.json`; its `StepOutcome.value` is the judge-result dict, `status` tells `run()` whether it actually RAN. The feedback loop becomes 4 explicit lines in `run()`: inspect the quality score, ask the supervisor to reflect (`reflect_for_completeness`), re-run `DigestStep(force=True)`, re-run `JudgeStep(force=True)`. `Step.run()` gains a `force` param meaning "unconditional RUN" so the feedback can re-produce a step regardless of gating. `supervisor.run_judge_feedback` shrinks to `reflect_for_completeness(missed_urls, original_digest_prompt)`.

**Tech Stack:** Python 3.10, dataclasses, pytest.

---

## Scope & decisions (from the grilling session)

- **In scope:** `judge` migration + feedback lift (candidate 3). Touches `step.py` (add `force` param), `supervisor.py` (swap `run_judge_feedback` → `reflect_for_completeness`), new `steps/judge.py`, `run()` rewiring, and rewriting the 5 judge integration tests.
- **Out of scope — Plan 4:** the `fetch` orchestrator + 5 two-stage Source Steps, and folding Fix C `_detect_stale_downstream` into orchestrator force-computation. `_phase_fetch` stays.
- **Kept untouched:** `_run_judge`, `_append_judge_history`, `_run_digest`, `_run_report`, `_notify`, `_run_save`, `_run_enrich`, `_run_compress` (all directly unit-tested).

## Behavior contract to preserve (the 5 judge integration tests encode this)

- **A.** completeness ≥ 3 (or non-numeric) → judge scored once, no feedback.
- **B.** completeness < 3 (and digest not force-pinned, digests present) → digest re-run + judge re-scored; the 2nd `_run_judge` receives the NEW digests.
- **C.** `--force judge` → `force=True` reaches `supervisor.run_step` for judge.
- **D.** judge LLM server unavailable → still goes through `run_step` (so retry works), no crash, no feedback.
- **E.** judge fails → report/notify continue; no log claims report was skipped.
- **New invariant:** feedback fires only when JudgeStep actually RAN (not when `judge.json` was LOADED from cache).

## Reference: current feedback loop (agent.py `_phase_judge`, to be deleted)

The leak being removed: a mutable `retry_state` dict shared across two closures, `original_digest_prompt` rebuilt via `json.dumps(compress_data)`, and `digest.json`/`judge.json` written back in the agent after `supervisor.run_judge_feedback` returns. `_run_judge(self, compress_data, digests, date=None) -> dict`. In `run()`, `enrich_data` plays the "compress_data" role for digest/judge.

---

## Task 1: Add `force` param to `Step.run()`

**Files:**
- Modify: `agents/daily_brief/step.py` (the `run` method)
- Test: `tests/agents/test_step.py` (append)

`force=True` means unconditional RUN (bypass gating) AND pass `force=True` to the supervisor. Default `False` keeps every existing caller identical.

- [ ] **Step 1: Append this test to `tests/agents/test_step.py`**

```python
# --- append to tests/agents/test_step.py ---
@pytest.mark.unit
def test_run_force_param_forces_run_even_when_not_in_steps(tmp_path):
    art = tmp_path / "compress.json"
    JsonCodec().write(art, {"v": 999})
    sup = _FakeSupervisor()
    # not in steps_to_run and artifact exists → normally LOAD; force=True → RUN
    ctx = _ctx(tmp_path, set(), set(), sup)
    outcome = _DoublerStep(art).run(ctx, 21, force=True)
    assert outcome.status is StepStatus.RAN
    assert outcome.value == 42
    assert sup.calls == 1


@pytest.mark.unit
def test_run_force_param_passed_to_supervisor(tmp_path):
    art = tmp_path / "compress.json"

    class _RecordingSupervisor:
        def __init__(self):
            self.forces = []

        def run_step(self, name, fn, force=False):
            self.forces.append(force)
            return SimpleNamespace(success=True, output=fn())

    sup = _RecordingSupervisor()
    ctx = _ctx(tmp_path, {"compress"}, set(), sup)
    _DoublerStep(art).run(ctx, 21, force=True)
    assert sup.forces == [True]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/agents/test_step.py -k force_param -v`
Expected: FAIL — `TypeError: run() got an unexpected keyword argument 'force'`

- [ ] **Step 3: Implement — modify `Step.run` in `agents/daily_brief/step.py`**

Replace the existing `run` method with exactly:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/agents/test_step.py -v`
Expected: PASS (11 passed — 9 existing + 2 new).

- [ ] **Step 5: Verify full suite green** (the `force` param is additive)

Run: `python3 -m pytest tests/ -q`
Expected: all green (264 passed → 266 passed, 1 skipped).

- [ ] **Step 6: Commit**

```bash
git add agents/daily_brief/step.py tests/agents/test_step.py
git commit -m "feat: add force param to Step.run for unconditional re-run"
```

---

## Task 2: Add `reflect_for_completeness` to the supervisor

**Files:**
- Modify: `agents/daily_brief/supervisor.py` (add method; keep `run_judge_feedback` for now — Task 4 removes it)
- Test: `tests/agents/test_supervisor.py` (append)

`reflect_for_completeness` is `run_judge_feedback` minus the `run_digest_fn`/`run_judge_fn` calls: it checks the judge server and returns a reflect hint (empty string on degrade).

- [ ] **Step 1: Append this test to `tests/agents/test_supervisor.py`**

First inspect the top of `tests/agents/test_supervisor.py` to reuse its existing supervisor-construction helper/fixture. Then append:

```python
# --- append to tests/agents/test_supervisor.py ---
@pytest.mark.unit
def test_reflect_for_completeness_returns_hint_when_server_up(tmp_path):
    from unittest.mock import MagicMock
    from agents.daily_brief.supervisor import SupervisorAgent

    sup = SupervisorAgent(llm=MagicMock(), judge_llm=MagicMock(),
                          steps_dir=tmp_path, today="2026-06-21", notify_fn=lambda m: True)
    sup._is_judge_server_available = lambda: True
    sup._reflect_with_judge = lambda missed, prompt: "REFLECT_HINT"
    assert sup.reflect_for_completeness(["http://x"], "orig prompt") == "REFLECT_HINT"


@pytest.mark.unit
def test_reflect_for_completeness_degrades_to_empty_when_server_down(tmp_path):
    from unittest.mock import MagicMock
    from agents.daily_brief.supervisor import SupervisorAgent

    sup = SupervisorAgent(llm=MagicMock(), judge_llm=MagicMock(),
                          steps_dir=tmp_path, today="2026-06-21", notify_fn=lambda m: True)
    sup._is_judge_server_available = lambda: False
    assert sup.reflect_for_completeness(["http://x"], "orig prompt") == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/agents/test_supervisor.py -k reflect_for_completeness -v`
Expected: FAIL — `AttributeError: 'SupervisorAgent' object has no attribute 'reflect_for_completeness'`

- [ ] **Step 3: Implement — add the method in `agents/daily_brief/supervisor.py`**

Add this method to `SupervisorAgent`, immediately AFTER the existing `run_judge_feedback` method (do NOT remove `run_judge_feedback` yet):

```python
    def reflect_for_completeness(
        self, missed_urls: list[str], original_digest_prompt: str
    ) -> str:
        """judge completeness < 3 時產出 digest 重跑用的 reflect 提示；server 無回應則降級回空字串。"""
        if self._is_judge_server_available():
            return self._reflect_with_judge(missed_urls, original_digest_prompt)
        logger.warning("Judge server 無回應，降級：直接用原 prompt 重跑 digest")
        return ""
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/agents/test_supervisor.py -v`
Expected: PASS (existing supervisor tests + 2 new).

- [ ] **Step 5: Commit**

```bash
git add agents/daily_brief/supervisor.py tests/agents/test_supervisor.py
git commit -m "feat: add SupervisorAgent.reflect_for_completeness"
```

---

## Task 3: JudgeStep (scoring only)

**Files:**
- Create: `agents/daily_brief/steps/judge.py`
- Test: `tests/agents/test_judge_step.py`

`JudgeStep`: input is `(compress_data, digests)`; `_produce` raises if the judge server is down (preserving behavior D), runs `_run_judge`, persists `judge.json`, returns the judge-result dict as both persist and value; `_guard` needs both inputs; `_load` returns the decoded judge result (identity); `_default` returns `None` (no score → `run()` skips feedback).

- [ ] **Step 1: Create `tests/agents/test_judge_step.py` with exactly:**

```python
"""JudgeStep — scoring only; value = judge_result dict; raises when server down."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.judge import JudgeStep


class _Supervisor:
    def __init__(self, server_up=True):
        self._up = server_up

    def _is_judge_server_available(self):
        return self._up

    def run_step(self, name, fn, force=False):
        try:
            return SimpleNamespace(success=True, output=fn(reflect_context=""))
        except Exception:
            return SimpleNamespace(success=False, output=None)


def _ctx(tmp_path, server_up=True, steps_to_run={"judge"}, force=set()):
    return SimpleNamespace(steps_dir=tmp_path, day_dir=tmp_path, today="2026-06-21",
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_Supervisor(server_up))


@pytest.mark.unit
def test_judge_step_runs_and_persists(tmp_path):
    judge_result = {"scores": {"completeness": {"score": 4}}, "overall": 4.0}

    def fake_run_judge(compress, digests, date=None):
        return judge_result

    outcome = JudgeStep(fake_run_judge).run(_ctx(tmp_path), ({"hn": {}}, [{"url": "http://a"}]))
    assert outcome.status is StepStatus.RAN
    assert outcome.value == judge_result
    assert JsonCodec().read(tmp_path / "judge.json") == judge_result


@pytest.mark.unit
def test_judge_step_fails_when_server_down(tmp_path):
    outcome = JudgeStep(lambda *a, **k: {}).run(
        _ctx(tmp_path, server_up=False), ({"hn": {}}, [{"url": "http://a"}]))
    assert outcome.status is StepStatus.FAILED
    assert outcome.value is None
    assert not (tmp_path / "judge.json").exists()


@pytest.mark.unit
def test_judge_step_guard_blocks_without_digests(tmp_path):
    outcome = JudgeStep(lambda *a, **k: {}).run(_ctx(tmp_path), ({"hn": {}}, []))
    assert outcome.status is StepStatus.SKIPPED


@pytest.mark.unit
def test_judge_step_default_is_none(tmp_path):
    outcome = JudgeStep(lambda *a, **k: {}).run(
        _ctx(tmp_path, steps_to_run=set()), ({"hn": {}}, [{"url": "http://a"}]))
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/agents/test_judge_step.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.daily_brief.steps.judge'`

- [ ] **Step 3: Create `agents/daily_brief/steps/judge.py` with exactly:**

```python
"""JudgeStep — LLM-as-Judge 品質評分（只評分，不含回饋迴圈）。

input 是 (compress_data, digests) 二元組。server 無回應時 raise（讓 supervisor 走 retry/FAILED）。
value = judge_result dict；run() 用它的 status==RAN + QualityScore 決定是否觸發 completeness 回饋。
_judge-history 的側寫由注入的 _run_judge 內部處理（維持不變）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..step import Step, StepOutput


class JudgeStep(Step):
    name = "judge"

    def __init__(self, run_judge: Callable[..., dict]) -> None:
        self._run_judge = run_judge

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "judge.json"

    def _guard(self, ctx, input) -> bool:
        compress_data, digests = input
        return bool(compress_data) and bool(digests)

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        compress_data, digests = input
        if not ctx.supervisor._is_judge_server_available():
            raise RuntimeError("judge LLM server 無回應")
        result = self._run_judge(compress_data, digests, date=ctx.today)
        return StepOutput(persist=result, value=result)

    def _default(self, input):
        return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/agents/test_judge_step.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agents/daily_brief/steps/judge.py tests/agents/test_judge_step.py
git commit -m "feat: add JudgeStep (scoring only, no feedback loop)"
```

---

## Task 4: Rewire `run()` feedback + delete `_phase_judge` + `run_judge_feedback`, rewrite the 5 integration tests

This is the integration task — it gets a spec + quality review. It wires JudgeStep into `run()`, expresses the feedback loop as 4 explicit lines, deletes `_phase_judge` and `supervisor.run_judge_feedback`, and rewrites the 5 judge integration tests to the new mechanism while preserving behaviors A–E.

**Files:**
- Modify: `agents/daily_brief/agent.py` (`run()` rewiring; delete `_phase_judge`)
- Modify: `agents/daily_brief/supervisor.py` (delete `run_judge_feedback`)
- Modify: `tests/test_daily_brief_agent.py` (rewrite the 5 judge integration tests)

- [ ] **Step 1: Rewrite the 5 judge integration tests in `tests/test_daily_brief_agent.py`**

These 5 tests currently define a `FakeSupervisor` with a `run_judge_feedback` method. Replace `run_judge_feedback` usage with the new mechanism: the feedback now calls `ctx.supervisor.reflect_for_completeness(missed_urls, original_digest_prompt)` then re-runs digest and judge via `run_step` with `force=True`. Update each FakeSupervisor: REMOVE its `run_judge_feedback` method, and ADD a `reflect_for_completeness(self, missed_urls, original_digest_prompt)` method returning `""` (or a guard that records it was called).

Apply these edits:

**(a) The no-feedback test** (the one asserting `_run_judge.assert_called_once()` with `run_judge_feedback` raising AssertionError): in its `FakeSupervisor`, replace
```python
        def run_judge_feedback(self, **kwargs):
            raise AssertionError("This test should not enter feedback loop")
```
with
```python
        def reflect_for_completeness(self, missed_urls, original_digest_prompt):
            raise AssertionError("This test should not enter feedback loop")
```

**(b) `test_judge_feedback_loop_uses_new_digests_for_retry`:** replace its `run_judge_feedback` method
```python
        def run_judge_feedback(
            self,
            missed_urls,
            original_digest_prompt,
            run_digest_fn,
            run_judge_fn,
        ):
            digest_output = run_digest_fn()
            judge_output = run_judge_fn()
            return digest_output[0], digest_output[1], judge_output
```
with
```python
        def reflect_for_completeness(self, missed_urls, original_digest_prompt):
            return ""
```
The assertions stay identical (`agent._run_judge.call_count == 2` and `call_args_list[1].args[1] == new_digests`) — the new `run()` re-runs digest (force) then judge (force), so `_run_judge` is still called twice with the new digests second.

**(c) `test_force_judge_passes_force_flag_to_supervisor`:** replace its
```python
        def run_judge_feedback(self, **kwargs):
```
...method (and its body) with
```python
        def reflect_for_completeness(self, missed_urls, original_digest_prompt):
            raise AssertionError("no feedback expected")
```
Assertion `judge_force_values == [True]` stays (judge runs once, forced; no feedback since `_run_judge` returns `{"overall": 4.2}` with no completeness score).

**(d) `test_judge_phase_uses_run_step_when_server_unavailable`:** replace its
```python
        def run_judge_feedback(self, **kwargs):
            raise AssertionError("不應進入 feedback loop")
```
with
```python
        def reflect_for_completeness(self, missed_urls, original_digest_prompt):
            raise AssertionError("不應進入 feedback loop")
```
Assertion `"judge" in run_step_calls` stays.

**(e) `test_judge_failure_log_does_not_claim_report_skipped`:** replace its
```python
        def run_judge_feedback(self, **kwargs):
            raise AssertionError("不應進入 feedback loop")
```
with
```python
        def reflect_for_completeness(self, missed_urls, original_digest_prompt):
            raise AssertionError("不應進入 feedback loop")
```
Assertion `"略過 report/notify" not in caplog.text` stays.

- [ ] **Step 2: Run the rewritten tests — confirm they FAIL against current code**

Run: `python3 -m pytest tests/test_daily_brief_agent.py -k judge -v`
Expected: FAILs — the current `_phase_judge` still calls `run_judge_feedback` (now removed from the fakes) for the feedback test, and the fakes no longer provide it. (This confirms the tests now describe the NEW mechanism.)

- [ ] **Step 3: Rewire `run()` in `agents/daily_brief/agent.py`**

Find in `run()`:
```python
        enrich_data, digests = self._phase_judge(ctx, enrich_data, digests)
```
Replace with exactly:
```python
        from .steps.judge import JudgeStep
        from .steps.digest import DigestStep
        judge_outcome = JudgeStep(self._run_judge).run(ctx, (enrich_data, digests))
        if judge_outcome.status is StepStatus.RAN:
            quality = QualityScore.from_dict(judge_outcome.value)
            if (
                quality.completeness is not None
                and quality.completeness < 3
                and "digest" not in ctx.force_steps
                and digests
            ):
                logger.warning(
                    "Judge completeness=%.1f，觸發 digest 重跑（missed: %s）",
                    quality.completeness,
                    list(quality.missed_urls),
                )
                hint = ctx.supervisor.reflect_for_completeness(
                    list(quality.missed_urls),
                    prompts.build_digest_prompt_from_compress(
                        json.dumps(enrich_data, ensure_ascii=False)
                    ),
                )
                digests = DigestStep(self._run_digest).run(
                    ctx, enrich_data, reflect=hint, force=True
                ).value
                JudgeStep(self._run_judge).run(ctx, (enrich_data, digests), force=True)
                logger.info("Judge 回饋 digest 重跑完成")
```

Ensure `StepStatus` is imported at the top of `agent.py` (add `from .step import StepStatus` if not already present; `QualityScore` and `prompts` and `json` are already imported).

- [ ] **Step 4: Delete `_phase_judge`**

Delete the entire `_phase_judge` method (from `def _phase_judge(` through its final `return compress_data, digests`). Leave `_run_judge`, `_append_judge_history` intact.

- [ ] **Step 5: Delete `run_judge_feedback` from the supervisor**

In `agents/daily_brief/supervisor.py`, delete the entire `run_judge_feedback` method (from `def run_judge_feedback(` through its `return digests, digest_data, judge_result`). Leave `reflect_for_completeness`, `_reflect_with_judge`, `_is_judge_server_available`, `run_step` intact.

- [ ] **Step 6: Run the judge tests, then the full suite**

Run: `python3 -m pytest tests/test_daily_brief_agent.py -k judge -v`
Expected: PASS (all 5 rewritten judge tests).

Run: `python3 -m pytest tests/ -q`
Expected: all green (266 passed + 4 from JudgeStep = 270 passed, 1 skipped).

Run: `grep -rn "_phase_judge\|run_judge_feedback" agents/ tests/`
Expected: no LIVE code reference (docstring mentions OK).

- [ ] **Step 7: Commit**

```bash
git add agents/daily_brief/agent.py agents/daily_brief/supervisor.py tests/test_daily_brief_agent.py
git commit -m "refactor: lift judge completeness feedback into run() (candidate 3)"
```

---

## Task 5: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (the Step migration-status sentence)

- [ ] **Step 1: Update the status sentence**

Find:
```
已遷移：compress / dedup / enrich / digest / report / save / notify（`steps/*.py`）；尚未遷移：judge（與 completeness 回饋迴圈一併處理）與 fetch orchestrator，見 `docs/superpowers/plans/2026-06-21-deep-step-plan2-linear-middle.md` 完成記錄與 Plan 3。
```
Replace with:
```
已遷移：compress / dedup / enrich / digest / judge / report / save / notify（`steps/*.py`）；judge 的 completeness 回饋迴圈已提昇進 `run()`（`Step.run(force=True)` 觸發無條件重跑，`supervisor.reflect_for_completeness` 取代舊 `run_judge_feedback`）。尚未遷移：fetch orchestrator（5 源兩階段 Source Step）與 Fix C 歸位，見 Plan 4。
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record judge migration + feedback lift in CLAUDE.md"
```

---

## Self-Review

**Spec coverage:**
- `Step.run(force=…)` unconditional re-run + passed to supervisor: T1. ✓
- `reflect_for_completeness` (replaces feedback reflect): T2. ✓
- JudgeStep scoring-only, raises on server-down (D), `_default=None`: T3. ✓
- `run()` feedback lift gated on `status is RAN` (new invariant), 4 explicit lines, no closure/no split write/no prompt-rebuild-from-compress (uses `enrich_data` once): T4 Step 3. ✓
- Delete `_phase_judge` + `run_judge_feedback`: T4 Steps 4–5. ✓
- 5 integration tests rewritten preserving A–E: T4 Step 1. ✓
- Docs: T5. ✓
- fetch + Fix C deferred to Plan 4 (documented). ✓ (not a gap)

**Placeholder scan:** No TBD/TODO. Deletions specified by signature. ✓

**Type consistency:** `JudgeStep` follows the `Step` interface (`_produce(ctx, input, reflect_context="")`, `_guard`, `_default`, `artifact_path`). `Step.run(ctx, input, reflect="", force=False)` — feedback calls use `reflect=`/`force=True` consistently. `QualityScore.from_dict` + `.completeness`/`.missed_urls` match `schemas.py`. `StepStatus.RAN` gating. Fake supervisors expose `run_step`/`_is_judge_server_available`/`reflect_for_completeness`. ✓

---

## Follow-up: Plan 4 (fetch orchestrator)

- `fetch` stays an orchestrator driving 5 two-stage Source Steps (`fetch_raw` parallel / `score` serial via supervisor, ≥2 success gate → abort). `_fetch_raw_data` / `_score_raw_data` / `_score_reddit_batched` kept and injected.
- Fold Fix C `_detect_stale_downstream` into an orchestrator force-computation helper.
- Final dead-code sweep (`decide`/`Verdict` imports in `agent.py` once `_phase_judge`/`_phase_fetch` patterns are gone) + lint.
