# Model Load/Eject Lifecycle Design

**Date:** 2026-04-28  
**Status:** Approved

## Problem

Daily-brief pipeline 執行前需要確保 LM Studio 模型已載入；執行完畢後應釋放所有模型記憶體。目前模型需手動管理，排程執行時沒有保護。

## Goals

- 執行 `python3 main.py` 任何方式（CLI、n8n 排程、手動）都自動確保模型已載入
- Pipeline 結束後（成功或失敗）自動 `lms unload --all`
- 若模型已載入，不重複 load

## Out of Scope

- Embedding 模型（`qwen3-embedding-0.6b-dwq`）透過 `mlx_lm` 直接管理，不在此範圍
- n8n workflow 不需修改

## Architecture

### 新增模組：`tools/lms_lifecycle.py`

封裝所有 `lms` CLI subprocess 呼叫。

```
tools/
└── lms_lifecycle.py   ← 新增
```

### 修改：`main.py`

在 `agent.run()` 前後加 load/unload 呼叫。

## Component Design

### `tools/lms_lifecycle.py`

```python
REQUIRED_MODELS = [
    DEFAULT_LOCAL_LLM_MODEL,   # qwen3.5-27b-claude-4.6-opus-distilled-mlx
    DEFAULT_JUDGE_LLM_MODEL,   # google/gemma-4-e4b
]

def get_loaded_models() -> set[str]:
    """執行 lms ps，解析 IDENTIFIER 欄，回傳已載入模型識別碼集合。"""

def ensure_models_loaded(models: list[str]) -> None:
    """
    1. get_loaded_models() 取得當前清單
    2. 對每個缺少的模型執行 lms load <model> -y（阻塞）
    3. 重新 get_loaded_models() 驗證，若仍缺少則 warning（不中斷）
    """

def unload_all() -> None:
    """執行 lms unload --all，失敗靜默忽略。"""
```

### `main.py` 修改

```python
from tools.lms_lifecycle import ensure_models_loaded, unload_all
from config.settings import DEFAULT_LOCAL_LLM_MODEL, DEFAULT_JUDGE_LLM_MODEL

# 在 agent.run() 之前
ensure_models_loaded([DEFAULT_LOCAL_LLM_MODEL, DEFAULT_JUDGE_LLM_MODEL])
try:
    print(agent.run(args))
finally:
    unload_all()
```

## Data Flow

```
python3 main.py "/daily-brief"
  → get_loaded_models()            # lms ps 解析
  → lms load qwen3.5-27b... -y    # 若未載入（阻塞等完成）
  → lms load google/gemma-4-e4b -y # 若未載入（阻塞等完成）
  → get_loaded_models() 驗證       # 確認兩個模型都在清單
  → DailyBriefAgent.run()
  → lms unload --all               # try/finally 保證執行
```

## Error Handling

| 情境 | 行為 |
|------|------|
| `lms` 不在 PATH | warning，繼續執行（讓 API 呼叫自然失敗） |
| `lms load` exit code != 0 | warning + 記錄 stderr，繼續 |
| 驗證後模型仍不在清單 | warning，繼續 |
| `lms unload --all` 失敗 | 靜默忽略 |

所有錯誤都是 warning 而非 exception，確保不因 lifecycle 管理失敗而中斷 pipeline 本身。

## Load 順序保證

`subprocess.run(["lms", "load", model, "-y"])` 是阻塞呼叫，Python 進程等待 `lms load` 指令完成才繼續。load 完成後再執行 `lms ps` 驗證確認模型已就緒，雙重保護。

## Testing

`tests/tools/test_lms_lifecycle.py`：

- mock `subprocess.run`，驗證已載入模型不重複 load
- 驗證缺少的模型會呼叫 `lms load <model> -y`
- 驗證 `unload_all` 呼叫 `lms unload --all`
- 驗證 load 失敗時只 warning 不 raise
