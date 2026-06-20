# Deep Step Abstraction — Plan 1: Infrastructure + Compress Reference Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deep `Step` module (gating + artifact I/O + supervisor wiring behind one `run()` interface) and prove it by migrating the `compress` phase, leaving every existing test green.

**Architecture:** A thin `Step` base class owns the template `decide() → SKIP/LOAD/RUN → codec I/O → delegate to supervisor → default`. Per-step variation lives in overridable internal seams (`_produce`, `_load`, `_guard`, `_default`) plus an injected `ArtifactCodec` (format adapter). The public interface is `run(ctx, input) -> StepOutcome`; everything else is internal. `run()` orchestration in `agent.py` stays explicit (no DAG engine). This plan migrates only `compress`; the other 12 steps and the two orchestrators (`fetch`, judge-feedback) follow in Plans 2 and 3.

**Tech Stack:** Python 3.10, dataclasses, `typing.Protocol`, pytest (`@pytest.mark.unit`).

---

## Design decisions locked in (from grilling session)

- **Scope:** 13 leaf Steps + 2 orchestrators (`run`, `fetch`). `fetch` is NOT a Step. This plan = infra + `compress`.
- **Style:** base class + template method; public interface = `run()`; artifact differences → `ArtifactCodec` sub-seam.
- **Naming:** `supervisor.py` already owns `StepResult` (retry-attempt result — untouched). The new Step-level return is `StepOutcome(status, value)`; the producer return is `StepOutput(persist, value)`.
- **Retry:** `supervisor.run_step` stays the retry engine; `Step.run` delegates the RUN branch to it. `_produce` has a uniform `(ctx, input, reflect_context="")` signature.
- **Cascade:** implicit. `_default(input)` is the value returned on both SKIP and FAILED. Pass-through steps (`dedup`/`enrich`/`judge`) return `input`; data producers (`compress`/`digest`) return `{}`/`[]`; terminal steps (`report`/`save`/`notify`) return `None`.
- **Side effects:** thin base class, zero lifecycle hooks. Side effects + secondary artifacts live inside `_produce`/`_load`.
- **Typed views:** live in `_load`, not the codec. (Candidate 2 — out of scope for this plan; `_load` defaults to identity.)
- **Codecs:** `JsonCodec`, `TextCodec`, `SentinelCodec`. Dumb format adapters: `exists` / `write` / `read`.

---

## File Structure

- **Create** `agents/daily_brief/codecs.py` — `ArtifactCodec` Protocol + `JsonCodec`, `TextCodec`, `SentinelCodec`. One responsibility: serialize/locate a single primary artifact.
- **Create** `agents/daily_brief/step.py` — `StepStatus`, `StepOutput`, `StepOutcome`, `Step` base class (the template). One responsibility: the cache-or-force lifecycle of one step.
- **Create** `agents/daily_brief/steps/__init__.py` — package marker for concrete steps.
- **Create** `agents/daily_brief/steps/compress.py` — `CompressStep` (first concrete step).
- **Modify** `agents/daily_brief/agent.py` — `run()` calls `CompressStep` instead of `_phase_compress`; delete `_phase_compress`.
- **Create** `tests/agents/test_codecs.py`, `tests/agents/test_step.py`, `tests/agents/test_compress_step.py`.

Concrete steps live under `agents/daily_brief/steps/` (one file per step) so Plans 2–3 add files without growing `agent.py`.

---

## Task 1: Artifact codecs

**Files:**
- Create: `agents/daily_brief/codecs.py`
- Test: `tests/agents/test_codecs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_codecs.py
"""ArtifactCodec adapters — dumb format/location seam for a step's primary artifact."""

import pytest

from agents.daily_brief.codecs import JsonCodec, SentinelCodec, TextCodec


@pytest.mark.unit
def test_json_codec_round_trip(tmp_path):
    path = tmp_path / "x.json"
    codec = JsonCodec()
    assert codec.exists(path) is False
    codec.write(path, {"a": 1, "z": "ä"})
    assert codec.exists(path) is True
    assert codec.read(path) == {"a": 1, "z": "ä"}


@pytest.mark.unit
def test_json_codec_writes_utf8_unescaped(tmp_path):
    path = tmp_path / "x.json"
    JsonCodec().write(path, {"k": "日本"})
    assert "日本" in path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_text_codec_round_trip(tmp_path):
    path = tmp_path / "report.md"
    codec = TextCodec()
    assert codec.exists(path) is False
    codec.write(path, "# hello")
    assert codec.exists(path) is True
    assert codec.read(path) == "# hello"


@pytest.mark.unit
def test_sentinel_codec_touches_and_reads_none(tmp_path):
    path = tmp_path / "done.flag"
    codec = SentinelCodec()
    assert codec.exists(path) is False
    codec.write(path, "ignored payload")
    assert codec.exists(path) is True
    assert codec.read(path) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agents/test_codecs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.daily_brief.codecs'`

- [ ] **Step 3: Write minimal implementation**

```python
# agents/daily_brief/codecs.py
"""ArtifactCodec — 一個 step 主 artifact 的格式/定位 seam（笨的格式轉換，不懂意義）。

typed view（解讀成 SourceCompress / Digest 等）不住這裡，住各 step 的 _load。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class ArtifactCodec(Protocol):
    def exists(self, path: Path) -> bool: ...
    def write(self, path: Path, obj: Any) -> None: ...
    def read(self, path: Path) -> Any: ...


class JsonCodec:
    """dict/list ↔ JSON 檔（UTF-8、不轉義、indent=2）。多數 step 用。"""

    def exists(self, path: Path) -> bool:
        return path.exists()

    def write(self, path: Path, obj: Any) -> None:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    def read(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))


class TextCodec:
    """純文字 ↔ 檔（report.md 用）。"""

    def exists(self, path: Path) -> bool:
        return path.exists()

    def write(self, path: Path, obj: Any) -> None:
        path.write_text(str(obj), encoding="utf-8")

    def read(self, path: Path) -> Any:
        return path.read_text(encoding="utf-8")


class SentinelCodec:
    """完成旗標（vault.done / telegram.done）。write=touch、read=None。"""

    def exists(self, path: Path) -> bool:
        return path.exists()

    def write(self, path: Path, obj: Any) -> None:
        path.touch()

    def read(self, path: Path) -> Any:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agents/test_codecs.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agents/daily_brief/codecs.py tests/agents/test_codecs.py
git commit -m "feat: add ArtifactCodec adapters (Json/Text/Sentinel)"
```

---

## Task 2: Step value types

**Files:**
- Create: `agents/daily_brief/step.py` (types only this task; base class added in Task 3)
- Test: `tests/agents/test_step.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_step.py
"""Step base class + value types."""

import pytest

from agents.daily_brief.step import StepOutcome, StepOutput, StepStatus


@pytest.mark.unit
def test_step_status_members():
    assert {s.name for s in StepStatus} == {"RAN", "LOADED", "SKIPPED", "FAILED"}


@pytest.mark.unit
def test_step_output_holds_persist_and_value():
    out = StepOutput(persist={"on": "disk"}, value=[1, 2, 3])
    assert out.persist == {"on": "disk"}
    assert out.value == [1, 2, 3]


@pytest.mark.unit
def test_step_outcome_holds_status_and_value():
    oc = StepOutcome(status=StepStatus.RAN, value={"k": 1})
    assert oc.status is StepStatus.RAN
    assert oc.value == {"k": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agents/test_step.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.daily_brief.step'`

- [ ] **Step 3: Write minimal implementation**

```python
# agents/daily_brief/step.py
"""Step — 步驟化執行的深模組：gating + artifact I/O + supervisor 接線藏在 run() 後面。

公開介面只有 run(ctx, input) -> StepOutcome。_produce / _load / _guard / _default
是內部 seam，子類只 override 自己不一樣的那塊。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agents/test_step.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agents/daily_brief/step.py tests/agents/test_step.py
git commit -m "feat: add StepStatus/StepOutput/StepOutcome value types"
```

---

## Task 3: Step base class (the template)

**Files:**
- Modify: `agents/daily_brief/step.py` (add `Step` base class)
- Test: `tests/agents/test_step.py` (append)

The template uses `ctx.steps_to_run` (set[str]), `ctx.force_steps` (set[str]), and `ctx.supervisor` (has `run_step(name, fn, force) -> object with .success and .output`). Tests fake these with `types.SimpleNamespace`.

- [ ] **Step 1: Write the failing test (append to `tests/agents/test_step.py`)**

```python
# --- append to tests/agents/test_step.py ---
from pathlib import Path
from types import SimpleNamespace

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import Step


class _DoublerStep(Step):
    """測試用最小 step：value = input * 2，persist = {'v': value}。"""

    name = "compress"  # 借用 STEP_CONFIGS 既有的鍵，避免 KeyError（fake supervisor 不查表）

    def __init__(self, artifact: Path):
        self._artifact = artifact

    def artifact_path(self, ctx):
        return self._artifact

    def _produce(self, ctx, input, reflect_context=""):
        value = input * 2
        return StepOutput(persist={"v": value}, value=value)


class _FakeSupervisor:
    """run_step 直接呼叫 fn()（plain 慣例），記錄被呼叫次數。"""

    def __init__(self, succeed=True):
        self.succeed = succeed
        self.calls = 0

    def run_step(self, name, fn, force=False):
        self.calls += 1
        if not self.succeed:
            return SimpleNamespace(success=False, output=None)
        return SimpleNamespace(success=True, output=fn())


def _ctx(tmp_path, steps_to_run, force_steps, supervisor):
    return SimpleNamespace(
        steps_dir=tmp_path,
        day_dir=tmp_path,
        steps_to_run=steps_to_run,
        force_steps=force_steps,
        supervisor=supervisor,
    )


@pytest.mark.unit
def test_run_executes_and_persists_when_in_steps(tmp_path):
    art = tmp_path / "compress.json"
    sup = _FakeSupervisor()
    ctx = _ctx(tmp_path, {"compress"}, set(), sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.RAN
    assert outcome.value == 42
    assert JsonCodec().read(art) == {"v": 42}
    assert sup.calls == 1


@pytest.mark.unit
def test_run_loads_existing_artifact_without_supervisor(tmp_path):
    art = tmp_path / "compress.json"
    JsonCodec().write(art, {"v": 999})
    sup = _FakeSupervisor()
    ctx = _ctx(tmp_path, {"compress"}, set(), sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.LOADED
    assert outcome.value == {"v": 999}   # _load 預設 = identity（回 decoded）
    assert sup.calls == 0


@pytest.mark.unit
def test_run_force_reruns_even_if_artifact_exists(tmp_path):
    art = tmp_path / "compress.json"
    JsonCodec().write(art, {"v": 999})
    sup = _FakeSupervisor()
    ctx = _ctx(tmp_path, {"compress"}, {"compress"}, sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.RAN
    assert outcome.value == 42
    assert sup.calls == 1


@pytest.mark.unit
def test_run_skips_when_not_in_steps_and_no_artifact(tmp_path):
    art = tmp_path / "compress.json"
    sup = _FakeSupervisor()
    ctx = _ctx(tmp_path, set(), set(), sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None         # 預設 _default 回 None
    assert sup.calls == 0


@pytest.mark.unit
def test_run_guard_blocks_falsy_input(tmp_path):
    art = tmp_path / "compress.json"
    sup = _FakeSupervisor()
    ctx = _ctx(tmp_path, {"compress"}, set(), sup)
    outcome = _DoublerStep(art).run(ctx, 0)   # 0 → bool(input) False → guard 擋
    assert outcome.status is StepStatus.SKIPPED
    assert sup.calls == 0


@pytest.mark.unit
def test_run_failed_returns_default(tmp_path):
    art = tmp_path / "compress.json"
    sup = _FakeSupervisor(succeed=False)
    ctx = _ctx(tmp_path, {"compress"}, set(), sup)
    outcome = _DoublerStep(art).run(ctx, 21)
    assert outcome.status is StepStatus.FAILED
    assert outcome.value is None
    assert not art.exists()              # 失敗不落盤
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agents/test_step.py -v`
Expected: FAIL — `ImportError: cannot import name 'Step'` (or `AttributeError` on `.run`)

- [ ] **Step 3: Write minimal implementation (append `Step` to `agents/daily_brief/step.py`)**

Add imports at the top of `step.py` (below `from typing import Any`):

```python
from pathlib import Path

from config import get_logger

from .codecs import ArtifactCodec, JsonCodec
from .step_cache import Verdict, decide

logger = get_logger(__name__)
```

Append the base class:

```python
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
    def run(self, ctx, input, reflect: str = "") -> StepOutcome:
        path = self.artifact_path(ctx)
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

        def _producer(reflect_context: str = "") -> StepOutput:
            return self._produce(ctx, input, reflect_context or reflect)

        result = ctx.supervisor.run_step(self.name, _producer, force=self.name in ctx.force_steps)
        if not result.success:
            return StepOutcome(StepStatus.FAILED, self._default(input))
        output: StepOutput = result.output
        self.codec.write(path, output.persist)
        logger.info("Step %-8s: 完成 → %s", self.name, path.name)
        return StepOutcome(StepStatus.RAN, output.value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agents/test_step.py -v`
Expected: PASS (9 passed — 3 from Task 2 + 6 new)

- [ ] **Step 5: Commit**

```bash
git add agents/daily_brief/step.py tests/agents/test_step.py
git commit -m "feat: add Step base class template (gate/io/supervisor/default)"
```

---

## Task 4: CompressStep + migrate run()

`CompressStep` reuses the agent's existing `_run_compress` and `_check_source_health` (both kept, both still unit-tested directly). The step only adds the gating/I/O/supervisor wrapping that `_phase_compress` used to hand-roll.

**Files:**
- Create: `agents/daily_brief/steps/__init__.py`
- Create: `agents/daily_brief/steps/compress.py`
- Test: `tests/agents/test_compress_step.py`
- Modify: `agents/daily_brief/agent.py` (call `CompressStep` in `run()`; delete `_phase_compress`)

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_compress_step.py
"""CompressStep — wraps _run_compress + _check_source_health behind Step.run()."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.compress import CompressStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn())


def _ctx(tmp_path):
    return SimpleNamespace(
        steps_dir=tmp_path,
        day_dir=tmp_path,
        steps_to_run={"compress"},
        force_steps=set(),
        supervisor=_FakeSupervisor(),
    )


@pytest.mark.unit
def test_compress_step_runs_producer_and_persists(tmp_path):
    captured = {}

    def fake_run_compress(source_data, reflect_context=""):
        captured["source"] = source_data
        captured["reflect"] = reflect_context
        return {"hn": {"themes": ["t"], "articles": []}}

    def fake_health(compress_data):
        captured["health"] = compress_data
        return []

    step = CompressStep(run_compress=fake_run_compress, check_health=fake_health)
    outcome = step.run(_ctx(tmp_path), {"hn": {"articles": [{"interest": "***"}]}})

    assert outcome.status is StepStatus.RAN
    assert outcome.value == {"hn": {"themes": ["t"], "articles": []}}
    assert captured["source"] == {"hn": {"articles": [{"interest": "***"}]}}
    assert captured["health"] == outcome.value          # health 收到產出
    assert JsonCodec().read(tmp_path / "compress.json") == outcome.value


@pytest.mark.unit
def test_compress_step_artifact_path(tmp_path):
    step = CompressStep(run_compress=lambda *a, **k: {}, check_health=lambda d: [])
    assert step.artifact_path(SimpleNamespace(steps_dir=tmp_path)) == tmp_path / "compress.json"


@pytest.mark.unit
def test_compress_step_default_is_empty_dict(tmp_path):
    step = CompressStep(run_compress=lambda *a, **k: {}, check_health=lambda d: [])
    ctx = SimpleNamespace(steps_dir=tmp_path, steps_to_run=set(), force_steps=set(),
                          supervisor=_FakeSupervisor())
    outcome = step.run(ctx, {"hn": {}})   # 不在 steps_to_run、無 artifact → SKIP
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agents/test_compress_step.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.daily_brief.steps'`

- [ ] **Step 3: Write minimal implementation**

```python
# agents/daily_brief/steps/__init__.py
"""Concrete Step 子類，一檔一步。"""
```

```python
# agents/daily_brief/steps/compress.py
"""CompressStep — 各來源 *** 文章語義壓縮。

producer 與 source-health 檢查注入自 DailyBriefAgent（_run_compress / _check_source_health），
本檔只負責 gating + artifact I/O 的 Step 包裝。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..step import Step, StepOutput


class CompressStep(Step):
    name = "compress"

    def __init__(
        self,
        run_compress: Callable[..., dict],
        check_health: Callable[[dict], list],
    ) -> None:
        self._run_compress = run_compress
        self._check_health = check_health

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "compress.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        result = self._run_compress(input, reflect_context=reflect_context)
        self._check_health(result)
        return StepOutput(persist=result, value=result)

    def _default(self, input):
        return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agents/test_compress_step.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Wire `CompressStep` into `run()` and delete `_phase_compress`**

In `agents/daily_brief/agent.py`, find this line in `run()` (currently line 124):

```python
        compress_data = self._phase_compress(ctx, source_data)
```

Replace it with:

```python
        from .steps.compress import CompressStep
        compress_data = CompressStep(
            self._run_compress, self._check_source_health
        ).run(ctx, source_data).value
```

Then delete the entire `_phase_compress` method (currently lines 271–303, from `def _phase_compress(self, ctx: _RunContext, source_data: dict[str, dict]) -> dict:` through its final `return result.output`).

- [ ] **Step 6: Run the full suite to verify nothing regressed**

Run: `python3 -m pytest tests/ -q`
Expected: PASS — all previously-passing tests stay green (notably `tests/test_daily_brief_agent.py::test_run_compress_*`, `::test_check_source_health_*`, and the `tests/harness/test_compress.py` behavioral suite, which read `_run_compress`/`compress.json` — both unchanged). No reference to `_phase_compress` remains.

Verify no dangling references:

Run: `grep -rn "_phase_compress" agents/ tests/`
Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add agents/daily_brief/steps/__init__.py agents/daily_brief/steps/compress.py \
        tests/agents/test_compress_step.py agents/daily_brief/agent.py
git commit -m "refactor: migrate compress phase to deep CompressStep"
```

---

## Task 5: Document the Step abstraction

**Files:**
- Modify: `CLAUDE.md` (the "步驟化執行（Idempotent Steps）" paragraph under 核心設計原則)

- [ ] **Step 1: Update the design-principle note**

In `CLAUDE.md`, find the paragraph beginning `**步驟化執行（Idempotent Steps）**：`. Append these two sentences to the end of that paragraph (keep existing text):

```
「該跑/該載入/該略過」的判定（`step_cache.decide`）與其後的動作（artifact I/O、委派 supervisor、default）一併收進 `step.py` 的 `Step` 基底模板；公開介面只有 `run(ctx, input) -> StepOutcome`，每步差異住內部 seam（`_produce`/`_load`/`_guard`/`_default`）與注入的 `codecs.py` `ArtifactCodec`。新增 step：在 `agents/daily_brief/steps/` 加一檔、繼承 `Step`、在 `run()` 顯式接線（不造依賴圖）。compress 已遷移；其餘步驟與 fetch/judge-feedback orchestrator 見 Plan 2/3。
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record Step abstraction in CLAUDE.md design principles"
```

---

## Self-Review

**Spec coverage** (against the locked-in decisions):
- Base class + template method, public `run()` → Task 3. ✓
- `StepOutcome(status, value)` distinct from supervisor's `StepResult` → Task 2 + naming note. ✓
- `StepOutput(persist, value)` for return≠persist → Task 2 (exercised in Task 3 `_DoublerStep`). ✓
- `_load(decoded, input)` identity default → Task 3. ✓
- `_guard` default `bool(input)` → Task 3 (`test_run_guard_blocks_falsy_input`). ✓
- `_default` = SKIP & FAILED value → Task 3 (`test_run_skips...`, `test_run_failed_returns_default`). ✓
- supervisor delegation + uniform `_produce(reflect_context)` signature → Task 3 `_producer` closure. ✓
- Codecs Json/Text/Sentinel → Task 1. ✓
- compress migration, tests green → Task 4. ✓
- **Out of scope (Plans 2–3):** the other 12 steps, fetch orchestrator + two-stage Sources, judge-feedback lift (candidate 3), typed views in `_load` (candidate 2), folding Fix C into orchestrator force-computation. These are NOT gaps — they are deliberately deferred.

**Placeholder scan:** No TBD/TODO/"similar to". Every code step shows full code. ✓

**Type consistency:** `StepStatus` members `RAN/LOADED/SKIPPED/FAILED` consistent across Tasks 2–4. `StepOutput(persist, value)` and `StepOutcome(status, value)` field names consistent. `Step.run(ctx, input, reflect="")`, `_produce(ctx, input, reflect_context="")`, `_load(decoded, input)`, `_guard(ctx, input)`, `_default(input)` signatures consistent across base (Task 3) and `CompressStep` (Task 4). Fake supervisor returns `SimpleNamespace(success=, output=)` matching `result.success`/`result.output` usage. ✓

---

## Follow-up plans (to write after Plan 1 lands)

- **Plan 2 — migrate the linear middle:** one task each for `dedup` (`_load` override re-filters by `kept_urls`), `enrich` (`max_retries=1` config, no behavior change), `digest` (`StepOutput(persist=digest_data, value=digests)`), `judge` (tuple input `(enrich, digests)`, `_guard` two-condition, `_judge-history.json` side write), `report` (`TextCodec`, `_load`→None), `save`/`notify` (`SentinelCodec`, `_guard` adds `report.md` check, side effects in `_produce`). Delete each `_phase_*` as migrated.
- **Plan 3 — orchestrators:** `fetch` stays an orchestrator driving 5 two-stage Source Steps (`fetch_raw` parallel / `score` serial, ≥2 gate); lift the judge→digest feedback loop into `run()` (resolves candidate 3 — delete the `retry_state` closure, prompt re-serialization, and split writes; `supervisor.run_judge_feedback` shrinks to `reflect_for_completeness(missed_urls)`); fold Fix C `_detect_stale_downstream` into an orchestrator force-computation helper; final dead-code sweep.
