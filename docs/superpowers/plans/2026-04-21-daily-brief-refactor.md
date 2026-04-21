# Daily Brief Agent 重構計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修復評估發現的 8 個設計缺陷（reflect 無效、run() God Method、parse_json 重複、Supervisor 耦合 Telegram、judge 無 reflect、compress_data 結構雜訊、notify 串行 LLM、無耗時 log）

**Architecture:** 從最底層共用工具（parse_llm_json utility）開始，逐層向上（config → supervisor → agent），最後做行為變更（並行化、結構修正）。每個 Task 均可獨立測試，不破壞既有測試。

**Tech Stack:** Python 3.11+、pytest、unittest.mock；無新外部依賴

---

## 受影響的檔案

| 操作 | 路徑 | 職責 |
|------|------|------|
| 建立 | `config/utils.py` | 共用 `parse_llm_json`（JSON fence strip → json.loads → json_repair fallback） |
| 修改 | `config/__init__.py` | 匯出 `parse_llm_json` |
| 修改 | `agents/daily_brief/config.py` | `StepConfig` 加 `task_description`；`judge` 改 `error_aware` |
| 修改 | `agents/daily_brief/supervisor.py` | 用 `parse_llm_json`；inject `notify_fn`；reflect 用 task_description；加 elapsed log |
| 修改 | `agents/daily_brief/agent.py` | 用 `parse_llm_json`；`run()` 拆 phase methods；notify 並行；compress_data 加 `_meta` |
| 修改 | `tests/agents/test_supervisor.py` | 適配 `notify_fn` 注入，移除 module-level `send` patch |
| 修改 | `tests/test_daily_brief_agent.py` | 更新 FakeSupervisor 簽名；修正 notify 並行測試；加 `_meta` assertion |

---

## Task 1：建立共用 `parse_llm_json`

**Files:**
- Create: `config/utils.py`
- Modify: `config/__init__.py`
- Test: `tests/test_daily_brief_agent.py`（既有的 `test_parse_json_*` 測試已覆蓋邏輯，此 task 確認搬移後仍通過）

- [ ] **Step 1：寫失敗測試（在 `tests/test_config_utils.py` 建立新測試檔）**

```python
# tests/test_config_utils.py
import pytest
from config.utils import parse_llm_json


def test_plain_json():
    assert parse_llm_json('{"key": "val"}') == {"key": "val"}


def test_json_in_fence():
    raw = '```json\n{"key": "val"}\n```'
    assert parse_llm_json(raw) == {"key": "val"}


def test_json_fence_without_lang():
    raw = '```\n{"key": "val"}\n```'
    assert parse_llm_json(raw) == {"key": "val"}


def test_fullwidth_colon_repaired():
    broken = '{"title：標題": "val"}'
    result = parse_llm_json(broken)
    assert "raw" not in result


def test_non_string_input():
    assert parse_llm_json(None) == {"raw": "None"}


def test_complete_failure_returns_raw():
    result = parse_llm_json("not json at all ><")
    # either repaired or falls back to {"raw": ...}
    assert isinstance(result, dict)
```

- [ ] **Step 2：執行測試確認失敗**

```bash
cd $HOME/Workspace/agent
python3 -m pytest tests/test_config_utils.py -v
```

預期：`ModuleNotFoundError: No module named 'config.utils'`

- [ ] **Step 3：建立 `config/utils.py`**

```python
# config/utils.py
from __future__ import annotations

import json
import re


def parse_llm_json(raw: str | None) -> dict:
    """從 LLM 輸出解析 JSON，含 markdown fence strip 和 json_repair fallback。"""
    if not isinstance(raw, str):
        raw = str(raw) if raw is not None else "null"

    def _strip_fence(s: str) -> str:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
        text = m.group(1) if m else s
        return re.sub(r"^\s*json\s*\n", "", text, count=1, flags=re.IGNORECASE)

    text = _strip_fence(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        from json_repair import repair_json
        repaired = json.loads(repair_json(text))
        if isinstance(repaired, dict):
            return repaired
    except Exception:
        pass

    return {"raw": raw}
```

- [ ] **Step 4：更新 `config/__init__.py` 匯出**

舊：
```python
from .settings import get_llm, get_judge_llm, LLMBackend, LocalLLMBackend, AnthropicBackend
from .logging_config import setup_logging, get_logger

__all__ = [
    "get_llm",
    "get_judge_llm",
    "LLMBackend",
    "LocalLLMBackend",
    "AnthropicBackend",
    "setup_logging",
    "get_logger",
]
```

新：
```python
from .settings import get_llm, get_judge_llm, LLMBackend, LocalLLMBackend, AnthropicBackend
from .logging_config import setup_logging, get_logger
from .utils import parse_llm_json

__all__ = [
    "get_llm",
    "get_judge_llm",
    "LLMBackend",
    "LocalLLMBackend",
    "AnthropicBackend",
    "setup_logging",
    "get_logger",
    "parse_llm_json",
]
```

- [ ] **Step 5：執行新測試確認通過**

```bash
python3 -m pytest tests/test_config_utils.py -v
```

預期：全部 PASS

- [ ] **Step 6：在 `agent.py` 替換 `_parse_json` 靜態方法**

在 `agents/daily_brief/agent.py`：

舊的 import 區塊加一行：
```python
from config import get_judge_llm, get_llm, get_logger, parse_llm_json
```

刪除 `DailyBriefAgent._parse_json` 靜態方法（約第 645-670 行整個 method）。

將 `agent.py` 中所有 `self._parse_json(` 替換為 `parse_llm_json(`（共 8 處）：
- `_fetch_hatena`：`result = parse_llm_json(self._complete(...))`
- `_fetch_hn`：同上
- `_fetch_reddit`：同上
- `_fetch_security`：同上
- `_run_compress`：`parsed = parse_llm_json(raw)`
- `_run_digest`：`result = parse_llm_json(self._complete(prompt))`
- `_run_judge`：`result = parse_llm_json(raw)`
- `_notify`：`overview_result = parse_llm_json(...)` 和 `digest_result = parse_llm_json(...)`

- [ ] **Step 7：在 `supervisor.py` 替換 `_parse_reflect_response`**

刪除 `supervisor.py` 底部的 `_parse_reflect_response` 函數（約第 205-221 行）。

在 `supervisor.py` import 區加：
```python
from config import parse_llm_json
```

在 `_reflect` 方法中，將：
```python
parsed = _parse_reflect_response(raw)
```
改為：
```python
parsed = parse_llm_json(raw)
```

在 `_reflect_with_judge` 方法中同樣替換：
```python
parsed = parse_llm_json(raw)
```

- [ ] **Step 8：執行全套測試確認無退步**

```bash
python3 -m pytest tests/ -v --tb=short
```

預期：全部 PASS（`test_parse_json_recovers_from_*` 仍通過，因為它們現在間接使用 `parse_llm_json`）

- [ ] **Step 9：Commit**

```bash
git add config/utils.py config/__init__.py agents/daily_brief/agent.py agents/daily_brief/supervisor.py tests/test_config_utils.py
git commit -m "refactor: 抽共用 parse_llm_json 到 config/utils，消除重複邏輯"
```

---

## Task 2：`StepConfig` 加 `task_description`，`judge` 改 `error_aware`

**Files:**
- Modify: `agents/daily_brief/config.py`
- Test: `tests/agents/test_supervisor.py`（新增 reflect 用 task_description 的測試）

- [ ] **Step 1：寫失敗測試**

在 `tests/agents/test_supervisor.py` 末尾加：

```python
@pytest.mark.unit
def test_reflect_uses_task_description_as_original_prompt(tmp_path):
    """reflect LLM 呼叫的 prompt 應包含 task_description，而非 '[step: name]'。"""
    reflect_resp = json.dumps({
        "diagnosis": "LLM 回傳格式錯誤",
        "adjusted_prompt": "修正後指示",
    })
    supervisor, llm, _ = _make_supervisor(tmp_path, llm_resp=reflect_resp)
    fn = MagicMock(side_effect=[RuntimeError("bad output"), {"digests": []}])

    supervisor.run_step("digest", fn)

    reflect_call_prompt = llm.complete.call_args[0][0]
    # task_description 應出現在 reflect prompt 中
    assert "跨來源深度摘要" in reflect_call_prompt
    # 舊的無效佔位符不應出現
    assert "[step:" not in reflect_call_prompt


@pytest.mark.unit
def test_judge_uses_error_aware_strategy(tmp_path):
    """judge 步驟現在應使用 error_aware strategy，失敗時會呼叫 reflect。"""
    from agents.daily_brief.config import STEP_CONFIGS
    assert STEP_CONFIGS["judge"].strategy == "error_aware"
```

- [ ] **Step 2：執行測試確認失敗**

```bash
python3 -m pytest tests/agents/test_supervisor.py::test_reflect_uses_task_description_as_original_prompt tests/agents/test_supervisor.py::test_judge_uses_error_aware_strategy -v
```

預期：兩個 FAIL（task_description 不存在，judge strategy 仍是 plain）

- [ ] **Step 3：更新 `agents/daily_brief/config.py`**

在 `StepConfig` 加欄位：

```python
@dataclass(frozen=True)
class StepConfig:
    max_retries: int
    strategy: Literal["plain", "error_aware"]
    backoff_seconds: tuple[float, ...] = (0.0,)
    task_description: str = ""
```

更新 `STEP_CONFIGS`（完整替換）：

```python
STEP_CONFIGS: dict[str, StepConfig] = {
    "hatena":   StepConfig(
        max_retries=3, strategy="plain",
        backoff_seconds=(1.0, 3.0, 9.0),
        task_description="從 Hatena Bookmark 抓取文章並以 JSON 格式回傳 interest 評分結果",
    ),
    "hn":       StepConfig(
        max_retries=3, strategy="plain",
        backoff_seconds=(1.0, 3.0, 9.0),
        task_description="從 Hacker News 抓取文章並以 JSON 格式回傳 interest 評分結果",
    ),
    "reddit":   StepConfig(
        max_retries=3, strategy="plain",
        backoff_seconds=(1.0, 3.0, 9.0),
        task_description="從 Reddit 各 subreddit 抓取文章並以 JSON 格式回傳 interest 評分結果",
    ),
    "security": StepConfig(
        max_retries=3, strategy="plain",
        backoff_seconds=(1.0, 3.0, 9.0),
        task_description="從 Security blogs 抓取文章並以 JSON 格式回傳 interest 評分結果",
    ),
    "compress": StepConfig(
        max_retries=2, strategy="error_aware",
        task_description="將各來源 *** 文章語義壓縮為 themes 陣列 + articles 陣列（含 one_liner），輸出 JSON",
    ),
    "digest":   StepConfig(
        max_retries=2, strategy="error_aware",
        task_description="跨來源深度摘要，輸出含 title/url/source/summary 的 digests 陣列 JSON",
    ),
    "judge":    StepConfig(
        max_retries=2, strategy="error_aware",
        task_description="LLM-as-Judge 評分 relevance/completeness/faithfulness，輸出含 scores 物件的 JSON",
    ),
    "report":   StepConfig(
        max_retries=2, strategy="error_aware",
        task_description="根據 compress + digest 資料生成純 markdown 格式的科技趨勢報告，不包 JSON fence",
    ),
    "notify":   StepConfig(
        max_retries=2, strategy="error_aware",
        task_description="生成 Telegram 訊息 JSON（tg_overview 或 tg_digest key），限用 Telegram 允許的 HTML tag",
    ),
    "save":     StepConfig(
        max_retries=2, strategy="plain",
        task_description="將 report.md 和 digest 存入 Obsidian vault",
    ),
}
```

- [ ] **Step 4：更新 `supervisor.py` 的 `_reflect` 方法傳入 task_description**

在 `run_step` 方法中，找到：
```python
adjusted = self._reflect(
    step_name=name,
    bad_output=last_output_str,
    error=last_error,
)
```

改為：
```python
adjusted = self._reflect(
    step_name=name,
    task_description=cfg.task_description,
    bad_output=last_output_str,
    error=last_error,
)
```

在 `_reflect` 方法簽名改為：
```python
def _reflect(self, step_name: str, task_description: str, bad_output: str, error: str) -> str:
```

在 `_reflect` 方法中，將：
```python
reflect_prompts.build_reflect_prompt(
    original_prompt=f"[step: {step_name}]",
    bad_output=bad_output,
    error=error,
)
```
改為：
```python
reflect_prompts.build_reflect_prompt(
    original_prompt=task_description or f"[step: {step_name}]",
    bad_output=bad_output,
    error=error,
)
```

- [ ] **Step 5：執行測試確認通過**

```bash
python3 -m pytest tests/agents/test_supervisor.py -v
```

預期：全部 PASS，包含兩個新測試

- [ ] **Step 6：Commit**

```bash
git add agents/daily_brief/config.py agents/daily_brief/supervisor.py tests/agents/test_supervisor.py
git commit -m "feat: StepConfig 加 task_description，reflect 使用有意義的任務描述，judge 改 error_aware"
```

---

## Task 3：`SupervisorAgent` 加 `notify_fn` 注入 + elapsed log

**Files:**
- Modify: `agents/daily_brief/supervisor.py`
- Modify: `tests/agents/test_supervisor.py`

背景：`supervisor.py` 目前在 module-level 直接 `from tools.notifiers.telegram import send`，使 Supervisor 耦合 Telegram。改為 constructor 注入後，測試不再需要 patch module-level 符號。

- [ ] **Step 1：更新 `test_supervisor.py` 的 `_make_supervisor` 輔助函數**

將舊的：
```python
def _make_supervisor(tmp_path, llm_resp="", judge_resp=""):
    from agents.daily_brief.supervisor import SupervisorAgent

    llm = MagicMock()
    llm.complete.return_value = llm_resp
    judge_llm = MagicMock()
    judge_llm.complete.return_value = judge_resp
    return SupervisorAgent(
        llm=llm,
        judge_llm=judge_llm,
        steps_dir=tmp_path,
        today="2026-04-20",
    ), llm, judge_llm
```

改為：
```python
def _make_supervisor(tmp_path, llm_resp="", judge_resp="", notify_fn=None):
    from agents.daily_brief.supervisor import SupervisorAgent

    llm = MagicMock()
    llm.complete.return_value = llm_resp
    judge_llm = MagicMock()
    judge_llm.complete.return_value = judge_resp
    return SupervisorAgent(
        llm=llm,
        judge_llm=judge_llm,
        steps_dir=tmp_path,
        today="2026-04-20",
        notify_fn=notify_fn,
    ), llm, judge_llm
```

- [ ] **Step 2：更新需要 Telegram 的測試，改用 notify_fn**

找到 `test_plain_step_fails_after_max_retries`，將：
```python
with patch("agents.daily_brief.supervisor.send", return_value=True):
    result = supervisor.run_step("judge", fn)
```
改為：
```python
mock_notify = MagicMock(return_value=True)
supervisor, llm, _ = _make_supervisor(tmp_path, notify_fn=mock_notify)
fn = MagicMock(side_effect=RuntimeError("always fails"))
result = supervisor.run_step("judge", fn)
```

（注意：舊的 `supervisor, llm, _ = _make_supervisor(tmp_path)` 這行也要移除，因為現在在 mock_notify 之後重新建立）

找到 `test_alert_dedup_same_step_same_day`，將：
```python
supervisor, _, _ = _make_supervisor(tmp_path)
fn = MagicMock(side_effect=RuntimeError("fail"))

with patch("agents.daily_brief.supervisor.send", return_value=True) as mock_send:
    supervisor.run_step("judge", fn)
    fn.reset_mock()
    fn.side_effect = RuntimeError("fail again")
    supervisor.run_step("judge", fn)

assert mock_send.call_count == 1
```
改為：
```python
mock_notify = MagicMock(return_value=True)
supervisor, _, _ = _make_supervisor(tmp_path, notify_fn=mock_notify)
fn = MagicMock(side_effect=RuntimeError("fail"))

supervisor.run_step("judge", fn)
fn.reset_mock()
fn.side_effect = RuntimeError("fail again")
supervisor.run_step("judge", fn)

assert mock_notify.call_count == 1
```

找到 `test_force_clears_alert`，將：
```python
supervisor, _, _ = _make_supervisor(tmp_path)
fn = MagicMock(side_effect=RuntimeError("fail"))

with patch("agents.daily_brief.supervisor.send", return_value=True) as mock_send:
    supervisor.run_step("judge", fn)
    fn.reset_mock()
    fn.side_effect = RuntimeError("fail again")
    supervisor.run_step("judge", fn, force=True)

assert mock_send.call_count == 2
```
改為：
```python
mock_notify = MagicMock(return_value=True)
supervisor, _, _ = _make_supervisor(tmp_path, notify_fn=mock_notify)
fn = MagicMock(side_effect=RuntimeError("fail"))

supervisor.run_step("judge", fn)
fn.reset_mock()
fn.side_effect = RuntimeError("fail again")
supervisor.run_step("judge", fn, force=True)

assert mock_notify.call_count == 2
```

- [ ] **Step 3：執行測試確認失敗（因為 supervisor.py 尚未改）**

```bash
python3 -m pytest tests/agents/test_supervisor.py -v
```

預期：`TypeError: SupervisorAgent.__init__() got an unexpected keyword argument 'notify_fn'`

- [ ] **Step 4：更新 `supervisor.py`**

**4a：移除 module-level import，加 Callable import**

舊 import：
```python
from tools.notifiers.telegram import send
```
刪除這行。

在 import 區加：
```python
from typing import Any, Callable
```
（如果已有 `from typing import Any, Callable` 則跳過）

**4b：更新 `__init__`**

```python
def __init__(
    self,
    llm: LLMBackend,
    judge_llm: LLMBackend,
    steps_dir: Path,
    today: str,
    notify_fn: Callable[[str], bool] | None = None,
) -> None:
    self._llm = llm
    self._judge_llm = judge_llm
    self._steps_dir = steps_dir
    self._today = today
    self._notify_fn = notify_fn
```

**4c：更新 `_notify_failure` 使用 `self._notify_fn`**

找到 `_notify_failure` 方法中：
```python
msg = (
    f"⚠️ Daily Brief 步驟失敗（{self._today}）\n\n"
    ...
)
send(msg)
```
改為：
```python
msg = (
    f"⚠️ Daily Brief 步驟失敗（{self._today}）\n\n"
    f"步驟：{name}（嘗試 {attempts} 次）\n"
    f"錯誤：{error[:300]}\n"
    f"診斷：{diagnosis[:300]}\n\n"
    f"建議：python3 main.py \"/daily-brief --force {name}\""
)
if self._notify_fn:
    self._notify_fn(msg)
```

**4d：在 `run_step` 加 elapsed log**

在 `run_step` 方法開頭，`cfg = STEP_CONFIGS[name]` 後加：
```python
import time
_start = time.monotonic()
```

在成功回傳前（`return StepResult(name=name, success=True, ...)`）加：
```python
logger.info("Step %s: 完成（attempt %d，耗時 %.1fs）", name, attempt, time.monotonic() - _start)
```

- [ ] **Step 5：執行測試確認通過**

```bash
python3 -m pytest tests/agents/test_supervisor.py -v
```

預期：全部 PASS

- [ ] **Step 6：執行全套測試**

```bash
python3 -m pytest tests/ -v --tb=short
```

預期：全部 PASS

- [ ] **Step 7：Commit**

```bash
git add agents/daily_brief/supervisor.py tests/agents/test_supervisor.py
git commit -m "refactor: SupervisorAgent 改用 notify_fn 注入解耦 Telegram，加耗時 log"
```

---

## Task 4：`run()` 重構為 phase methods

**Files:**
- Modify: `agents/daily_brief/agent.py`
- Modify: `tests/test_daily_brief_agent.py`（更新 FakeSupervisor 簽名）

這是純結構重構，不改變任何行為。`run()` 從 ~300 行縮到 ~30 行。

- [ ] **Step 1：更新 `tests/test_daily_brief_agent.py` 的 FakeSupervisor**

在 `test_daily_brief_agent.py` 中有三個 FakeSupervisor class（分別在 `test_run_judge_step_is_wrapped_by_supervisor`、`test_judge_feedback_loop_uses_new_digests_for_retry`、`test_force_judge_passes_force_flag_to_supervisor`）。

每個 FakeSupervisor 的 `__init__` 都只接受 `(self, llm, judge_llm, steps_dir, today)`，需要加 `notify_fn=None`：

```python
# 三個 FakeSupervisor 的 __init__ 都改為：
def __init__(self, llm, judge_llm, steps_dir, today, notify_fn=None):
    pass
```

- [ ] **Step 2：執行測試確認目前通過（基準線）**

```bash
python3 -m pytest tests/test_daily_brief_agent.py -v --tb=short
```

預期：全部 PASS（此 step 確認 FakeSupervisor 更新沒有破壞什麼）

- [ ] **Step 3：在 `agent.py` 加 `_RunContext` dataclass**

在 `from . import prompts` 之後加：

```python
from dataclasses import dataclass


@dataclass
class _RunContext:
    today: str
    day_dir: Path
    steps_dir: Path
    force_steps: set[str]
    steps_to_run: set[str]
    supervisor: object  # SupervisorAgent，避免循環 import
```

- [ ] **Step 4：抽出 `_phase_fetch` 方法**

將 `run()` 中 Phase 1（從 `source_data: dict[str, dict] = {}` 到 `return f"Pipeline 中止：..."`）移成獨立方法：

```python
def _phase_fetch(self, ctx: _RunContext) -> dict[str, dict] | None:
    """並行執行 4 個 fetch steps。回傳 source_data；成功數 < 2 時回傳 None。"""
    source_data: dict[str, dict] = {}
    fetch_failed: list[str] = []

    def _run_fetch_supervised(name: str) -> tuple[str, dict | None]:
        artifact = ctx.steps_dir / f"{name}.json"
        if name not in ctx.steps_to_run:
            if artifact.exists():
                return name, json.loads(artifact.read_text(encoding="utf-8"))
            return name, None
        if artifact.exists() and name not in ctx.force_steps:
            logger.info("Step %-8s: 載入既有 artifact", name)
            return name, json.loads(artifact.read_text(encoding="utf-8"))

        def fn() -> dict:
            result = self._run_fetch(name)
            result["fetched_at"] = datetime.now().isoformat(timespec="seconds")
            artifact.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("Step %-8s: 完成 → %s", name, artifact.name)
            return result

        step_result = ctx.supervisor.run_step(name, fn, force=(name in ctx.force_steps))
        if step_result.success:
            return name, step_result.output
        return name, None

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_run_fetch_supervised, n): n for n in FETCH_STEPS}
        for future in as_completed(futures):
            name, data = future.result()
            if data is not None:
                source_data[name] = data
            elif name in ctx.steps_to_run:
                fetch_failed.append(name)

    success_count = len(source_data)
    if success_count < 2 and ctx.steps_to_run.intersection(set(FETCH_STEPS)):
        from tools.notifiers.telegram import send as tg_send
        msg = (
            f"⚠️ Daily Brief Fetch 嚴重失敗（{ctx.today}）\n"
            f"成功：{success_count}/4，失敗：{fetch_failed}\n"
            "Pipeline 停止。"
        )
        tg_send(msg)
        logger.error("Fetch 成功 %d/4，低於門檻，pipeline 停止", success_count)
        return None

    return source_data
```

- [ ] **Step 5：抽出 `_phase_compress` 方法**

```python
def _phase_compress(self, ctx: _RunContext, source_data: dict[str, dict]) -> dict:
    """執行 compress step，回傳 compress_data。"""
    compress_artifact = ctx.steps_dir / "compress.json"

    if "compress" not in ctx.steps_to_run:
        if compress_artifact.exists():
            return json.loads(compress_artifact.read_text(encoding="utf-8"))
        return {}

    if compress_artifact.exists() and "compress" not in ctx.force_steps:
        logger.info("Step compress  : 載入既有 artifact")
        return json.loads(compress_artifact.read_text(encoding="utf-8"))

    if not source_data:
        logger.warning("Step compress  : 無評分資料，略過（先執行 fetch steps）")
        return {}

    logger.info("Step compress  : 執行中...")

    def _compress_fn(reflect_context: str = "") -> dict:
        return self._run_compress(source_data, reflect_context=reflect_context)

    result = ctx.supervisor.run_step(
        "compress", _compress_fn, force=("compress" in ctx.force_steps)
    )
    if not result.success:
        logger.error("Step compress: 全部重試失敗，略過 digest/judge/report/notify")
        return {}

    compress_artifact.write_text(
        json.dumps(result.output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Step compress  : 完成 → compress.json")
    self._check_source_health(result.output)
    return result.output
```

- [ ] **Step 6：抽出 `_phase_digest` 方法**

```python
def _phase_digest(self, ctx: _RunContext, compress_data: dict) -> list[dict]:
    """執行 digest step，回傳 digests list。"""
    digest_artifact = ctx.steps_dir / "digest.json"

    if "digest" not in ctx.steps_to_run:
        if digest_artifact.exists():
            return json.loads(digest_artifact.read_text(encoding="utf-8")).get("digests", [])
        return []

    if digest_artifact.exists() and "digest" not in ctx.force_steps:
        logger.info("Step digest   : 載入既有 artifact")
        return json.loads(digest_artifact.read_text(encoding="utf-8")).get("digests", [])

    if not compress_data:
        logger.warning("Step digest   : 無壓縮資料，略過（先執行 compress step）")
        return []

    logger.info("Step digest   : 執行中...")

    def _digest_fn(reflect_context: str = "") -> tuple[list[dict], dict]:
        return self._run_digest(compress_data, reflect_context=reflect_context)

    result = ctx.supervisor.run_step(
        "digest", _digest_fn, force=("digest" in ctx.force_steps)
    )
    if not result.success:
        logger.error("Step digest: 全部重試失敗，略過 judge/report/notify")
        return []

    digests, digest_data = result.output
    digest_artifact.write_text(
        json.dumps(digest_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Step digest   : 完成 → digest.json（%d 篇）", len(digests))
    return digests
```

- [ ] **Step 7：抽出 `_phase_judge` 方法**

```python
def _phase_judge(
    self, ctx: _RunContext, compress_data: dict, digests: list[dict]
) -> tuple[dict, list[dict]]:
    """執行 judge step + feedback loop。回傳 (compress_data, digests)（可能更新）。"""
    judge_artifact = ctx.steps_dir / "judge.json"

    if "judge" not in ctx.steps_to_run:
        return compress_data, digests

    if judge_artifact.exists() and "judge" not in ctx.force_steps:
        logger.info("Step judge     : 載入既有 artifact")
        return compress_data, digests

    if not digests or not compress_data:
        logger.warning("Step judge     : 缺少 digests 或 compress 資料，略過")
        return compress_data, digests

    logger.info("Step judge     : 執行中...")

    def _judge_fn() -> dict:
        return self._run_judge(compress_data, digests, date=ctx.today)

    judge_step = ctx.supervisor.run_step(
        "judge", _judge_fn, force=("judge" in ctx.force_steps)
    )
    if not judge_step.success:
        logger.error("Step judge: 全部重試失敗，略過 report/notify")
        return compress_data, digests

    judge_result = judge_step.output
    judge_artifact.write_text(
        json.dumps(judge_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        "Step judge     : 完成 → judge.json (overall=%.1f)",
        judge_result.get("overall", 0),
    )

    # Judge → Digest 回饋 loop（上限 1 次）
    completeness_score = (
        judge_result.get("scores", {}).get("completeness", {}).get("score")
    )
    if (
        isinstance(completeness_score, (int, float))
        and completeness_score < 3
        and "digest" not in ctx.force_steps
        and digests
    ):
        missed_urls = (
            judge_result.get("scores", {})
            .get("completeness", {})
            .get("missed_urls", [])
        )
        logger.warning(
            "Judge completeness=%.1f，觸發 digest 重跑（missed: %s）",
            completeness_score,
            missed_urls,
        )
        original_digest_prompt = prompts.build_digest_prompt_from_compress(
            json.dumps(compress_data, ensure_ascii=False)
        )
        retry_state: dict[str, list[dict]] = {"digests": digests}

        def _retry_digest_fn(reflect_context: str = "") -> tuple[list[dict], dict]:
            new_digests, new_digest_data = self._run_digest(
                compress_data, reflect_context=reflect_context
            )
            retry_state["digests"] = new_digests
            return new_digests, new_digest_data

        def _retry_judge_fn(reflect_context: str = "") -> dict:
            return self._run_judge(compress_data, retry_state["digests"], date=ctx.today)

        digests, digest_data, judge_result = ctx.supervisor.run_judge_feedback(
            missed_urls=missed_urls,
            original_digest_prompt=original_digest_prompt,
            run_digest_fn=_retry_digest_fn,
            run_judge_fn=_retry_judge_fn,
        )
        (ctx.steps_dir / "digest.json").write_text(
            json.dumps(digest_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        judge_artifact.write_text(
            json.dumps(judge_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Judge 回饋 digest 重跑完成")

    return compress_data, digests
```

- [ ] **Step 8：抽出 `_phase_report`、`_phase_save`、`_phase_notify` 方法**

```python
def _phase_report(self, ctx: _RunContext, compress_data: dict, digests: list[dict]) -> None:
    report_md = ctx.day_dir / "report.md"

    if "report" not in ctx.steps_to_run:
        return
    if report_md.exists() and "report" not in ctx.force_steps:
        logger.info("Step report   : 載入既有 artifact")
        return
    if not digests:
        logger.warning("Step report   : 無摘要資料，略過（先執行 digest step）")
        return

    logger.info("Step report   : 執行中...")

    def _report_fn(reflect_context: str = "") -> str:
        return self._run_report(compress_data, digests, ctx.today, reflect_context=reflect_context)

    result = ctx.supervisor.run_step(
        "report", _report_fn, force=("report" in ctx.force_steps)
    )
    if result.success:
        report_md.write_text(result.output, encoding="utf-8")
        logger.info("Step report   : 完成 → report.md")
    else:
        logger.error("Step report: 全部重試失敗，略過 save/notify")


def _phase_save(self, ctx: _RunContext, digests: list[dict]) -> None:
    vault_done = ctx.day_dir / "vault.done"

    if "save" not in ctx.steps_to_run:
        return
    if vault_done.exists() and "save" not in ctx.force_steps:
        logger.info("Step save     : 已儲存過，略過")
        return
    if not digests or not (ctx.day_dir / "report.md").exists():
        logger.warning("Step save     : 缺少 report.md 或 digests，略過（先執行 report step）")
        return

    logger.info("Step save     : 執行中...")

    def _save_fn() -> None:
        self._run_save(ctx.day_dir, ctx.today, digests)

    result = ctx.supervisor.run_step(
        "save", _save_fn, force=("save" in ctx.force_steps)
    )
    if result.success:
        vault_done.touch()
        logger.info("Step save     : 完成 → vault.done")
    else:
        logger.error("Step save: 全部重試失敗")


def _phase_notify(self, ctx: _RunContext, digests: list[dict]) -> None:
    done_file = ctx.day_dir / "telegram.done"

    if "notify" not in ctx.steps_to_run:
        return
    if done_file.exists() and "notify" not in ctx.force_steps:
        logger.info("Step notify   : 已發送過，略過")
        return
    if not digests or not (ctx.day_dir / "report.md").exists():
        logger.warning("Step notify   : 缺少 report.md 或摘要資料，略過")
        return

    logger.info("Step notify   : 執行中...")

    def _notify_fn(reflect_context: str = "") -> bool:
        ok = self._notify(digests, ctx.today, steps_dir=ctx.steps_dir, reflect_context=reflect_context)
        if not ok:
            raise RuntimeError("Telegram 訊息發送失敗")
        return ok

    result = ctx.supervisor.run_step(
        "notify", _notify_fn, force=("notify" in ctx.force_steps)
    )
    if result.success:
        done_file.touch()
        logger.info("Step notify   : 完成")
    else:
        logger.error("Step notify   : 部分或全部訊息發送失敗，請用 --force notify 重試")
```

- [ ] **Step 9：用 phase methods 重寫 `run()` 方法**

將整個 `run()` 方法替換為：

```python
def run(self, args: str = "") -> str:
    today = date.today().strftime("%Y-%m-%d")
    force_steps, only_steps = _parse_args(args)

    day_dir = OUTPUT_DIR / today
    steps_dir = day_dir / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)

    from .supervisor import SupervisorAgent
    from tools.notifiers.telegram import send as tg_send

    supervisor = SupervisorAgent(
        llm=self._llm,
        judge_llm=self._judge_llm,
        steps_dir=steps_dir,
        today=today,
        notify_fn=tg_send,
    )
    ctx = _RunContext(
        today=today,
        day_dir=day_dir,
        steps_dir=steps_dir,
        force_steps=force_steps,
        steps_to_run=only_steps or set(ALL_STEPS),
        supervisor=supervisor,
    )

    source_data = self._phase_fetch(ctx)
    if source_data is None:
        return f"Pipeline 中止：fetch 成功不足（需 ≥ 2）"

    compress_data = self._phase_compress(ctx, source_data)
    digests = self._phase_digest(ctx, compress_data)
    compress_data, digests = self._phase_judge(ctx, compress_data, digests)
    self._phase_report(ctx, compress_data, digests)
    self._phase_save(ctx, digests)
    self._phase_notify(ctx, digests)

    return f"完成。輸出目錄：outputs/daily-brief/{today}/"
```

- [ ] **Step 10：執行全套測試確認無退步**

```bash
python3 -m pytest tests/ -v --tb=short
```

預期：全部 PASS。特別確認 `test_run_judge_step_is_wrapped_by_supervisor`、`test_judge_feedback_loop_uses_new_digests_for_retry`、`test_force_judge_passes_force_flag_to_supervisor` 仍通過。

- [ ] **Step 11：Commit**

```bash
git add agents/daily_brief/agent.py tests/test_daily_brief_agent.py
git commit -m "refactor: run() 拆為 7 個 phase methods，加 _RunContext，縮減主流程至 30 行"
```

---

## Task 5：`_notify()` 兩次 LLM 呼叫並行化

**Files:**
- Modify: `agents/daily_brief/agent.py`
- Modify: `tests/test_daily_brief_agent.py`（修正 `test_notify_msg2_limits_digests_to_top8`）

- [ ] **Step 1：更新 `test_notify_msg2_limits_digests_to_top8` 改為內容比對而非位置比對**

找到此測試，將：
```python
msg2_prompt = mock_llm.complete.call_args_list[1][0][0]
```
改為（按 prompt 內容找 digest call）：
```python
all_prompts = [c[0][0] for c in mock_llm.complete.call_args_list]
# digest prompt 包含 top8_json 的內容（"example.com/0" 到 "example.com/7"）
msg2_prompt = next(p for p in all_prompts if "example.com/0" in p and "example.com/7" in p)
```

- [ ] **Step 2：執行測試確認更新後仍通過（基準線）**

```bash
python3 -m pytest tests/test_daily_brief_agent.py::test_notify_msg2_limits_digests_to_top8 -v
```

預期：PASS（確認修改前仍通過）

- [ ] **Step 3：更新 `_notify` 方法為並行**

在 `agents/daily_brief/agent.py` 的 `_notify` 方法，替換為：

```python
def _notify(self, digests: list[dict], today: str, steps_dir: Path | None = None, reflect_context: str = "") -> bool:
    from concurrent.futures import ThreadPoolExecutor
    from tools.notifiers.telegram import send

    digests_json = json.dumps(digests, ensure_ascii=False)
    top8_json = json.dumps(digests[:8], ensure_ascii=False)

    overview_prompt = prompts.build_telegram_overview_prompt(digests_json, today)
    if reflect_context:
        overview_prompt = f"{overview_prompt}\n\n## 修正指示\n{reflect_context}"
    digest_prompt = prompts.build_telegram_digest_prompt(top8_json, today)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_overview = executor.submit(
            lambda: parse_llm_json(self._complete(overview_prompt))
        )
        f_digest = executor.submit(
            lambda: parse_llm_json(self._complete(digest_prompt))
        )
        overview_result = f_overview.result()
        digest_result = f_digest.result()

    overview = overview_result.get("tg_overview", "")
    ok1 = False
    if overview:
        if steps_dir:
            (steps_dir / "telegram_overview.txt").write_text(overview, encoding="utf-8")
        ok1 = send(overview)
        if not ok1:
            logger.error("Step notify   : 第一封訊息發送失敗，telegram.done 不寫入")

    tg_digest = digest_result.get("tg_digest", "")
    ok2 = False
    if tg_digest:
        if steps_dir:
            (steps_dir / "telegram_digest.txt").write_text(tg_digest, encoding="utf-8")
        ok2 = send(tg_digest)
        if not ok2:
            logger.error("Step notify   : 第二封訊息發送失敗，telegram.done 不寫入")

    return ok1 and ok2
```

- [ ] **Step 4：執行 notify 相關測試**

```bash
python3 -m pytest tests/test_daily_brief_agent.py -k "notify" -v
```

預期：全部 PASS

- [ ] **Step 5：執行全套測試**

```bash
python3 -m pytest tests/ -v --tb=short
```

預期：全部 PASS

- [ ] **Step 6：Commit**

```bash
git add agents/daily_brief/agent.py tests/test_daily_brief_agent.py
git commit -m "perf: _notify 兩次 LLM 呼叫改為並行，減少 ~50% notify 步驟等待時間"
```

---

## Task 6：`compress_data` 加 `_meta` 隔離 metadata

**Files:**
- Modify: `agents/daily_brief/agent.py`
- Modify: `tests/test_daily_brief_agent.py`（加 `_meta` 斷言）

背景：`compress_data` 目前把 `compressed_at` 混在來源 key 同層，使後續迭代必須 `if src in FETCH_STEPS` 過濾。改為 `_meta` 子 key，語意更清晰且過濾邏輯變 optional。

⚠️ **注意**：本 Task 改變 `compress.json` 的 schema。執行後，磁碟上的舊 artifact 若含有 `"compressed_at"` 在頂層，需手動刪除或用 `--force compress` 重跑。

- [ ] **Step 1：更新 `test_run_compress_returns_dict_with_all_sources` 加 `_meta` 斷言**

找到此測試，在現有斷言後加：
```python
assert "_meta" in result
assert "compressed_at" in result["_meta"]
# 舊頂層 compressed_at 應消失
assert "compressed_at" not in {k for k in result if k != "_meta"}
```

- [ ] **Step 2：執行測試確認失敗**

```bash
python3 -m pytest tests/test_daily_brief_agent.py::test_run_compress_returns_dict_with_all_sources -v
```

預期：FAIL（目前 `result["_meta"]` 不存在）

- [ ] **Step 3：更新 `_run_compress` 的 metadata 結構**

在 `_run_compress` 方法中，將：
```python
result: dict = {"compressed_at": datetime.now().isoformat(timespec="seconds")}
```
改為：
```python
result: dict = {"_meta": {"compressed_at": datetime.now().isoformat(timespec="seconds")}}
```

- [ ] **Step 4：執行測試確認通過**

```bash
python3 -m pytest tests/test_daily_brief_agent.py::test_run_compress_returns_dict_with_all_sources tests/test_daily_brief_agent.py::test_run_compress_prefilters_to_starred_only -v
```

預期：PASS（`if src in FETCH_STEPS` 篩選邏輯在 `_run_judge` 和 `_check_source_health` 中仍有效，自然跳過 `_meta`）

- [ ] **Step 5：執行全套測試**

```bash
python3 -m pytest tests/ -v --tb=short
```

預期：全部 PASS

- [ ] **Step 6：Commit**

```bash
git add agents/daily_brief/agent.py tests/test_daily_brief_agent.py
git commit -m "refactor: compress_data 的 compressed_at 移至 _meta key，結構語意更清晰"
```

---

## 最終驗證

- [ ] **執行完整測試套件含覆蓋率**

```bash
python3 -m pytest tests/ -v --cov=agents --cov=config --cov=tools --cov-report=term-missing
```

預期：無失敗，覆蓋率維持或提升

- [ ] **執行 lint 驗證**

```bash
python3 lint/check_agent_interface.py
python3 lint/check_fetcher_interface.py
```

預期：無錯誤

- [ ] **確認 agent.py 行數縮減**

```bash
wc -l agents/daily_brief/agent.py
```

預期：≤ 650 行（原 731 行，`run()` 拆出後應縮減約 80+ 行，phase methods 本身頂多等長）

---

## 自我審查

### Spec 覆蓋

| 問題 | Task |
|------|------|
| `_reflect` 無 original_prompt | Task 2 + Task 3 |
| `run()` 300 行 monolith | Task 4 |
| `_parse_json` 重複 | Task 1 |
| Supervisor 耦合 Telegram | Task 3 |
| `judge` strategy plain | Task 2 |
| `compress_data` 結構雜訊 | Task 6 |
| notify 串行 LLM | Task 5 |
| 無耗時 log | Task 3 |

所有 8 個問題均已覆蓋。

### 型別一致性

- `parse_llm_json` 在 Task 1 定義，Task 4 的 `_notify` 使用時已確認匯入正確
- `_RunContext.supervisor` 型別為 `object`（避免循環 import），呼叫時仍有 `run_step` / `run_judge_feedback`，需確認 duck typing 正確
- `notify_fn: Callable[[str], bool] | None` 在 Task 3 定義，Task 4 建立 supervisor 時傳入 `tg_send`，兩者型別一致

### 向後相容性

- Task 6 改變 `compress.json` schema；執行後舊 artifact 若存在需 `--force compress` 重跑
- 其他 tasks 均為純結構重構，既有 artifact 無影響
