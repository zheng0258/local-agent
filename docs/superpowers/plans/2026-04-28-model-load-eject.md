# Model Load/Eject Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `python3 main.py` 執行前自動確認 LM Studio 模型已載入，執行後自動 unload 所有模型。

**Architecture:** 新增 `tools/lms_lifecycle.py` 封裝 `lms` CLI subprocess 呼叫；`main.py` 在 `agent.run()` 前後呼叫 `ensure_models_loaded` / `unload_all`，用 `try/finally` 保證 unload 必然執行。

**Tech Stack:** Python 3、`subprocess`、`pytest`、`unittest.mock`

---

## File Map

| 動作 | 路徑 | 說明 |
|------|------|------|
| Create | `tools/lms_lifecycle.py` | lms CLI 封裝：get_loaded_models / ensure_models_loaded / unload_all |
| Create | `tests/tools/test_lms_lifecycle.py` | 上述函數的 unit tests |
| Modify | `main.py` | 呼叫 ensure_models_loaded / unload_all 包住 agent.run() |

---

## Task 1: `get_loaded_models()` — 解析 lms ps 輸出

**Files:**
- Create: `tools/lms_lifecycle.py`
- Create: `tests/tools/test_lms_lifecycle.py`

### 背景

`lms ps` 輸出如下（空白分隔表格，IDENTIFIER 是第一欄）：

```
IDENTIFIER                                   MODEL                  STATUS
google/gemma-4-e4b                           google/gemma-4-e4b     IDLE
qwen3.5-27b-claude-4.6-opus-distilled-mlx    qwen3.5-27b-...        IDLE
```

- [ ] **Step 1: 建立測試檔 `tests/tools/test_lms_lifecycle.py`，寫 `get_loaded_models` 的 failing tests**

```python
"""tools/lms_lifecycle 測試。"""

import pytest
from unittest.mock import patch, MagicMock

from tools.lms_lifecycle import get_loaded_models


_PS_OUTPUT = (
    "IDENTIFIER                                   MODEL                                        STATUS\n"
    "google/gemma-4-e4b                           google/gemma-4-e4b                           IDLE\n"
    "qwen3.5-27b-claude-4.6-opus-distilled-mlx    qwen3.5-27b-claude-4.6-opus-distilled-mlx    IDLE\n"
)


def _mock_ps(stdout: str = _PS_OUTPUT, returncode: int = 0) -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr="")


@pytest.mark.unit
def test_get_loaded_models_returns_identifiers():
    """lms ps 輸出正確時，回傳所有 IDENTIFIER 的集合。"""
    with patch("tools.lms_lifecycle.subprocess.run", return_value=_mock_ps()) as mock_run:
        result = get_loaded_models()
    mock_run.assert_called_once_with(["lms", "ps"], capture_output=True, text=True)
    assert result == {
        "google/gemma-4-e4b",
        "qwen3.5-27b-claude-4.6-opus-distilled-mlx",
    }


@pytest.mark.unit
def test_get_loaded_models_empty_when_none_loaded():
    """只有標題列時回傳空集合。"""
    stdout = "IDENTIFIER    MODEL    STATUS\n"
    with patch("tools.lms_lifecycle.subprocess.run", return_value=_mock_ps(stdout=stdout)):
        result = get_loaded_models()
    assert result == set()


@pytest.mark.unit
def test_get_loaded_models_returns_empty_on_lms_failure():
    """`lms ps` 回傳 non-zero 時不 raise，回傳空集合。"""
    with patch("tools.lms_lifecycle.subprocess.run", return_value=_mock_ps(returncode=1, stdout="")):
        result = get_loaded_models()
    assert result == set()


@pytest.mark.unit
def test_get_loaded_models_returns_empty_when_lms_not_found():
    """`lms` 不在 PATH 時不 raise，回傳空集合。"""
    with patch("tools.lms_lifecycle.subprocess.run", side_effect=FileNotFoundError):
        result = get_loaded_models()
    assert result == set()
```

- [ ] **Step 2: 執行測試，確認 FAIL（模組尚未建立）**

```bash
cd /Users/guangzhenglee/Workspace/agent
python3 -m pytest tests/tools/test_lms_lifecycle.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` 或 `ImportError`

- [ ] **Step 3: 建立 `tools/lms_lifecycle.py`，實作 `get_loaded_models`**

```python
"""LM Studio model lifecycle management via lms CLI."""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def get_loaded_models() -> set[str]:
    """Execute lms ps and return the set of loaded model identifiers."""
    try:
        result = subprocess.run(["lms", "ps"], capture_output=True, text=True)
    except FileNotFoundError:
        logger.warning("lms not found in PATH, skipping model check")
        return set()

    if result.returncode != 0:
        logger.warning("lms ps failed: %s", result.stderr)
        return set()

    loaded: set[str] = set()
    lines = result.stdout.strip().splitlines()
    for line in lines[1:]:  # skip header
        parts = line.split()
        if parts:
            loaded.add(parts[0])
    return loaded
```

- [ ] **Step 4: 執行測試，確認 PASS**

```bash
python3 -m pytest tests/tools/test_lms_lifecycle.py::test_get_loaded_models_returns_identifiers \
    tests/tools/test_lms_lifecycle.py::test_get_loaded_models_empty_when_none_loaded \
    tests/tools/test_lms_lifecycle.py::test_get_loaded_models_returns_empty_on_lms_failure \
    tests/tools/test_lms_lifecycle.py::test_get_loaded_models_returns_empty_when_lms_not_found \
    -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add tools/lms_lifecycle.py tests/tools/test_lms_lifecycle.py
git commit -m "feat: add lms_lifecycle.get_loaded_models with tests"
```

---

## Task 2: `ensure_models_loaded()` — 檢查並載入缺少的模型

**Files:**
- Modify: `tools/lms_lifecycle.py`
- Modify: `tests/tools/test_lms_lifecycle.py`

- [ ] **Step 1: 在測試檔末尾新增 `ensure_models_loaded` 的 failing tests**

```python
from tools.lms_lifecycle import get_loaded_models, ensure_models_loaded


@pytest.mark.unit
def test_ensure_skips_already_loaded_model():
    """已載入的模型不呼叫 lms load。"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd == ["lms", "ps"]:
            return _mock_ps()  # both models loaded
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("tools.lms_lifecycle.subprocess.run", side_effect=fake_run):
        ensure_models_loaded(["google/gemma-4-e4b"])

    load_calls = [c for c in calls if len(c) > 1 and c[1] == "load"]
    assert load_calls == []


@pytest.mark.unit
def test_ensure_loads_missing_model():
    """未載入的模型會呼叫 lms load <model> -y。"""
    ps_calls = 0

    def fake_run(cmd, **kwargs):
        nonlocal ps_calls
        if cmd == ["lms", "ps"]:
            ps_calls += 1
            if ps_calls == 1:
                return _mock_ps(stdout="IDENTIFIER    MODEL    STATUS\n")  # empty
            return _mock_ps()  # after load: both present
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("tools.lms_lifecycle.subprocess.run", side_effect=fake_run):
        ensure_models_loaded(["google/gemma-4-e4b"])

    # ps called twice (before + verify), load called once
    assert ps_calls == 2


@pytest.mark.unit
def test_ensure_warns_but_does_not_raise_on_load_failure():
    """`lms load` 失敗時只 warning，不 raise。"""
    def fake_run(cmd, **kwargs):
        if cmd == ["lms", "ps"]:
            return _mock_ps(stdout="IDENTIFIER    MODEL    STATUS\n")
        return MagicMock(returncode=1, stdout="", stderr="model not found")

    with patch("tools.lms_lifecycle.subprocess.run", side_effect=fake_run):
        ensure_models_loaded(["google/gemma-4-e4b"])  # must not raise
```

- [ ] **Step 2: 執行測試，確認 FAIL**

```bash
python3 -m pytest tests/tools/test_lms_lifecycle.py::test_ensure_skips_already_loaded_model \
    tests/tools/test_lms_lifecycle.py::test_ensure_loads_missing_model \
    tests/tools/test_lms_lifecycle.py::test_ensure_warns_but_does_not_raise_on_load_failure \
    -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'ensure_models_loaded'`

- [ ] **Step 3: 在 `tools/lms_lifecycle.py` 末尾新增 `ensure_models_loaded`**

```python
def ensure_models_loaded(models: list[str]) -> None:
    """Load any models not currently in lms ps. Verifies after loading."""
    loaded = get_loaded_models()
    for model in models:
        if model not in loaded:
            logger.info("Loading model: %s", model)
            try:
                result = subprocess.run(
                    ["lms", "load", model, "-y"],
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError:
                logger.warning("lms not found in PATH, cannot load model: %s", model)
                continue
            if result.returncode != 0:
                logger.warning("lms load failed for %s: %s", model, result.stderr)

    final = get_loaded_models()
    for model in models:
        if model not in final:
            logger.warning("Model not present after load attempt: %s", model)
```

- [ ] **Step 4: 執行測試，確認 PASS**

```bash
python3 -m pytest tests/tools/test_lms_lifecycle.py::test_ensure_skips_already_loaded_model \
    tests/tools/test_lms_lifecycle.py::test_ensure_loads_missing_model \
    tests/tools/test_lms_lifecycle.py::test_ensure_warns_but_does_not_raise_on_load_failure \
    -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add tools/lms_lifecycle.py tests/tools/test_lms_lifecycle.py
git commit -m "feat: add ensure_models_loaded with load-and-verify logic"
```

---

## Task 3: `unload_all()` — 卸載所有模型

**Files:**
- Modify: `tools/lms_lifecycle.py`
- Modify: `tests/tools/test_lms_lifecycle.py`

- [ ] **Step 1: 在測試檔末尾新增 `unload_all` 的 failing tests**

```python
from tools.lms_lifecycle import get_loaded_models, ensure_models_loaded, unload_all


@pytest.mark.unit
def test_unload_all_calls_lms_unload_all():
    """`unload_all` 呼叫 lms unload --all。"""
    with patch("tools.lms_lifecycle.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
        unload_all()
    mock_run.assert_called_once_with(
        ["lms", "unload", "--all"], capture_output=True, text=True
    )


@pytest.mark.unit
def test_unload_all_does_not_raise_on_failure():
    """`lms unload --all` 失敗時靜默忽略，不 raise。"""
    with patch("tools.lms_lifecycle.subprocess.run", return_value=MagicMock(returncode=1, stderr="err")):
        unload_all()  # must not raise


@pytest.mark.unit
def test_unload_all_does_not_raise_when_lms_not_found():
    """`lms` 不在 PATH 時靜默忽略。"""
    with patch("tools.lms_lifecycle.subprocess.run", side_effect=FileNotFoundError):
        unload_all()  # must not raise
```

- [ ] **Step 2: 執行測試，確認 FAIL**

```bash
python3 -m pytest tests/tools/test_lms_lifecycle.py::test_unload_all_calls_lms_unload_all \
    tests/tools/test_lms_lifecycle.py::test_unload_all_does_not_raise_on_failure \
    tests/tools/test_lms_lifecycle.py::test_unload_all_does_not_raise_when_lms_not_found \
    -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'unload_all'`

- [ ] **Step 3: 在 `tools/lms_lifecycle.py` 末尾新增 `unload_all`**

```python
def unload_all() -> None:
    """Unload all models from LM Studio. Failures are silently ignored."""
    try:
        subprocess.run(["lms", "unload", "--all"], capture_output=True, text=True)
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: 執行所有 lifecycle 測試，確認全部 PASS**

```bash
python3 -m pytest tests/tools/test_lms_lifecycle.py -v
```

Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add tools/lms_lifecycle.py tests/tools/test_lms_lifecycle.py
git commit -m "feat: add unload_all; complete lms_lifecycle module"
```

---

## Task 4: 整合進 `main.py`

**Files:**
- Modify: `main.py` (lines 54–57)

### 背景

目前 `main.py` 的 `main()` 末段：

```python
llm = get_llm()
agent = agent_cls(llm=llm)
print(f"[router] skill={agent.AGENT_NAME}, args={args!r}")
print(agent.run(args))
```

目標：在 `agent.run()` 前加 `ensure_models_loaded`，用 `try/finally` 包住整個執行確保 `unload_all` 必然執行。

- [ ] **Step 1: 修改 `main.py` 的 import 區塊，新增兩行**

在現有 `from config import get_llm, setup_logging` 下方加入：

```python
from tools.lms_lifecycle import ensure_models_loaded, unload_all
from config.settings import DEFAULT_LOCAL_LLM_MODEL, DEFAULT_JUDGE_LLM_MODEL
```

- [ ] **Step 2: 修改 `main()` 末段，加入 lifecycle 呼叫**

將：

```python
    llm = get_llm()
    agent = agent_cls(llm=llm)
    print(f"[router] skill={agent.AGENT_NAME}, args={args!r}")
    print(agent.run(args))
```

改為：

```python
    llm = get_llm()
    agent = agent_cls(llm=llm)
    print(f"[router] skill={agent.AGENT_NAME}, args={args!r}")
    ensure_models_loaded([DEFAULT_LOCAL_LLM_MODEL, DEFAULT_JUDGE_LLM_MODEL])
    try:
        print(agent.run(args))
    finally:
        unload_all()
```

- [ ] **Step 3: 執行 smoke test，確認 import 正常**

```bash
cd /Users/guangzhenglee/Workspace/agent
python3 -c "import main; print('import ok')"
```

Expected: `import ok`

- [ ] **Step 4: 執行完整測試套件，確認無回歸**

```bash
python3 -m pytest tests/ -v --ignore=tests/tools/test_lms_lifecycle.py -x 2>&1 | tail -20
```

Expected: 原有測試全部通過（不新增失敗）

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: integrate model load/eject lifecycle into main.py"
```
