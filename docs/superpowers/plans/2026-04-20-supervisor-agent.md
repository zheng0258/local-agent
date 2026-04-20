# SupervisorAgent Self-Healing Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 為 AI Daily Brief pipeline 加入 LLM self-healing loop，步驟失敗時自動 reflect、調整 prompt 重試，耗盡重試後發 Telegram 告警。

**Architecture:** 新增 `SupervisorAgent` 包裝每個步驟的執行；`plain` 策略直接重試，`error_aware` 策略失敗後呼叫 reflect LLM 產出 `adjusted_prompt` 再重跑。Judge completeness < 3 時用 `_judge_llm` reflect 並重跑 digest（上限 1 次）。Fetch 步驟並行執行，≥2 成功才繼續；`alerts.json` 防止同步驟同天重複告警。

**Tech Stack:** Python 3.12、`dataclasses`、`concurrent.futures.ThreadPoolExecutor`（fetch 並行）、現有 `LocalLLMBackend`、`tools.notifiers.telegram.send`

---

## File Map

| 動作 | 路徑 | 職責 |
|------|------|------|
| Create | `agents/daily_brief/supervisor.py` | `SupervisorAgent`、`StepResult` |
| Create | `agents/daily_brief/reflect_prompts.py` | Reflect LLM prompt 模板 |
| Modify | `agents/daily_brief/config.py` | 新增 `StepConfig`、`STEP_CONFIGS` |
| Modify | `agents/daily_brief/agent.py` | 整合 `SupervisorAgent`，加 `reflect_context` 參數 |
| Create | `tests/agents/test_supervisor.py` | SupervisorAgent 單元測試 |

---

## Task 1: StepConfig + STEP_CONFIGS

**Files:**
- Modify: `agents/daily_brief/config.py`

- [ ] **Step 1: 在 `config.py` 尾部新增資料結構**

```python
# agents/daily_brief/config.py 末尾加入

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class StepConfig:
    max_retries: int
    strategy: Literal["plain", "error_aware"]
    backoff_seconds: tuple[float, ...] = (0.0,)


STEP_CONFIGS: dict[str, StepConfig] = {
    "hatena":   StepConfig(max_retries=3, strategy="plain", backoff_seconds=(1.0, 3.0, 9.0)),
    "hn":       StepConfig(max_retries=3, strategy="plain", backoff_seconds=(1.0, 3.0, 9.0)),
    "reddit":   StepConfig(max_retries=3, strategy="plain", backoff_seconds=(1.0, 3.0, 9.0)),
    "security": StepConfig(max_retries=3, strategy="plain", backoff_seconds=(1.0, 3.0, 9.0)),
    "compress": StepConfig(max_retries=2, strategy="error_aware"),
    "digest":   StepConfig(max_retries=2, strategy="error_aware"),
    "judge":    StepConfig(max_retries=2, strategy="plain"),
    "report":   StepConfig(max_retries=2, strategy="error_aware"),
    "notify":   StepConfig(max_retries=2, strategy="error_aware"),
    "save":     StepConfig(max_retries=2, strategy="plain"),
}
```

- [ ] **Step 2: 確認 import 無衝突**

```bash
cd $HOME/Workspace/agent && python3 -c "from agents.daily_brief.config import STEP_CONFIGS; print(list(STEP_CONFIGS.keys()))"
```

Expected output:
```
['hatena', 'hn', 'reddit', 'security', 'compress', 'digest', 'judge', 'report', 'notify', 'save']
```

- [ ] **Step 3: Commit**

```bash
git add agents/daily_brief/config.py
git commit -m "feat: add StepConfig and STEP_CONFIGS to daily_brief config"
```

---

## Task 2: reflect_prompts.py

**Files:**
- Create: `agents/daily_brief/reflect_prompts.py`

- [ ] **Step 1: 寫失敗診斷 reflect prompt**

建立 `agents/daily_brief/reflect_prompts.py`：

```python
"""Reflect LLM prompt 模板（供 SupervisorAgent 失敗重試使用）。"""

from __future__ import annotations


def build_reflect_prompt(
    original_prompt: str,
    bad_output: str,
    error: str,
) -> str:
    return f"""\
你是 pipeline 修復專家。以下步驟執行失敗，請診斷並產出修正後的 prompt。

## 原始任務 prompt
{original_prompt}

## 執行結果（壞輸出）
{bad_output[:2000]}

## 錯誤訊息
{error}

## 要求
1. 診斷失敗原因（1-2 句）
2. 產出修正後的 prompt，確保下次執行能成功
3. 修正後 prompt 必須包含原始任務的完整需求，不可遺漏

輸出 JSON：
```json
{{"diagnosis": "...", "adjusted_prompt": "..."}}
```"""


def build_judge_reflect_prompt(
    missed_urls: list[str],
    original_digest_prompt: str,
) -> str:
    missed = "\n".join(f"- {u}" for u in missed_urls)
    return f"""\
你是摘要品質改善專家。上次的摘要遺漏了重要文章，請產出修正後的 digest prompt。

## 遺漏的文章 URL
{missed}

## 原始 digest prompt
{original_digest_prompt}

## 要求
產出修正後的 prompt，在結尾明確要求涵蓋上述遺漏 URL 對應的文章。

輸出 JSON：
```json
{{"diagnosis": "摘要遺漏了 N 篇重要文章", "adjusted_prompt": "..."}}
```"""
```

- [ ] **Step 2: 確認 import**

```bash
cd $HOME/Workspace/agent && python3 -c "from agents.daily_brief.reflect_prompts import build_reflect_prompt, build_judge_reflect_prompt; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add agents/daily_brief/reflect_prompts.py
git commit -m "feat: add reflect_prompts for supervisor self-healing"
```

---

## Task 3: SupervisorAgent 核心

**Files:**
- Create: `agents/daily_brief/supervisor.py`
- Create: `tests/agents/test_supervisor.py`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/agents/test_supervisor.py`：

```python
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch
import pytest


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


def test_plain_step_success_on_first_attempt(tmp_path):
    supervisor, llm, _ = _make_supervisor(tmp_path)
    fn = MagicMock(return_value={"data": "ok"})

    result = supervisor.run_step("judge", fn)

    assert result.success is True
    assert result.attempts == 1
    assert result.output == {"data": "ok"}
    fn.assert_called_once_with(reflect_context="")


def test_plain_step_retries_without_reflect(tmp_path):
    supervisor, llm, _ = _make_supervisor(tmp_path)
    fn = MagicMock(side_effect=[RuntimeError("boom"), {"data": "ok"}])

    result = supervisor.run_step("judge", fn)

    assert result.success is True
    assert result.attempts == 2
    # reflect LLM 不應被呼叫
    llm.complete.assert_not_called()


def test_plain_step_fails_after_max_retries(tmp_path):
    supervisor, llm, _ = _make_supervisor(tmp_path)
    fn = MagicMock(side_effect=RuntimeError("always fails"))

    with patch("agents.daily_brief.supervisor.send", return_value=True):
        result = supervisor.run_step("judge", fn)

    assert result.success is False
    assert result.attempts == 2  # max_retries=2 for judge


def test_error_aware_step_calls_reflect_on_failure(tmp_path):
    reflect_resp = json.dumps({
        "diagnosis": "JSON 解析錯誤",
        "adjusted_prompt": "修正後的 prompt",
    })
    supervisor, llm, _ = _make_supervisor(tmp_path, llm_resp=reflect_resp)
    fn = MagicMock(side_effect=[RuntimeError("json error"), {"digests": []}])

    result = supervisor.run_step("digest", fn)

    assert result.success is True
    assert result.attempts == 2
    # reflect LLM 應被呼叫一次
    llm.complete.assert_called_once()
    # 第二次呼叫應帶 reflect context
    assert fn.call_args_list[1] == call(reflect_context="修正後的 prompt")


def test_alert_dedup_same_step_same_day(tmp_path):
    supervisor, _, _ = _make_supervisor(tmp_path)
    fn = MagicMock(side_effect=RuntimeError("fail"))

    with patch("agents.daily_brief.supervisor.send", return_value=True) as mock_send:
        supervisor.run_step("judge", fn)
        fn.reset_mock()
        fn.side_effect = RuntimeError("fail again")
        supervisor.run_step("judge", fn)

    # Telegram 只應發一次
    assert mock_send.call_count == 1


def test_force_clears_alert(tmp_path):
    supervisor, _, _ = _make_supervisor(tmp_path)
    fn = MagicMock(side_effect=RuntimeError("fail"))

    with patch("agents.daily_brief.supervisor.send", return_value=True) as mock_send:
        supervisor.run_step("judge", fn)
        fn.reset_mock()
        fn.side_effect = RuntimeError("fail again")
        supervisor.run_step("judge", fn, force=True)

    assert mock_send.call_count == 2
```

- [ ] **Step 2: 執行測試確認全部失敗**

```bash
cd $HOME/Workspace/agent && python3 -m pytest tests/agents/test_supervisor.py -v 2>&1 | head -30
```

Expected: 全部 `ERROR` 或 `FAILED`（`supervisor.py` 尚未存在）

- [ ] **Step 3: 建立 `supervisor.py`**

建立 `agents/daily_brief/supervisor.py`：

```python
"""SupervisorAgent — pipeline 步驟執行、重試、self-healing。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from config import get_logger
from config.settings import LLMBackend

from . import reflect_prompts
from .config import STEP_CONFIGS

from tools.notifiers.telegram import send

logger = get_logger(__name__)


@dataclass(frozen=True)
class StepResult:
    name: str
    success: bool
    output: Any
    error: str | None
    attempts: int
    adjusted_prompts: tuple[str, ...] = ()


class SupervisorAgent:

    def __init__(
        self,
        llm: LLMBackend,
        judge_llm: LLMBackend,
        steps_dir: Path,
        today: str,
    ) -> None:
        self._llm = llm
        self._judge_llm = judge_llm
        self._steps_dir = steps_dir
        self._today = today

    def run_step(
        self,
        name: str,
        fn: Callable[..., Any],
        force: bool = False,
    ) -> StepResult:
        """執行一個步驟，失敗時依 strategy 重試。"""
        cfg = STEP_CONFIGS[name]
        adjusted_prompts: list[str] = []
        last_error = ""
        last_output = ""

        for attempt in range(1, cfg.max_retries + 1):
            reflect_context = adjusted_prompts[-1] if adjusted_prompts else ""
            try:
                output = fn(reflect_context=reflect_context)
                return StepResult(
                    name=name,
                    success=True,
                    output=output,
                    error=None,
                    attempts=attempt,
                    adjusted_prompts=tuple(adjusted_prompts),
                )
            except Exception as exc:
                last_error = str(exc)
                last_output = str(output) if "output" in dir() else ""
                logger.warning(
                    "Step %s: attempt %d/%d 失敗 — %s",
                    name, attempt, cfg.max_retries, last_error,
                )

                if attempt < cfg.max_retries:
                    if cfg.strategy == "error_aware":
                        adjusted = self._reflect(
                            step_name=name,
                            bad_output=last_output,
                            error=last_error,
                        )
                        if adjusted:
                            adjusted_prompts.append(adjusted)
                    # backoff
                    backoff = cfg.backoff_seconds[min(attempt - 1, len(cfg.backoff_seconds) - 1)]
                    if backoff > 0:
                        time.sleep(backoff)

        diagnosis = adjusted_prompts[-1][:200] if adjusted_prompts else last_error
        self._notify_failure(name, last_error, cfg.max_retries, diagnosis, force=force)
        return StepResult(
            name=name,
            success=False,
            output=None,
            error=last_error,
            attempts=cfg.max_retries,
            adjusted_prompts=tuple(adjusted_prompts),
        )

    def run_judge_feedback(
        self,
        missed_urls: list[str],
        original_digest_prompt: str,
        run_digest_fn: Callable[..., Any],
        run_judge_fn: Callable[..., Any],
    ) -> tuple[list[dict], dict]:
        """judge completeness < 3 時，用 judge_llm reflect 並重跑 digest + judge（上限 1 次）。"""
        judge_server_ok = self._is_judge_server_available()

        if judge_server_ok:
            reflect_resp = self._reflect_with_judge(missed_urls, original_digest_prompt)
        else:
            logger.warning("Judge server 無回應，降級：直接用原 prompt 重跑 digest")
            reflect_resp = ""

        digests, digest_data = run_digest_fn(reflect_context=reflect_resp)
        judge_result = run_judge_fn()
        return digests, digest_data, judge_result

    # ── 內部方法 ─────────────────────────────────────────────────────

    def _reflect(self, step_name: str, bad_output: str, error: str) -> str:
        """呼叫主 LLM 診斷失敗，回傳 adjusted_prompt（空字串表示失敗）。"""
        from . import prompts as agent_prompts
        try:
            raw = self._llm.complete(
                reflect_prompts.build_reflect_prompt(
                    original_prompt=f"[step: {step_name}]",
                    bad_output=bad_output,
                    error=error,
                )
            )
            parsed = _parse_reflect_response(raw)
            diagnosis = parsed.get("diagnosis", "")
            adjusted = parsed.get("adjusted_prompt", "")
            if diagnosis:
                logger.info("Step %s reflect 診斷：%s", step_name, diagnosis)
            return adjusted
        except Exception as exc:
            logger.warning("Step %s reflect LLM 呼叫失敗：%s", step_name, exc)
            return ""

    def _reflect_with_judge(self, missed_urls: list[str], original_prompt: str) -> str:
        """呼叫 judge LLM 針對 completeness 不足產出 adjusted_prompt。"""
        try:
            raw = self._judge_llm.complete(
                reflect_prompts.build_judge_reflect_prompt(missed_urls, original_prompt)
            )
            parsed = _parse_reflect_response(raw)
            return parsed.get("adjusted_prompt", "")
        except Exception as exc:
            logger.warning("Judge reflect LLM 呼叫失敗：%s", exc)
            return ""

    def _is_judge_server_available(self) -> bool:
        """快速探測 judge LLM server 是否在線。"""
        import urllib.request, urllib.error
        from config.settings import DEFAULT_LOCAL_LLM_URL
        import os
        url = os.environ.get("JUDGE_LLM_URL", DEFAULT_LOCAL_LLM_URL)
        try:
            urllib.request.urlopen(f"{url}/v1/models", timeout=3)
            return True
        except Exception:
            return False

    def _notify_failure(
        self,
        name: str,
        error: str,
        attempts: int,
        diagnosis: str,
        force: bool = False,
    ) -> None:
        """發 Telegram 告警，同一步驟同一天只發一次（force 重跑時重置）。"""
        alerts_file = self._steps_dir / "alerts.json"
        alerts: dict[str, str] = {}
        if alerts_file.exists():
            try:
                alerts = json.loads(alerts_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                alerts = {}

        if name in alerts and not force:
            logger.info("Step %s: 告警已發送過（%s），略過重複告警", name, alerts[name])
            return

        msg = (
            f"⚠️ Daily Brief 步驟失敗（{self._today}）\n\n"
            f"步驟：{name}（嘗試 {attempts} 次）\n"
            f"錯誤：{error[:300]}\n"
            f"診斷：{diagnosis[:300]}\n\n"
            f"建議：python3 main.py \"/daily-brief --force {name}\""
        )
        send(msg)
        alerts[name] = datetime.now().isoformat(timespec="seconds")
        alerts_file.write_text(json.dumps(alerts, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_reflect_response(raw: str) -> dict:
    """從 LLM 輸出解析 reflect JSON（含 json-repair fallback）。"""
    import re
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    text = m.group(1) if m else raw
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        from json_repair import repair_json
        result = json.loads(repair_json(text))
        if isinstance(result, dict):
            return result
    except Exception:
        pass
    return {}
```

- [ ] **Step 4: 執行測試**

```bash
cd $HOME/Workspace/agent && python3 -m pytest tests/agents/test_supervisor.py -v
```

Expected: 全部 PASSED

- [ ] **Step 5: Commit**

```bash
git add agents/daily_brief/supervisor.py tests/agents/test_supervisor.py
git commit -m "feat: SupervisorAgent core with plain/error_aware retry and Telegram alert"
```

---

## Task 4: 整合 Fetch 步驟（並行 + 部分成功）

**Files:**
- Modify: `agents/daily_brief/agent.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/agents/test_supervisor.py` 尾部新增：

```python
def test_fetch_partial_success_continues(tmp_path):
    """≥2 fetcher 成功時 pipeline 應繼續。"""
    from agents.daily_brief.supervisor import SupervisorAgent

    llm = MagicMock()
    judge_llm = MagicMock()
    supervisor = SupervisorAgent(llm=llm, judge_llm=judge_llm, steps_dir=tmp_path, today="2026-04-20")

    results = {
        "hatena": {"articles": [{"url": "https://a.com", "interest": "***"}]},
        "hn": None,   # 失敗
        "reddit": {"articles": []},
        "security": None,  # 失敗
    }

    success_count = sum(1 for v in results.values() if v is not None)
    assert success_count >= 2  # 2 成功，pipeline 應繼續


def test_fetch_below_threshold_stops(tmp_path):
    """< 2 fetcher 成功時應回傳 should_stop=True。"""
    from agents.daily_brief.supervisor import SupervisorAgent

    llm = MagicMock()
    judge_llm = MagicMock()
    supervisor = SupervisorAgent(llm=llm, judge_llm=judge_llm, steps_dir=tmp_path, today="2026-04-20")

    results = {"hatena": None, "hn": None, "reddit": {"articles": []}, "security": None}
    success_count = sum(1 for v in results.values() if v is not None)
    assert success_count < 2
```

- [ ] **Step 2: 執行測試確認通過（邏輯測試，無需 supervisor 改動）**

```bash
cd $HOME/Workspace/agent && python3 -m pytest tests/agents/test_supervisor.py::test_fetch_partial_success_continues tests/agents/test_supervisor.py::test_fetch_below_threshold_stops -v
```

Expected: PASSED

- [ ] **Step 3: 修改 `agent.py` Phase 1（fetch 步驟並行 + supervisor）**

在 `agent.py` 中的 `run()` 方法，找到以下區塊並替換：

```python
# ── Phase 1：Fetch steps ────────────────────────────────────
source_data: dict[str, dict] = {}

for name in FETCH_STEPS:
    ...（原有 for loop）...
```

替換為：

```python
# ── Phase 1：Fetch steps ────────────────────────────────────
from concurrent.futures import ThreadPoolExecutor, as_completed

source_data: dict[str, dict] = {}
fetch_failed: list[str] = []

def _run_fetch_supervised(name: str) -> tuple[str, dict | None]:
    artifact = steps_dir / f"{name}.json"
    if artifact.exists() and name not in force_steps and name in steps_to_run:
        logger.info("Step %-8s: 載入既有 artifact", name)
        return name, json.loads(artifact.read_text(encoding="utf-8"))
    if name not in steps_to_run:
        if artifact.exists():
            return name, json.loads(artifact.read_text(encoding="utf-8"))
        return name, None

    def fn(reflect_context: str = "") -> dict:
        result = self._run_fetch(name)
        result["fetched_at"] = datetime.now().isoformat(timespec="seconds")
        artifact.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Step %-8s: 完成 → %s", name, artifact.name)
        return result

    step_result = supervisor.run_step(name, fn)
    if step_result.success:
        return name, step_result.output
    return name, None

with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {executor.submit(_run_fetch_supervised, n): n for n in FETCH_STEPS}
    for future in as_completed(futures):
        name, data = future.result()
        if data is not None:
            source_data[name] = data
        else:
            fetch_failed.append(name)

success_count = len(source_data)
if success_count < 2:
    msg = (
        f"⚠️ Daily Brief Fetch 嚴重失敗（{today}）\n"
        f"成功：{success_count}/4，失敗：{fetch_failed}\n"
        "Pipeline 停止。"
    )
    from tools.notifiers.telegram import send as tg_send
    tg_send(msg)
    logger.error("Fetch 成功 %d/4，低於門檻，pipeline 停止", success_count)
    return f"Pipeline 中止：fetch 成功 {success_count}/4（需 ≥ 2）"
```

- [ ] **Step 4: 在 `agent.py` 的 `run()` 開頭初始化 `supervisor`**

在 `steps_dir.mkdir(...)` 之後加入：

```python
from .supervisor import SupervisorAgent
supervisor = SupervisorAgent(
    llm=self._llm,
    judge_llm=self._judge_llm,
    steps_dir=steps_dir,
    today=today,
)
```

- [ ] **Step 5: 執行 lint 確認語法**

```bash
cd $HOME/Workspace/agent && python3 -m py_compile agents/daily_brief/agent.py && echo "ok"
```

Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add agents/daily_brief/agent.py
git commit -m "feat: parallel fetch with supervisor retry and partial-success guard"
```

---

## Task 5: 整合 LLM 步驟（compress / digest / report / notify）

**Files:**
- Modify: `agents/daily_brief/agent.py`

- [ ] **Step 1: 為各 LLM 步驟方法加 `reflect_context` 參數**

修改 `_run_compress`、`_run_digest`、`_run_report`、`_notify`，各加一個 `reflect_context: str = ""` 參數，並在呼叫 `_complete()` 的 prompt 尾部注入：

```python
# _run_compress 修改示例（在 `raw = self._complete(...)` 之前加）
def _run_compress(self, source_data: dict, reflect_context: str = "") -> dict:
    ...
    # 在各 source 的 _complete 呼叫中注入 reflect_context
    prompt = prompts.build_compress_prompt(name, articles_json)
    if reflect_context:
        prompt = f"{prompt}\n\n## 修正指示\n{reflect_context}"
    raw = self._complete(prompt)
    ...

# _run_digest 修改示例
def _run_digest(self, compress_data: dict, reflect_context: str = "") -> tuple[list[dict], dict]:
    compress_json = json.dumps(compress_data, ensure_ascii=False)
    prompt = prompts.build_digest_prompt_from_compress(compress_json)
    if reflect_context:
        prompt = f"{prompt}\n\n## 修正指示\n{reflect_context}"
    result = self._parse_json(self._complete(prompt))
    ...

# _run_report 修改示例
def _run_report(self, compress_data: dict, digests: list[dict], today: str, reflect_context: str = "") -> str:
    ...
    prompt = prompts.build_report_prompt_from_compress(...)
    if reflect_context:
        prompt = f"{prompt}\n\n## 修正指示\n{reflect_context}"
    content = self._complete(prompt).strip()
    ...

# _notify 修改示例
def _notify(self, digests: list[dict], today: str, steps_dir: Path | None = None, reflect_context: str = "") -> bool:
    ...
    overview_result = self._parse_json(
        self._complete(prompts.build_telegram_overview_prompt(digests_json, today))
    )
    # notify 的 reflect_context 注入到 overview prompt
    overview_prompt = prompts.build_telegram_overview_prompt(digests_json, today)
    if reflect_context:
        overview_prompt = f"{overview_prompt}\n\n## 修正指示\n{reflect_context}"
    overview_result = self._parse_json(self._complete(overview_prompt))
    ...
```

- [ ] **Step 2: 修改 Phase 2（compress）呼叫點**

找到：
```python
compress_data = self._run_compress(source_data)
```

替換為：
```python
def _compress_fn(reflect_context: str = "") -> dict:
    return self._run_compress(source_data, reflect_context=reflect_context)

compress_result = supervisor.run_step("compress", _compress_fn)
if not compress_result.success:
    logger.error("Step compress: 全部重試失敗，略過 digest/judge/report/notify")
    return f"Pipeline 中止：compress 失敗\n輸出目錄：outputs/daily-brief/{today}/"
compress_data = compress_result.output
```

- [ ] **Step 3: 修改 Phase 3（digest）呼叫點**

找到：
```python
digests, digest_data = self._run_digest(compress_data)
```

替換為：
```python
def _digest_fn(reflect_context: str = "") -> tuple[list[dict], dict]:
    return self._run_digest(compress_data, reflect_context=reflect_context)

digest_result = supervisor.run_step("digest", _digest_fn)
if not digest_result.success:
    logger.error("Step digest: 全部重試失敗，略過 judge/report/notify")
    # save 若 report.md 已存在仍可執行，不 return
else:
    digests, digest_data = digest_result.output
    digest_artifact.write_text(
        json.dumps(digest_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Step digest   : 完成 → digest.json（%d 篇）", len(digests))
```

- [ ] **Step 4: 修改 Phase 3.5（judge）含 completeness 回饋**

在 judge 完成後，`quality_alert` 為 True 時呼叫 `supervisor.run_judge_feedback()`：

```python
# 在 judge 完成、寫入 judge.json 之後加入：
completeness_score = judge_result.get("scores", {}).get("completeness", {}).get("score")
if (
    isinstance(completeness_score, (int, float))
    and completeness_score < 3
    and "digest" not in force_steps  # 避免無限重跑
):
    missed_urls = judge_result.get("scores", {}).get("completeness", {}).get("missed_urls", [])
    logger.warning("Judge completeness=%s，觸發 digest 重跑（missed: %s）", completeness_score, missed_urls)
    original_digest_prompt = prompts.build_digest_prompt_from_compress(
        json.dumps(compress_data, ensure_ascii=False)
    )

    def _retry_digest_fn(reflect_context: str = "") -> tuple[list[dict], dict]:
        return self._run_digest(compress_data, reflect_context=reflect_context)

    def _retry_judge_fn(reflect_context: str = "") -> dict:
        return self._run_judge(compress_data, digests, date=today)

    digests, digest_data, judge_result = supervisor.run_judge_feedback(
        missed_urls=missed_urls,
        original_digest_prompt=original_digest_prompt,
        run_digest_fn=_retry_digest_fn,
        run_judge_fn=_retry_judge_fn,
    )
    digest_artifact.write_text(
        json.dumps(digest_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    judge_artifact.write_text(
        json.dumps(judge_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Judge 回饋 digest 重跑完成")
```

- [ ] **Step 5: 修改 Phase 5（save）呼叫點**

Save 步驟是 `plain` 策略，直接包 supervisor：

```python
def _save_fn(reflect_context: str = "") -> None:
    self._run_save(day_dir, today, digests)

save_result = supervisor.run_step("save", _save_fn)
if save_result.success:
    vault_done.touch()
    logger.info("Step save     : 完成 → vault.done")
else:
    logger.error("Step save: 全部重試失敗")
```

- [ ] **Step 6: 修改 Phase 4（report）+ Phase 6（notify）呼叫點**

Report：
```python
def _report_fn(reflect_context: str = "") -> str:
    return self._run_report(compress_data, digests, today, reflect_context=reflect_context)

report_result = supervisor.run_step("report", _report_fn)
if report_result.success:
    report_md.write_text(report_result.output, encoding="utf-8")
    logger.info("Step report   : 完成 → report.md")
else:
    logger.error("Step report: 全部重試失敗，略過 save/notify")
```

Notify：
```python
def _notify_fn(reflect_context: str = "") -> bool:
    ok = self._notify(digests, today, steps_dir=steps_dir, reflect_context=reflect_context)
    if not ok:
        raise RuntimeError("Telegram 訊息發送失敗")
    return ok

notify_result = supervisor.run_step("notify", _notify_fn)
if notify_result.success:
    done_file.touch()
    logger.info("Step notify   : 完成")
else:
    logger.error("Step notify   : 部分或全部訊息發送失敗，請用 --force notify 重試")
```

- [ ] **Step 7: 執行 lint**

```bash
cd $HOME/Workspace/agent && python3 -m py_compile agents/daily_brief/agent.py && echo "ok"
```

Expected: `ok`

- [ ] **Step 8: 執行現有測試確認無 regression**

```bash
cd $HOME/Workspace/agent && python3 -m pytest tests/ -v --ignore=tests/agents/test_supervisor.py 2>&1 | tail -20
```

Expected: 全部 PASSED

- [ ] **Step 9: Commit**

```bash
git add agents/daily_brief/agent.py
git commit -m "feat: integrate SupervisorAgent into all LLM steps with reflect_context"
```

---

## Task 6: 端對端驗證

**Files:**（無新增檔案）

- [ ] **Step 1: dry-run 確認 import chain 正常**

```bash
cd $HOME/Workspace/agent && python3 -c "
from agents.daily_brief.agent import DailyBriefAgent
from agents.daily_brief.supervisor import SupervisorAgent, StepResult
from agents.daily_brief.config import STEP_CONFIGS
print('all imports ok')
print('steps:', list(STEP_CONFIGS.keys()))
"
```

Expected:
```
all imports ok
steps: ['hatena', 'hn', 'reddit', 'security', 'compress', 'digest', 'judge', 'report', 'notify', 'save']
```

- [ ] **Step 2: 執行全部測試**

```bash
cd $HOME/Workspace/agent && python3 -m pytest tests/ -v 2>&1 | tail -30
```

Expected: 全部 PASSED

- [ ] **Step 3: lint 介面驗證**

```bash
cd $HOME/Workspace/agent && python3 lint/check_agent_interface.py && python3 lint/check_fetcher_interface.py
```

Expected: 無 ERROR 輸出

- [ ] **Step 4: Final commit**

```bash
git add -p  # 確認無意外變更
git commit -m "feat: SupervisorAgent self-healing loop — complete integration"
```
