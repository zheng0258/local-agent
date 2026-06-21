# Deep Step Abstraction — Plan 2: Linear Middle Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the six linear-middle phases (`dedup`, `digest`, `report`, `save`, `notify`, `enrich`) from hand-rolled `_phase_*` methods to deep `Step` subclasses, reusing the `Step` base + codecs built in Plan 1, leaving every test green.

**Architecture:** Each step becomes a `Step` subclass under `agents/daily_brief/steps/`. The heavy logic stays on `DailyBriefAgent` as `_run_*` helpers (all directly unit-tested — untouched) and is injected into the step, exactly as `CompressStep` injects `_run_compress`. Steps with a return-shape ≠ persist-shape (digest) override `_load`; pass-through steps (dedup, enrich) set `_default` to return their input; terminal steps (report/save/notify) use `TextCodec`/`SentinelCodec` and return `None`. `run()` keeps explicit linear wiring.

**Tech Stack:** Python 3.10, dataclasses, pytest (`@pytest.mark.unit`).

---

## Scope & decisions (carried from the grilling session)

- **In scope (6 steps):** dedup, digest, report, save, notify, enrich.
- **Out of scope — deferred to Plan 3:** `judge` (entangled with the completeness<3 feedback loop = candidate 3; migrate together), the `fetch` orchestrator (5 two-stage Source Steps), and folding Fix C `_detect_stale_downstream` into orchestrator force-computation. `_phase_judge` and `_phase_fetch` stay as-is this plan.
- **`_run_*` helpers stay on the agent, injected** — `_run_dedup` does not exist yet (dedup logic is inline in `_phase_dedup`); `DedupStep` owns the vector-store production directly (it needs no agent state). `_filter_source_data_by_urls` stays a module function in `agent.py`, imported by `DedupStep._load`.
- **Pass-through `_default`:** dedup and enrich return `input` on SKIP/FAILED (the un-deduped / un-enriched data flows on), matching today's `_phase_dedup`/`_phase_enrich` which `return source_data` / `return compress_data`.
- **Behavior note (dedup):** today's `_phase_dedup` runs the vector-store logic *without* `supervisor.run_step`, so a dedup exception crashes the pipeline. Going through the `Step` template wraps it in `supervisor.run_step` (config `dedup`: `max_retries=1`, `plain`). A dedup exception is now caught → alerted → returns `_default(input)` = pass-through. This is an intentional resilience improvement consistent with "a single failure doesn't block the pipeline"; it is the only behavior change in this plan.
- **Tuple inputs:** `report` takes `(compress_data, digests)`; `run()` passes a 2-tuple, `_produce` unpacks. (Matches the judge tuple-input pattern planned for Plan 3.)
- **Order (ascending risk):** digest → report → save → notify → dedup → enrich. enrich is last because it also migrates 3 existing `_phase_enrich` tests.

## Reference: kept agent helpers (do NOT modify — all directly unit-tested)

```python
def _run_digest(self, compress_data: dict, reflect_context: str = "") -> tuple[list[dict], dict]   # → (digests, digest_data)
def _run_report(self, compress_data: dict, digests: list[dict], today: str, reflect_context: str = "") -> str
def _run_save(self, day_dir: Path, today: str, digests: list[dict]) -> None
def _notify(self, digests: list[dict], today: str, steps_dir: Path | None = None, reflect_context: str = "") -> bool
def _run_enrich(self, compress_data: dict) -> dict          # NOTE: no reflect_context param
# module-level in agent.py:
def _filter_source_data_by_urls(source_data: dict, kept_urls: set) -> dict
```

`run()` current wiring (agent.py ~line 119-133):

```python
        source_data = self._phase_fetch(ctx)                 # Plan 3 — leave
        if source_data is None:
            return "Pipeline 中止：fetch 成功不足（需 ≥ 2）"
        source_data = _filter_top_articles(source_data)
        source_data = self._phase_dedup(ctx, source_data)    # Task 5
        from .steps.compress import CompressStep             # Plan 1
        compress_data = CompressStep(
            self._run_compress, self._check_source_health
        ).run(ctx, source_data).value
        enrich_data = self._phase_enrich(ctx, compress_data) # Task 6
        digests = self._phase_digest(ctx, enrich_data)       # Task 1
        enrich_data, digests = self._phase_judge(ctx, enrich_data, digests)  # Plan 3 — leave
        self._phase_report(ctx, enrich_data, digests)        # Task 2
        self._phase_save(ctx, digests)                       # Task 3
        self._phase_notify(ctx, digests)                     # Task 4
```

When deleting a `_phase_*` method, delete the entire method (from its `def` line through its final `return`/end), nothing else. Keep all `_run_*` helpers and other phases intact.

---

## Task 1: DigestStep

**Files:**
- Create: `agents/daily_brief/steps/digest.py`
- Test: `tests/agents/test_digest_step.py`
- Modify: `agents/daily_brief/agent.py` (wire `run()`, delete `_phase_digest`)

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_digest_step.py
"""DigestStep — wraps _run_digest; persist≠value (persist digest_data, pass digests)."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.digest import DigestStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn(reflect_context=""))


def _ctx(tmp_path, steps_to_run={"digest"}, force=set()):
    return SimpleNamespace(steps_dir=tmp_path, day_dir=tmp_path,
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_FakeSupervisor())


@pytest.mark.unit
def test_digest_step_persists_digest_data_passes_digests(tmp_path):
    digests = [{"title": "A", "url": "http://a", "_source": "hn"}]
    digest_data = {"generated_at": "t", "digests": digests}

    def fake_run_digest(compress_data, reflect_context=""):
        return digests, digest_data

    outcome = DigestStep(fake_run_digest).run(_ctx(tmp_path), {"hn": {"articles": [1]}})

    assert outcome.status is StepStatus.RAN
    assert outcome.value == digests                       # passes digests list
    assert JsonCodec().read(tmp_path / "digest.json") == digest_data  # persists full data


@pytest.mark.unit
def test_digest_step_load_returns_digests_field(tmp_path):
    digests = [{"title": "X", "url": "http://x"}]
    JsonCodec().write(tmp_path / "digest.json", {"generated_at": "t", "digests": digests})
    outcome = DigestStep(lambda *a, **k: ([], {})).run(_ctx(tmp_path), {"hn": {}})
    assert outcome.status is StepStatus.LOADED
    assert outcome.value == digests


@pytest.mark.unit
def test_digest_step_default_is_empty_list(tmp_path):
    outcome = DigestStep(lambda *a, **k: ([], {})).run(
        _ctx(tmp_path, steps_to_run=set()), {"hn": {}})
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agents/test_digest_step.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.daily_brief.steps.digest'`

- [ ] **Step 3: Write the implementation**

```python
# agents/daily_brief/steps/digest.py
"""DigestStep — 跨來源深度摘要。

producer 注入自 DailyBriefAgent._run_digest（回傳 (digests, digest_data)）；
本檔負責 gating + artifact I/O。persist 全份 digest_data，下游只拿 digests list。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..step import Step, StepOutput


class DigestStep(Step):
    name = "digest"

    def __init__(self, run_digest: Callable[..., tuple]) -> None:
        self._run_digest = run_digest

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "digest.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        digests, digest_data = self._run_digest(input, reflect_context=reflect_context)
        return StepOutput(persist=digest_data, value=digests)

    def _load(self, decoded, input):
        return decoded.get("digests", [])

    def _default(self, input):
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agents/test_digest_step.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Wire into `run()` and delete `_phase_digest`**

In `agents/daily_brief/agent.py`, find in `run()`:

```python
        digests = self._phase_digest(ctx, enrich_data)
```

Replace with:

```python
        from .steps.digest import DigestStep
        digests = DigestStep(self._run_digest).run(ctx, enrich_data).value
```

Then delete the entire `_phase_digest` method (from `def _phase_digest(self, ctx: _RunContext, compress_data: dict) -> list[dict]:` through its final `return digests`). Leave `_run_digest`, `_phase_judge`, and everything else intact.

- [ ] **Step 6: Verify the full suite is green and no dangling references**

Run: `python3 -m pytest tests/ -q`
Expected: all green (suite was 249 passed, 1 skipped at the start of Plan 2; new digest tests add 3).

Run: `grep -rn "_phase_digest" agents/ tests/`
Expected: empty.

- [ ] **Step 7: Commit**

```bash
git add agents/daily_brief/steps/digest.py tests/agents/test_digest_step.py agents/daily_brief/agent.py
git commit -m "refactor: migrate digest phase to deep DigestStep"
```

---

## Task 2: ReportStep

**Files:**
- Create: `agents/daily_brief/steps/report.py`
- Test: `tests/agents/test_report_step.py`
- Modify: `agents/daily_brief/agent.py` (wire `run()`, delete `_phase_report`)

`ReportStep` uses `TextCodec` (writes `report.md`), takes a 2-tuple input `(compress_data, digests)`, guards on `digests`, returns `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_report_step.py
"""ReportStep — TextCodec, tuple input (compress, digests), value=None."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import TextCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.report import ReportStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn(reflect_context=""))


def _ctx(tmp_path, steps_to_run={"report"}, force=set()):
    return SimpleNamespace(steps_dir=tmp_path, day_dir=tmp_path,
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_FakeSupervisor())


@pytest.mark.unit
def test_report_step_writes_markdown_to_report_md(tmp_path):
    captured = {}

    def fake_run_report(compress_data, digests, today, reflect_context=""):
        captured["args"] = (compress_data, digests, today)
        return "# Trend Report\n\nbody"

    outcome = ReportStep(fake_run_report, today="2026-06-21").run(
        _ctx(tmp_path), ({"hn": {}}, [{"url": "http://a"}]))

    assert outcome.status is StepStatus.RAN
    assert outcome.value is None
    assert TextCodec().read(tmp_path / "report.md") == "# Trend Report\n\nbody"
    assert captured["args"] == ({"hn": {}}, [{"url": "http://a"}], "2026-06-21")


@pytest.mark.unit
def test_report_step_guard_blocks_when_no_digests(tmp_path):
    outcome = ReportStep(lambda *a, **k: "x", today="2026-06-21").run(
        _ctx(tmp_path), ({"hn": {}}, []))   # empty digests → guard blocks
    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "report.md").exists()


@pytest.mark.unit
def test_report_step_artifact_path_is_day_dir(tmp_path):
    step = ReportStep(lambda *a, **k: "x", today="2026-06-21")
    assert step.artifact_path(SimpleNamespace(day_dir=tmp_path)) == tmp_path / "report.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agents/test_report_step.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.daily_brief.steps.report'`

- [ ] **Step 3: Write the implementation**

```python
# agents/daily_brief/steps/report.py
"""ReportStep — 最終趨勢報告（純 markdown，寫 report.md）。

input 是 (compress_data, digests) 二元組；producer 注入自 _run_report。
artifact 在 day_dir（非 steps_dir），用 TextCodec。value 為 None（終端步）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..codecs import TextCodec
from ..step import Step, StepOutput


class ReportStep(Step):
    name = "report"
    codec = TextCodec()

    def __init__(self, run_report: Callable[..., str], today: str) -> None:
        self._run_report = run_report
        self._today = today

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "report.md"

    def _guard(self, ctx, input) -> bool:
        _compress, digests = input
        return bool(digests)

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        compress_data, digests = input
        md = self._run_report(compress_data, digests, self._today, reflect_context=reflect_context)
        return StepOutput(persist=md, value=None)

    def _default(self, input):
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agents/test_report_step.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Wire into `run()` and delete `_phase_report`**

In `agents/daily_brief/agent.py`, find in `run()`:

```python
        self._phase_report(ctx, enrich_data, digests)
```

Replace with:

```python
        from .steps.report import ReportStep
        ReportStep(self._run_report, ctx.today).run(ctx, (enrich_data, digests))
```

Then delete the entire `_phase_report` method (from `def _phase_report(self, ctx: _RunContext, compress_data: dict, digests: list[dict]) -> None:` through its end). Leave `_run_report` intact.

- [ ] **Step 6: Verify full suite green + no dangling references**

Run: `python3 -m pytest tests/ -q`
Expected: all green.

Run: `grep -rn "_phase_report" agents/ tests/`
Expected: empty.

- [ ] **Step 7: Commit**

```bash
git add agents/daily_brief/steps/report.py tests/agents/test_report_step.py agents/daily_brief/agent.py
git commit -m "refactor: migrate report phase to deep ReportStep"
```

---

## Task 3: SaveStep

**Files:**
- Create: `agents/daily_brief/steps/save.py`
- Test: `tests/agents/test_save_step.py`
- Modify: `agents/daily_brief/agent.py` (wire `run()`, delete `_phase_save`)

`SaveStep` uses `SentinelCodec` (`vault.done`), guards on `digests` AND `report.md` existing, runs the side-effecting `_run_save`, returns `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_save_step.py
"""SaveStep — SentinelCodec(vault.done), guards on digests + report.md, side-effect _run_save."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.save import SaveStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn())


def _ctx(tmp_path, steps_to_run={"save"}, force=set()):
    return SimpleNamespace(steps_dir=tmp_path, day_dir=tmp_path,
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_FakeSupervisor())


@pytest.mark.unit
def test_save_step_runs_and_touches_sentinel(tmp_path):
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")
    captured = {}

    def fake_run_save(day_dir, today, digests):
        captured["args"] = (day_dir, today, digests)

    outcome = SaveStep(fake_run_save, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])

    assert outcome.status is StepStatus.RAN
    assert (tmp_path / "vault.done").exists()
    assert captured["args"] == (tmp_path, "2026-06-21", [{"url": "http://a"}])


@pytest.mark.unit
def test_save_step_guard_blocks_without_report_md(tmp_path):
    # digests present but no report.md → guard blocks
    outcome = SaveStep(lambda *a: None, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])
    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "vault.done").exists()


@pytest.mark.unit
def test_save_step_loads_when_sentinel_exists(tmp_path):
    (tmp_path / "vault.done").touch()
    called = {"n": 0}

    def fake_run_save(day_dir, today, digests):
        called["n"] += 1

    outcome = SaveStep(fake_run_save, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])
    assert outcome.status is StepStatus.LOADED
    assert called["n"] == 0          # already saved → no re-run
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agents/test_save_step.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.daily_brief.steps.save'`

- [ ] **Step 3: Write the implementation**

```python
# agents/daily_brief/steps/save.py
"""SaveStep — 把 report.md + digest 存進 Obsidian vault。

SentinelCodec：成功後 touch vault.done（存在 = 已存過 → 下次 LOAD 略過）。
guard：需有 digests 且 report.md 已存在。producer 注入自 _run_save（純副作用）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..codecs import SentinelCodec
from ..step import Step, StepOutput


class SaveStep(Step):
    name = "save"
    codec = SentinelCodec()

    def __init__(self, run_save: Callable[..., None], today: str) -> None:
        self._run_save = run_save
        self._today = today

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "vault.done"

    def _guard(self, ctx, input) -> bool:
        return bool(input) and (ctx.day_dir / "report.md").exists()

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        self._run_save(ctx.day_dir, self._today, input)
        return StepOutput(persist=None, value=None)

    def _default(self, input):
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agents/test_save_step.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Wire into `run()` and delete `_phase_save`**

In `agents/daily_brief/agent.py`, find in `run()`:

```python
        self._phase_save(ctx, digests)
```

Replace with:

```python
        from .steps.save import SaveStep
        SaveStep(self._run_save, ctx.today).run(ctx, digests)
```

Then delete the entire `_phase_save` method. Leave `_run_save` intact.

- [ ] **Step 6: Verify full suite green + no dangling references**

Run: `python3 -m pytest tests/ -q`
Expected: all green.

Run: `grep -rn "_phase_save" agents/ tests/`
Expected: empty.

- [ ] **Step 7: Commit**

```bash
git add agents/daily_brief/steps/save.py tests/agents/test_save_step.py agents/daily_brief/agent.py
git commit -m "refactor: migrate save phase to deep SaveStep"
```

---

## Task 4: NotifyStep

**Files:**
- Create: `agents/daily_brief/steps/notify.py`
- Test: `tests/agents/test_notify_step.py`
- Modify: `agents/daily_brief/agent.py` (wire `run()`, delete `_phase_notify`)

`NotifyStep` uses `SentinelCodec` (`telegram.done`), guards on `digests` AND `report.md`, calls `_notify` which returns `bool`; on `False` it raises so the supervisor records FAILED and the sentinel is NOT written.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_notify_step.py
"""NotifyStep — SentinelCodec(telegram.done); _notify False → raise → FAILED, no sentinel."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.notify import NotifyStep


class _FakeSupervisor:
    """Mimics supervisor: calls fn(); on exception returns success=False."""

    def run_step(self, name, fn, force=False):
        try:
            return SimpleNamespace(success=True, output=fn(reflect_context=""))
        except Exception:
            return SimpleNamespace(success=False, output=None)


def _ctx(tmp_path, steps_to_run={"notify"}, force=set()):
    return SimpleNamespace(steps_dir=tmp_path, day_dir=tmp_path,
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_FakeSupervisor())


@pytest.mark.unit
def test_notify_step_success_touches_sentinel(tmp_path):
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")
    captured = {}

    def fake_notify(digests, today, steps_dir=None, reflect_context=""):
        captured["digests"] = digests
        return True

    outcome = NotifyStep(fake_notify, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])

    assert outcome.status is StepStatus.RAN
    assert (tmp_path / "telegram.done").exists()
    assert captured["digests"] == [{"url": "http://a"}]


@pytest.mark.unit
def test_notify_step_false_result_fails_without_sentinel(tmp_path):
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")

    def fake_notify(digests, today, steps_dir=None, reflect_context=""):
        return False   # send failed

    outcome = NotifyStep(fake_notify, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])

    assert outcome.status is StepStatus.FAILED
    assert not (tmp_path / "telegram.done").exists()


@pytest.mark.unit
def test_notify_step_guard_blocks_without_report_md(tmp_path):
    outcome = NotifyStep(lambda *a, **k: True, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])
    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "telegram.done").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agents/test_notify_step.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.daily_brief.steps.notify'`

- [ ] **Step 3: Write the implementation**

```python
# agents/daily_brief/steps/notify.py
"""NotifyStep — 發送 Telegram 推播（兩封）。

SentinelCodec：成功後 touch telegram.done。guard：需 digests 且 report.md。
producer 注入自 _notify（回 bool）；回 False 視為失敗 → raise，讓 supervisor 記 FAILED、
sentinel 不寫入（與舊 _phase_notify 一致：失敗用 --force notify 重試）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..codecs import SentinelCodec
from ..step import Step, StepOutput


class NotifyStep(Step):
    name = "notify"
    codec = SentinelCodec()

    def __init__(self, notify: Callable[..., bool], today: str) -> None:
        self._notify = notify
        self._today = today

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "telegram.done"

    def _guard(self, ctx, input) -> bool:
        return bool(input) and (ctx.day_dir / "report.md").exists()

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        ok = self._notify(input, self._today, steps_dir=ctx.steps_dir, reflect_context=reflect_context)
        if not ok:
            raise RuntimeError("Telegram 訊息發送失敗")
        return StepOutput(persist=None, value=None)

    def _default(self, input):
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agents/test_notify_step.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Wire into `run()` and delete `_phase_notify`**

In `agents/daily_brief/agent.py`, find in `run()`:

```python
        self._phase_notify(ctx, digests)
```

Replace with:

```python
        from .steps.notify import NotifyStep
        NotifyStep(self._notify, ctx.today).run(ctx, digests)
```

Then delete the entire `_phase_notify` method. Leave `_notify` intact.

- [ ] **Step 6: Verify full suite green + no dangling references**

Run: `python3 -m pytest tests/ -q`
Expected: all green.

Run: `grep -rn "_phase_notify" agents/ tests/`
Expected: empty.

- [ ] **Step 7: Commit**

```bash
git add agents/daily_brief/steps/notify.py tests/agents/test_notify_step.py agents/daily_brief/agent.py
git commit -m "refactor: migrate notify phase to deep NotifyStep"
```

---

## Task 5: DedupStep

**Files:**
- Create: `agents/daily_brief/steps/dedup.py`
- Test: `tests/agents/test_dedup_step.py`
- Modify: `agents/daily_brief/agent.py` (wire `run()`, delete `_phase_dedup`)

`DedupStep` owns the vector-store production directly (no agent state needed). `_load` re-filters `input` by the persisted `kept_urls` (on-disk schema unchanged). `_default` returns `input` (pass-through). See the "Behavior note (dedup)" in Scope — going through the supervisor turns a crash into a caught/alerted pass-through.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_dedup_step.py
"""DedupStep — _load re-filters by kept_urls; _default passes through; _produce persists artifact."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.dedup import DedupStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn())


def _ctx(tmp_path, steps_to_run={"dedup"}, force=set()):
    return SimpleNamespace(steps_dir=tmp_path, day_dir=tmp_path, today="2026-06-21",
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_FakeSupervisor())


_SRC = {
    "hn": {"articles": [
        {"url": "http://keep", "title": "k"},
        {"url": "http://drop", "title": "d"},
    ]},
}


@pytest.mark.unit
def test_dedup_step_load_refilters_by_kept_urls(tmp_path):
    JsonCodec().write(tmp_path / "dedup.json", {"kept_urls": ["http://keep"]})
    outcome = DedupStep().run(_ctx(tmp_path), _SRC)
    assert outcome.status is StepStatus.LOADED
    urls = [a["url"] for a in outcome.value["hn"]["articles"]]
    assert urls == ["http://keep"]


@pytest.mark.unit
def test_dedup_step_default_passes_input_through(tmp_path):
    outcome = DedupStep().run(_ctx(tmp_path, steps_to_run=set()), _SRC)
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is _SRC          # pass-through


@pytest.mark.unit
def test_dedup_step_produce_persists_artifact_and_passes_filtered(tmp_path):
    filtered = {"hn": {"articles": [{"url": "http://keep", "title": "k"}]}}
    result = SimpleNamespace(total=2, kept=1, filtered_url=0, filtered_semantic=1,
                             kept_urls=["http://keep"], filtered_items=[])

    with patch("agents.daily_brief.steps.dedup.dedup_source_data",
               return_value=(filtered, result)), \
         patch("agents.daily_brief.steps.dedup.get_collection"), \
         patch("agents.daily_brief.steps.dedup.cleanup_old_records"), \
         patch("agents.daily_brief.steps.dedup.Qwen3Embedder"):
        outcome = DedupStep().run(_ctx(tmp_path), _SRC)

    assert outcome.status is StepStatus.RAN
    assert outcome.value == filtered
    saved = JsonCodec().read(tmp_path / "dedup.json")
    assert saved["kept_urls"] == ["http://keep"]
    assert saved["kept"] == 1 and saved["total"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agents/test_dedup_step.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.daily_brief.steps.dedup'`

- [ ] **Step 3: Write the implementation**

```python
# agents/daily_brief/steps/dedup.py
"""DedupStep — 語義去重（向量 embedding + cosine）。

無 LLM、無 agent 狀態：production 邏輯直接住 _produce。persist 的 kept_urls 等指標
維持原 on-disk schema；_load 用 kept_urls 重濾上游 source_data；_default 直接 pass-through。
向量庫相依以模組層 import 暴露，便於測試 patch。
"""

from __future__ import annotations

from pathlib import Path

from ..config import DEDUP_SIMILARITY_THRESHOLD, DEDUP_WINDOW_DAYS, VECTOR_DB_PATH
from ..step import Step, StepOutput
from tools.vector_store.client import cleanup_old_records, get_collection
from tools.vector_store.dedup import dedup_source_data
from tools.vector_store.embedder import Qwen3Embedder


class DedupStep(Step):
    name = "dedup"

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "dedup.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        VECTOR_DB_PATH.mkdir(parents=True, exist_ok=True)
        collection = get_collection(VECTOR_DB_PATH)
        cleanup_old_records(collection, DEDUP_WINDOW_DAYS)
        embedder = Qwen3Embedder()
        filtered_data, result = dedup_source_data(
            source_data=input,
            collection=collection,
            embedder=embedder,
            today=ctx.today,
            window_days=DEDUP_WINDOW_DAYS,
            threshold=DEDUP_SIMILARITY_THRESHOLD,
        )
        artifact_data = {
            "total": result.total,
            "kept": result.kept,
            "filtered_url": result.filtered_url,
            "filtered_semantic": result.filtered_semantic,
            "kept_urls": result.kept_urls,
            "filtered_items": result.filtered_items,
        }
        return StepOutput(persist=artifact_data, value=filtered_data)

    def _load(self, decoded, input):
        from ..agent import _filter_source_data_by_urls
        return _filter_source_data_by_urls(input, set(decoded.get("kept_urls", [])))

    def _default(self, input):
        return input
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agents/test_dedup_step.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Wire into `run()` and delete `_phase_dedup`**

In `agents/daily_brief/agent.py`, find in `run()`:

```python
        source_data = self._phase_dedup(ctx, source_data)
```

Replace with:

```python
        from .steps.dedup import DedupStep
        source_data = DedupStep().run(ctx, source_data).value
```

Then delete the entire `_phase_dedup` method (from `def _phase_dedup(self, ctx: _RunContext, source_data: dict) -> dict:` through its final `return filtered_data`). Leave `_filter_source_data_by_urls`, `_filter_top_articles`, and everything else intact.

- [ ] **Step 6: Verify full suite green + no dangling references**

Run: `python3 -m pytest tests/ -q`
Expected: all green.

Run: `grep -rn "_phase_dedup" agents/ tests/`
Expected: empty.

- [ ] **Step 7: Commit**

```bash
git add agents/daily_brief/steps/dedup.py tests/agents/test_dedup_step.py agents/daily_brief/agent.py
git commit -m "refactor: migrate dedup phase to deep DedupStep"
```

---

## Task 6: EnrichStep (+ migrate the 3 `_phase_enrich` tests)

**Files:**
- Create: `agents/daily_brief/steps/enrich.py`
- Test: `tests/agents/test_enrich_step.py` (REPLACE the 3 `_phase_enrich` tests with `EnrichStep` tests; KEEP the 8 `_run_enrich` tests unchanged)
- Modify: `agents/daily_brief/agent.py` (wire `run()`, delete `_phase_enrich`)

`EnrichStep` injects `_run_enrich` (note: `_run_enrich` has NO `reflect_context` param — `_produce` ignores it). `_default` returns `input` (pass-through). LOAD returns the decoded artifact directly (identity). The 3 existing `_phase_enrich` tests in `tests/agents/test_enrich_step.py` (lines 111-164) must be rewritten to drive `EnrichStep` with a fake supervisor that actually calls `fn()`.

- [ ] **Step 1: Write the failing test — create the EnrichStep tests AND migrate the phase tests**

First create `agents/daily_brief/steps/enrich.py` test expectations by REPLACING the entire `# ── _phase_enrich：idempotent ──` section (from line 111 `# ── _phase_enrich...` through the end of the file, line 165) in `tests/agents/test_enrich_step.py` with:

```python
# ── EnrichStep：idempotent（取代舊 _phase_enrich 測試）─────────────

from types import SimpleNamespace
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.enrich import EnrichStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn())


def _enrich_ctx(steps_dir, steps_to_run, force=set()):
    return SimpleNamespace(steps_dir=steps_dir, day_dir=steps_dir,
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_FakeSupervisor())


def test_enrich_step_loads_existing_artifact(tmp_path):
    agent = _make_agent()
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    saved = {"_meta": {}, "hn": {"articles": [{"comment_summary": "cached"}]}}
    (steps_dir / "enrich.json").write_text(json.dumps(saved), encoding="utf-8")

    ctx = _enrich_ctx(steps_dir, {"enrich"})
    outcome = EnrichStep(agent._run_enrich).run(ctx, _HN_COMPRESS)
    assert outcome.status is StepStatus.LOADED
    assert outcome.value["hn"]["articles"][0]["comment_summary"] == "cached"


def test_enrich_step_skips_when_not_in_steps_to_run(tmp_path):
    agent = _make_agent()
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()

    ctx = _enrich_ctx(steps_dir, {"digest"})
    outcome = EnrichStep(agent._run_enrich).run(ctx, _HN_COMPRESS)
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is _HN_COMPRESS          # pass-through default


def test_enrich_step_writes_artifact(tmp_path):
    agent = _make_agent()
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()

    ctx = _enrich_ctx(steps_dir, {"enrich"})
    with patch("tools.fetchers.hn_comments.fetch_comments", return_value=["c1"]):
        with patch("tools.fetchers.reddit_comments.fetch_comments", return_value=["rc1"]):
            EnrichStep(agent._run_enrich).run(ctx, _HN_COMPRESS)

    assert (steps_dir / "enrich.json").exists()
    saved = json.loads((steps_dir / "enrich.json").read_text())
    assert "_meta" in saved
    assert "enriched_at" in saved["_meta"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agents/test_enrich_step.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.daily_brief.steps.enrich'` (the 8 `_run_enrich` tests above still collect/pass; the 3 new EnrichStep tests fail on import).

- [ ] **Step 3: Write the implementation**

```python
# agents/daily_brief/steps/enrich.py
"""EnrichStep — 對 HN/Reddit *** 文章抓留言並 LLM 摘要社群觀點（best-effort）。

producer 注入自 _run_enrich（無 reflect_context；_produce 忽略它）。
LOAD 直接回 artifact（identity）；_default pass-through 上游 compress_data。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..step import Step, StepOutput


class EnrichStep(Step):
    name = "enrich"

    def __init__(self, run_enrich: Callable[[dict], dict]) -> None:
        self._run_enrich = run_enrich

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "enrich.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        enriched = self._run_enrich(input)
        return StepOutput(persist=enriched, value=enriched)

    def _default(self, input):
        return input
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agents/test_enrich_step.py -v`
Expected: PASS (8 `_run_enrich` tests + 3 EnrichStep tests = 11 passed)

- [ ] **Step 5: Wire into `run()` and delete `_phase_enrich`**

In `agents/daily_brief/agent.py`, find in `run()`:

```python
        enrich_data = self._phase_enrich(ctx, compress_data)
```

Replace with:

```python
        from .steps.enrich import EnrichStep
        enrich_data = EnrichStep(self._run_enrich).run(ctx, compress_data).value
```

Then delete the entire `_phase_enrich` method (from `def _phase_enrich(self, ctx: _RunContext, compress_data: dict) -> dict:` through its final `return enrich_data`). Leave `_run_enrich`, `_enrich_article` intact.

- [ ] **Step 6: Verify full suite green + no dangling references**

Run: `python3 -m pytest tests/ -q`
Expected: all green.

Run: `grep -rn "_phase_enrich" agents/ tests/`
Expected: empty.

- [ ] **Step 7: Commit**

```bash
git add agents/daily_brief/steps/enrich.py tests/agents/test_enrich_step.py agents/daily_brief/agent.py
git commit -m "refactor: migrate enrich phase to deep EnrichStep"
```

---

## Task 7: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (the Step paragraph under 核心設計原則, updated in Plan 1)

- [ ] **Step 1: Update the migration-status sentence**

In `CLAUDE.md`, find the sentence (added in Plan 1) that reads:

```
compress 已遷移（`steps/compress.py`）；其餘步驟與 fetch/judge-feedback orchestrator 見 `docs/superpowers/plans/2026-06-21-deep-step-abstraction.md` 的 Plan 2/3。
```

Replace it with:

```
已遷移：compress / dedup / enrich / digest / report / save / notify（`steps/*.py`）；尚未遷移：judge（與 completeness 回饋迴圈一併處理）與 fetch orchestrator，見 `docs/superpowers/plans/2026-06-21-deep-step-plan2-linear-middle.md` 完成記錄與 Plan 3。
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record Plan 2 step migrations in CLAUDE.md"
```

---

## Self-Review

**Spec coverage:**
- 6 linear-middle steps migrated, each `_phase_*` deleted, each wired into `run()`: digest (T1), report (T2), save (T3), notify (T4), dedup (T5), enrich (T6). ✓
- Return≠persist (digest `_load` + `StepOutput`): T1. ✓
- TextCodec (report): T2. SentinelCodec (save, notify): T3, T4. ✓
- Pass-through `_default` (dedup, enrich return input): T5, T6. ✓
- dedup `_load` re-filters by kept_urls, on-disk schema unchanged: T5. ✓
- notify False→raise→FAILED→no sentinel: T4. ✓
- Migrated 3 `_phase_enrich` tests → EnrichStep; kept 8 `_run_enrich` tests: T6. ✓
- judge + fetch deferred to Plan 3 (documented in Scope + T7). ✓ (not a gap)

**Placeholder scan:** No TBD/TODO. Every code step has full code. Deletions specified by method signature (robust to line shifts). ✓

**Type consistency:** All steps subclass `Step` (Plan 1) with `_produce(ctx, input, reflect_context="")`, `_load(decoded, input)`, `_guard(ctx, input)`, `_default(input)`, `artifact_path(ctx)`. `StepOutput(persist, value)` / `StepOutcome(status, value)` consistent. Injected helper signatures match the "Reference: kept agent helpers" block. Fake supervisors return `SimpleNamespace(success=, output=)`. `JsonCodec`/`TextCodec`/`SentinelCodec` from Plan 1 `codecs.py`. ✓

---

## Follow-up: Plan 3 (orchestrators)

- `fetch` orchestrator driving 5 two-stage Source Steps (`fetch_raw` parallel / `score` serial, ≥2 gate).
- Lift the judge→digest completeness feedback loop into `run()` (candidate 3): migrate `judge` to `JudgeStep` (tuple input `(compress, digests)`, `_guard` two-condition, `_judge-history.json` side write in `_produce`), delete the `retry_state` closure + prompt re-serialization + split writes; shrink `supervisor.run_judge_feedback` to `reflect_for_completeness(missed_urls)`.
- Fold Fix C `_detect_stale_downstream` into an orchestrator force-computation helper.
- Final dead-code sweep + `lint/check_agent_interface.py` / `check_fetcher_interface.py`.
