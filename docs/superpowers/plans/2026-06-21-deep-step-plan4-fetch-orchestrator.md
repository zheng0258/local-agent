# Deep Step Abstraction — Plan 4: Fetch Orchestrator + Source Steps + Fix C Fold

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn each of the 5 Sources into a deep `SourceStep` (a `Step` subclass that scores + persists one source), make `_phase_fetch` a thin orchestrator (parallel raw-fetch → serial score-via-`run()` → ≥2 success gate), and fold the Fix C stale-detection force-computation into a single helper. This finishes the deep-Step refactor; afterward no `_phase_*` methods remain. Every test stays green.

**Architecture:** Per the grilling, `fetch` stays an **orchestrator** (like `run()`), not a Step. Its 5 Sources become `SourceStep` (a `Step` subclass): `_produce` scores pre-fetched raw + stamps `fetched_at`; the codec persists `{name}.json`. The two-stage split (raw parallel / score serial — required because LM Studio rejects concurrent scoring requests, and Playwright sources need parallel raw) is realised by the orchestrator: it pre-fetches raw for RUN-verdict sources **in parallel**, then calls `SourceStep.run(ctx, raw)` **serially**. Gating moves from hand-rolled inline logic to `decide()` (Plan 1's gating authority).

**Tech Stack:** Python 3.10, `concurrent.futures`, pytest.

---

## Scope & decisions (from the grilling session)

- **`fetch` is an orchestrator, not a Step** (grilling Q6). The 5 Sources (`hatena`/`hn`/`reddit`/`security`/`rss`) become `SourceStep` (grilling Q7, option 甲: two-stage).
- **Two-stage realised by the orchestrator**, not by a custom Step lifecycle: parallel `_fetch_raw_data` (network) → serial `SourceStep.run(ctx, raw)` (score via supervisor). This keeps `SourceStep` a plain `Step` subclass and preserves the LM-Studio-serial / Playwright-parallel performance characteristics (CLAUDE.md gotchas).
- **Kept untouched (directly unit-tested):** `_fetch_raw_data`, `_score_raw_data`, `_score_reddit_batched`.
- **Fix C** stays orchestrator-owned (grilling Q13, option 乙) — this plan only extracts the existing run() lines into a named helper for locality; the mtime mechanism is unchanged.
- **Re-add import:** Plan 3 removed `from .step_cache import Verdict, decide` from `agent.py`. The new orchestrator uses `decide`/`Verdict`, so Task 2 re-adds that import.

## Reference: current behavior to preserve (no direct `_phase_fetch` test exists)

- Cached sources (`{name}.json` exists, not forced, not in `--only` excluding it) load their scored artifact.
- Sources needing work fetch raw **in parallel**, then score **serially** via `supervisor.run_step(name, fn, force)`, writing `{name}.json` with a `fetched_at` stamp.
- Success = a source present in `source_data` (loaded OR freshly scored). If `success_count < 2` and the run touches any fetch step → Telegram alert + abort (`run()` returns the "fetch 不足" string).
- A raw-fetch exception for one source must not crash the others.

---

## Task 1: SourceStep

**Files:**
- Create: `agents/daily_brief/steps/source.py`
- Test: `tests/agents/test_source_step.py`

`SourceStep` is a `Step` subclass with a per-instance `name`. Input is the pre-fetched raw list (or `None` if its raw-fetch failed). `_produce` scores the raw via the injected `score_fn`, stamps `fetched_at`, returns it as persist+value. `_guard` passes when raw `is not None` (so an empty list `[]` still scores, matching today; a failed fetch `None` skips). `_default` is `None`. On LOAD it returns the decoded scored artifact (identity default).

- [ ] **Step 1: Create `tests/agents/test_source_step.py` with exactly:**

```python
"""SourceStep — a Step subclass: scores pre-fetched raw into {name}.json."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.source import SourceStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn())


def _ctx(tmp_path, steps_to_run={"hn"}, force=set()):
    return SimpleNamespace(steps_dir=tmp_path, day_dir=tmp_path, today="2026-06-21",
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_FakeSupervisor())


@pytest.mark.unit
def test_source_step_scores_raw_and_stamps_fetched_at(tmp_path):
    captured = {}

    def fake_score(name, raw):
        captured["args"] = (name, raw)
        return {"articles": [{"url": "http://a", "interest": "***"}]}

    outcome = SourceStep("hn", fake_score).run(_ctx(tmp_path), [{"title": "t"}])

    assert outcome.status is StepStatus.RAN
    assert captured["args"] == ("hn", [{"title": "t"}])
    saved = JsonCodec().read(tmp_path / "hn.json")
    assert saved["articles"] == [{"url": "http://a", "interest": "***"}]
    assert "fetched_at" in saved
    assert outcome.value["articles"][0]["url"] == "http://a"


@pytest.mark.unit
def test_source_step_guard_skips_when_raw_is_none(tmp_path):
    outcome = SourceStep("hn", lambda n, r: {"articles": []}).run(_ctx(tmp_path), None)
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None
    assert not (tmp_path / "hn.json").exists()


@pytest.mark.unit
def test_source_step_scores_empty_raw_list(tmp_path):
    # empty raw is still scored (not skipped) — matches old behavior
    outcome = SourceStep("hn", lambda n, r: {"articles": []}).run(_ctx(tmp_path), [])
    assert outcome.status is StepStatus.RAN
    assert (tmp_path / "hn.json").exists()


@pytest.mark.unit
def test_source_step_loads_existing_scored_artifact(tmp_path):
    JsonCodec().write(tmp_path / "hn.json", {"articles": [{"url": "http://cached"}], "fetched_at": "t"})
    # not in steps_to_run → LOAD
    ctx = _ctx(tmp_path, steps_to_run=set())
    outcome = SourceStep("hn", lambda n, r: {}).run(ctx, None)
    assert outcome.status is StepStatus.LOADED
    assert outcome.value["articles"][0]["url"] == "http://cached"


@pytest.mark.unit
def test_source_step_artifact_path_uses_name(tmp_path):
    step = SourceStep("reddit", lambda n, r: {})
    assert step.artifact_path(SimpleNamespace(steps_dir=tmp_path)) == tmp_path / "reddit.json"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/agents/test_source_step.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.daily_brief.steps.source'`

- [ ] **Step 3: Create `agents/daily_brief/steps/source.py` with exactly:**

```python
"""SourceStep — 單一來源（Source）的評分 + 落盤 {name}.json。

fetch 是 orchestrator；本 Step 只負責「對已抓取的 raw 評分並持久化」這一段（serial 階段）。
raw 由 orchestrator 並行預抓後當 input 餵入：None = 抓取失敗 → guard 略過；[] = 空 → 仍評分。
score_fn 注入自 DailyBriefAgent._score_raw_data。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from ..step import Step, StepOutput


class SourceStep(Step):
    def __init__(self, name: str, score_fn: Callable[[str, list], dict]) -> None:
        self.name = name
        self._score = score_fn

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / f"{self.name}.json"

    def _guard(self, ctx, input) -> bool:
        return input is not None

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        result = self._score(self.name, input)
        result["fetched_at"] = datetime.now().isoformat(timespec="seconds")
        return StepOutput(persist=result, value=result)

    def _default(self, input):
        return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/agents/test_source_step.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add agents/daily_brief/steps/source.py tests/agents/test_source_step.py
git commit -m "feat: add SourceStep (per-source score + persist)"
```

---

## Task 2: Rewrite `_phase_fetch` as a thin orchestrator

This is the integration task — it gets a spec + quality review (it touches concurrency and the ≥2 abort gate). The orchestrator: (1) computes each source's verdict via `decide`; (2) parallel-fetches raw for RUN-verdict sources; (3) serially calls `SourceStep.run(ctx, raw)` for every source; (4) applies the ≥2 success gate.

**Files:**
- Modify: `agents/daily_brief/agent.py` (rewrite `_phase_fetch`; re-add `decide`/`Verdict` import; delete the now-dead inline helpers)
- Test: `tests/agents/test_fetch_orchestrator.py`

- [ ] **Step 1: Create `tests/agents/test_fetch_orchestrator.py` with exactly:**

```python
"""_phase_fetch orchestrator — parallel raw / serial score / ≥2 gate, via SourceStep."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agents.daily_brief.agent import DailyBriefAgent, FETCH_STEPS


def _ctx(tmp_path, steps_to_run, force=set()):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir(exist_ok=True)
    sup = SimpleNamespace()
    sup.run_step = lambda name, fn, force=False: SimpleNamespace(success=True, output=fn())
    return SimpleNamespace(
        today="2026-06-21", day_dir=tmp_path, steps_dir=steps_dir,
        steps_to_run=set(steps_to_run), force_steps=set(force),
        supervisor=sup, notify_fn=lambda m: True,
    )


@pytest.mark.unit
def test_fetch_orchestrator_scores_fresh_sources(tmp_path):
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    agent._fetch_raw_data = lambda name: [{"raw": name}]
    agent._score_raw_data = lambda name, raw: {"articles": [{"url": f"http://{name}"}]}

    ctx = _ctx(tmp_path, steps_to_run=set(FETCH_STEPS))
    result = agent._phase_fetch(ctx)

    assert set(result.keys()) == set(FETCH_STEPS)
    for name in FETCH_STEPS:
        assert result[name]["articles"][0]["url"] == f"http://{name}"
        assert (ctx.steps_dir / f"{name}.json").exists()


@pytest.mark.unit
def test_fetch_orchestrator_loads_cached_sources(tmp_path):
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    fetch_calls = []
    agent._fetch_raw_data = lambda name: fetch_calls.append(name) or [{"raw": name}]
    agent._score_raw_data = lambda name, raw: {"articles": []}

    ctx = _ctx(tmp_path, steps_to_run=set(FETCH_STEPS))
    for name in FETCH_STEPS:
        (ctx.steps_dir / f"{name}.json").write_text(
            json.dumps({"articles": [{"url": f"http://cached-{name}"}], "fetched_at": "t"}),
            encoding="utf-8")

    result = agent._phase_fetch(ctx)
    assert fetch_calls == []                       # all cached → no raw fetch
    assert result["hn"]["articles"][0]["url"] == "http://cached-hn"


@pytest.mark.unit
def test_fetch_orchestrator_aborts_when_fewer_than_two_succeed(tmp_path):
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())

    def only_hn(name):
        if name == "hn":
            return [{"raw": "hn"}]
        raise RuntimeError("fetch failed")

    agent._fetch_raw_data = only_hn
    agent._score_raw_data = lambda name, raw: {"articles": [{"url": "http://hn"}]}

    alerts = []
    ctx = _ctx(tmp_path, steps_to_run=set(FETCH_STEPS))
    ctx.notify_fn = lambda m: alerts.append(m) or True

    result = agent._phase_fetch(ctx)
    assert result is None                          # < 2 succeeded → abort
    assert alerts and "Fetch" in alerts[0]


@pytest.mark.unit
def test_fetch_orchestrator_one_raw_failure_does_not_block_others(tmp_path):
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())

    def fail_reddit(name):
        if name == "reddit":
            raise RuntimeError("boom")
        return [{"raw": name}]

    agent._fetch_raw_data = fail_reddit
    agent._score_raw_data = lambda name, raw: {"articles": [{"url": f"http://{name}"}]}

    ctx = _ctx(tmp_path, steps_to_run=set(FETCH_STEPS))
    result = agent._phase_fetch(ctx)
    assert "reddit" not in result                  # failed source absent
    assert set(result.keys()) == set(FETCH_STEPS) - {"reddit"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/agents/test_fetch_orchestrator.py -v`
Expected: FAILs — the current `_phase_fetch` returns scored data but the tests assert the new structure (e.g., `fetch_calls == []` when cached) and the cached-load behavior; some may pass and some fail. (The point: they pin the orchestrator contract. If ALL pass against the old code, that's fine too — but Step 5 still applies.) If imports fail, that's a real failure to fix.

- [ ] **Step 3: Re-add the `decide`/`Verdict` import**

In `agents/daily_brief/agent.py`, find:
```python
from .step import StepStatus
```
Replace with:
```python
from .step import StepStatus
from .step_cache import Verdict, decide
```

- [ ] **Step 4: Rewrite `_phase_fetch`**

Replace the ENTIRE existing `_phase_fetch` method with exactly:

```python
    def _phase_fetch(self, ctx: _RunContext) -> dict[str, dict] | None:
        """Orchestrator：並行預抓 raw（RUN-verdict 來源）→ 序列評分（SourceStep.run）→ ≥2 門檻。"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from .steps.source import SourceStep

        sources = {n: SourceStep(n, self._score_raw_data) for n in FETCH_STEPS}

        # 哪些來源該重抓 raw（verdict == RUN）。LOAD/SKIP 不需網路 I/O。
        to_fetch = [
            n
            for n in FETCH_STEPS
            if decide(
                n in ctx.steps_to_run,
                (ctx.steps_dir / f"{n}.json").exists(),
                n in ctx.force_steps,
            )
            is Verdict.RUN
        ]

        # Stage 1（並行）：純網路 I/O，無 LLM。
        raws: dict[str, list] = {}
        with ThreadPoolExecutor(max_workers=len(FETCH_STEPS) or 1) as executor:
            futures = {executor.submit(self._fetch_raw_data, n): n for n in to_fetch}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    raws[name] = future.result()
                except Exception as exc:
                    logger.warning("Step %-8s: 原始資料抓取失敗 — %s", name, exc)

        # Stage 2（序列）：評分序列化，避免 LM Studio 並行 HTTP 400。
        source_data: dict[str, dict] = {}
        for name in FETCH_STEPS:
            outcome = sources[name].run(ctx, raws.get(name))
            if outcome.value is not None:
                source_data[name] = outcome.value

        fetch_failed = [n for n in to_fetch if n not in source_data]
        success_count = len(source_data)
        if success_count < 2 and ctx.steps_to_run.intersection(set(FETCH_STEPS)):
            msg = (
                f"⚠️ Daily Brief Fetch 嚴重失敗（{ctx.today}）\n"
                f"成功：{success_count}/{len(FETCH_STEPS)}，失敗：{fetch_failed}\n"
                "Pipeline 停止。"
            )
            ctx.notify_fn(msg)
            logger.error("Fetch 成功 %d/%d，低於門檻，pipeline 停止", success_count, len(FETCH_STEPS))
            return None

        return source_data
```

- [ ] **Step 5: Run the orchestrator tests, then the full suite**

Run: `python3 -m pytest tests/agents/test_fetch_orchestrator.py -v`
Expected: PASS (4 passed).

Run: `python3 -m pytest tests/ -q`
Expected: all green (was 272 passed, 1 skipped; +5 SourceStep +4 orchestrator = 281 passed, 1 skipped).

Confirm the dead inline helpers are gone — the old `_phase_fetch` had a nested `_load_or_fetch_raw` and `_make_fn`; the rewrite removes them.

Run: `grep -n "_load_or_fetch_raw\|_make_fn" agents/daily_brief/agent.py`
Expected: empty.

- [ ] **Step 6: Commit**

```bash
git add agents/daily_brief/agent.py tests/agents/test_fetch_orchestrator.py
git commit -m "refactor: make _phase_fetch a thin orchestrator over SourceStep"
```

---

## Task 3: Fold Fix C into a force-computation helper

Extract the run() Fix C block into a module-level helper `_compute_force_steps` for locality. Behavior unchanged.

**Files:**
- Modify: `agents/daily_brief/agent.py` (add helper; call it in `run()`)
- Test: `tests/agents/test_fetch_orchestrator.py` (append — reuses that file for agent-level helper tests) OR a new `tests/agents/test_force_computation.py`

- [ ] **Step 1: Create `tests/agents/test_force_computation.py` with exactly:**

```python
"""_compute_force_steps — folds Fix C stale-detection into force-step computation."""

import json
import time
from pathlib import Path

import pytest

from agents.daily_brief.agent import _compute_force_steps, FETCH_STEPS


def _write(p: Path, mtime: float | None = None):
    p.write_text(json.dumps({"x": 1}), encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(p, (mtime, mtime))


@pytest.mark.unit
def test_compute_force_steps_returns_explicit_force_when_only_mode(tmp_path):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    # only_steps non-empty → Fix C disabled, explicit force returned as-is
    result = _compute_force_steps({"hn"}, {"compress"}, steps_dir, tmp_path)
    assert result == {"compress"}


@pytest.mark.unit
def test_compute_force_steps_adds_stale_downstream(tmp_path):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    # downstream compress older than a source artifact → compress force-added
    _write(steps_dir / "compress.json", mtime=time.time() - 100)
    _write(steps_dir / "hn.json", mtime=time.time())
    result = _compute_force_steps(set(), set(), steps_dir, tmp_path)
    assert "compress" in result


@pytest.mark.unit
def test_compute_force_steps_no_change_when_fresh(tmp_path):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    _write(steps_dir / "hn.json", mtime=time.time() - 100)
    _write(steps_dir / "compress.json", mtime=time.time())
    result = _compute_force_steps(set(), {"notify"}, steps_dir, tmp_path)
    assert result == {"notify"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/agents/test_force_computation.py -v`
Expected: FAIL — `ImportError: cannot import name '_compute_force_steps'`

- [ ] **Step 3: Add the helper and call it from `run()`**

In `agents/daily_brief/agent.py`, add this module-level function immediately ABOVE the existing `def _detect_stale_downstream(` function:

```python
def _compute_force_steps(
    only_steps: set[str], force_steps: set[str], steps_dir: Path, day_dir: Path
) -> set[str]:
    """Fix C：非 --only 模式下，source artifact 比下游新時，把過期下游加進 force_steps。"""
    if only_steps:
        return force_steps
    stale = _detect_stale_downstream(steps_dir, day_dir)
    newly_forced = stale - force_steps
    if newly_forced:
        logger.warning("來源 artifact 比下游新，自動強制重跑：%s", sorted(newly_forced))
    return force_steps | newly_forced
```

Then in `run()`, replace this block:
```python
        # Fix C: source artifact 比下游新時自動強制重跑下游
        if not only_steps:
            stale = _detect_stale_downstream(steps_dir, day_dir)
            newly_forced = stale - force_steps
            if newly_forced:
                logger.warning(
                    "來源 artifact 比下游新，自動強制重跑：%s", sorted(newly_forced)
                )
                force_steps = force_steps | newly_forced
```
with:
```python
        # Fix C: source artifact 比下游新時自動強制重跑下游
        force_steps = _compute_force_steps(only_steps, force_steps, steps_dir, day_dir)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/agents/test_force_computation.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all green (281 + 3 = 284 passed, 1 skipped).

- [ ] **Step 6: Commit**

```bash
git add agents/daily_brief/agent.py tests/agents/test_force_computation.py
git commit -m "refactor: fold Fix C stale-detection into _compute_force_steps helper"
```

---

## Task 4: Final sweep + docs

**Files:**
- Modify: `CLAUDE.md`
- Verify: lint + no remaining `_phase_*`

- [ ] **Step 1: Confirm no `_phase_*` methods remain**

Run: `grep -rn "def _phase_" agents/daily_brief/agent.py`
Expected: empty (every phase is now a Step or orchestrator).

- [ ] **Step 2: Run the interface lints**

Run: `python3 lint/check_agent_interface.py && python3 lint/check_fetcher_interface.py`
Expected: both pass.

- [ ] **Step 3: Update `CLAUDE.md`**

Find:
```
已遷移：compress / dedup / enrich / digest / judge / report / save / notify（`steps/*.py`）；judge 的 completeness 回饋迴圈已提昇進 `run()`（`Step.run(force=True)` 觸發無條件重跑，`supervisor.reflect_for_completeness` 取代舊 `run_judge_feedback`）。尚未遷移：fetch orchestrator（5 源兩階段 Source Step）與 Fix C 歸位，見 `docs/superpowers/plans/2026-06-21-deep-step-plan3-judge-feedback.md` 的 Plan 4。
```
Replace with:
```
全部步驟已遷移為深 `Step`：5 個 Source（hatena/hn/reddit/security/rss，`steps/source.py` 的 `SourceStep`）+ dedup / compress / enrich / digest / judge / report / save / notify（`steps/*.py`）。`fetch` 維持 orchestrator（並行預抓 raw → 序列 `SourceStep.run` 評分 → ≥2 門檻）；judge 的 completeness 回饋已在 `run()` 顯式編排（`Step.run(force=True)` + `supervisor.reflect_for_completeness`）；Fix C 收進 `_compute_force_steps`。`run()` 是純地圖，無 `_phase_*`。
```

- [ ] **Step 4: Run the full suite one last time**

Run: `python3 -m pytest tests/ -q`
Expected: all green (284 passed, 1 skipped).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record completed deep-Step refactor (fetch orchestrator + SourceStep)"
```

---

## Self-Review

**Spec coverage:**
- `SourceStep` (Step subclass, per-instance name, `_guard=input is not None`, `fetched_at` stamp): T1. ✓
- `_phase_fetch` thin orchestrator (parallel raw / serial `run()` / ≥2 gate / one-failure-isolation), `decide`/`Verdict` re-added, dead inline helpers removed: T2. ✓
- Two-stage preserved (parallel raw, serial score) without a custom Step lifecycle: T2 orchestrator. ✓
- Fix C folded into `_compute_force_steps` (behavior unchanged): T3. ✓
- No `_phase_*` remain; lint passes; docs updated: T4. ✓

**Placeholder scan:** No TBD/TODO. Full code in every step; deletions by signature/region. ✓

**Type consistency:** `SourceStep(name, score_fn)` injects `_score_raw_data(name, raw) -> dict` (kept). Orchestrator uses `decide(...) is Verdict.RUN`, `SourceStep.run(ctx, raw) -> StepOutcome`, `.value`/`.status`. `_compute_force_steps(only_steps, force_steps, steps_dir, day_dir) -> set[str]` wraps the kept `_detect_stale_downstream`. ✓

---

## Done state (after Plan 4)

The deep-Step refactor is complete: `run()` is a flat map of orchestrators + Step calls; all 13 leaf steps (5 Sources + 8 middle/terminal) are deep `Step`s behind `run(ctx, input) -> StepOutcome`; gating (`decide`), artifact I/O (`codecs`), retry (`supervisor`), and defaults live behind the seam; the candidate-3 judge-feedback leak is gone. Remaining orchestrators (`run`, `fetch`) are intentional maps, not shallow modules.
