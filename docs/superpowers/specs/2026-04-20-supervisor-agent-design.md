# SupervisorAgent 設計文件

**日期**：2026-04-20  
**範疇**：為 AI Daily Brief pipeline 加入 LLM Self-Healing Loop，確保每個步驟失敗時能自動診斷、調整 prompt、重試，並在耗盡重試後發送 Telegram 告警。

---

## 背景與動機

目前 pipeline 步驟失敗時只記 log，`telegram.done` 等 sentinel 可能在部分失敗時仍被寫入（已修復），但整體缺乏自動恢復機制。本設計引入 `SupervisorAgent` 作為執行層，讓 LLM 在失敗時自我診斷並調整 prompt 重試。

---

## 架構概覽

```
SupervisorAgent
├── run_step(name, fn, prompt) → StepResult
│     ├── attempt 1: fn(prompt)
│     │     成功 → StepResult(success=True)
│     │     失敗 ↓
│     ├── reflect: _llm.complete(reflect_prompt) → adjusted_prompt
│     ├── attempt 2: fn(adjusted_prompt)
│     │     成功 → StepResult(success=True, attempts=2)
│     │     失敗 ↓
│     └── _notify_failure() → Telegram 告警，回傳 StepResult(success=False)
├── _build_reflect_prompt(original, bad_output, error) → str
├── _notify_failure(name, error, attempts) → None（去重）
└── STEP_CONFIGS：每步驟 max_retries + strategy

DailyBriefAgent（現有）
└── 透過 self._supervisor.run_step() 驅動各步驟，業務邏輯不動
```

**Reflect LLM（分情境）**：
- 執行失敗（JSON 解析錯、空輸出、網路錯誤）→ `self._llm`（理解任務 context、生成修正 prompt）
- judge completeness < 3 觸發的 digest 重跑 → `self._judge_llm`（已有評估 context，診斷最準）
- judge server 未啟動時降級：跳過 reflect，直接用原 prompt 重跑 digest（最多 1 次）

---

## 新增檔案

```
agents/daily_brief/
├── supervisor.py        # SupervisorAgent、StepResult
└── reflect_prompts.py   # Reflect LLM prompt 模板
```

---

## 資料結構

```python
@dataclass(frozen=True)
class StepResult:
    name: str
    success: bool
    output: Any
    error: str | None
    attempts: int
    adjusted_prompts: tuple[str, ...]   # 每次 reflect 產出的 adjusted_prompt 紀錄

@dataclass(frozen=True)
class StepConfig:
    max_retries: int
    strategy: Literal["plain", "error_aware"]
    backoff_seconds: tuple[float, ...] = (0.0,)
```

---

## 步驟設定（`STEP_CONFIGS`）

| 步驟 | max_retries | strategy | backoff |
|------|-------------|----------|---------|
| hatena / hn / reddit / security | 3 | plain | 1s / 3s / 9s |
| compress / digest / report / notify | 2 | error_aware | — |
| judge / save | 2 | plain | — |

`error_aware` 策略：失敗後呼叫 reflect LLM 產出 `adjusted_prompt`，用調整後的 prompt 重跑。  
`plain` 策略：直接重跑原函數，無 prompt 調整。

---

## Reflect Prompt 結構

```
你是 pipeline 修復專家。

原始任務：
{original_prompt}

執行結果（壞輸出）：
{bad_output}

錯誤訊息：
{error}

請診斷問題並產出修正後的 prompt，確保下次執行能成功。
輸出 JSON：{"diagnosis": "...", "adjusted_prompt": "..."}
```

---

## Judge → Digest 回饋 Loop

```
judge 完成
  └── completeness < 3？
        ↓ 是
        把 missed_urls 注入 adjusted_prompt 重跑 digest
        └── digest 重跑 → judge 重跑（上限 1 次，避免無限迴圈）
```

注入格式：
```
注意：上次摘要遺漏了以下重要文章，請務必涵蓋：
{missed_urls}
```

---

## Fetch 部分成功容錯

- 4 個 fetcher 並行執行，各自獨立重試（含 network 指數退避）
- 成功 ≥ 2：繼續 compress，對失敗 fetcher 各自發告警
- 成功 < 2：整條 pipeline 停止 + Telegram 告警

---

## Telegram 告警格式

```
⚠️ Daily Brief 步驟失敗（{date}）

步驟：{name}（嘗試 {attempts} 次）
錯誤：{error}
診斷：{diagnosis}

建議：python3 main.py "/daily-brief --force {name}"
```

**去重機制**：`steps_dir/alerts.json` 記錄當天已告警步驟與時間。同一步驟同一天只發一次。`--force <step>` 重跑時清除該步驟的告警紀錄。

```json
{ "digest": "2026-04-20T19:30:00", "notify": "2026-04-20T19:35:00" }
```

---

## `agent.py` 改動範圍

現有 `_run_compress()` / `_run_digest()` 等方法不動。只在各步驟呼叫點加一層 `run_step`：

```python
# 改前
compress_data = self._run_compress(source_data)

# 改後
result = self._supervisor.run_step("compress", lambda: self._run_compress(source_data))
if not result.success:
    logger.warning("Step compress: 全部重試失敗，略過後續步驟")
    # 依 step dependency 決定是否繼續
else:
    compress_data = result.output
```

---

## 步驟依賴關係

| 步驟失敗 | 影響 |
|---------|------|
| fetch（< 2 成功） | 停止整條 pipeline |
| compress | 跳過 digest / judge / report / notify |
| digest | 跳過 judge / report / notify（save 若 report.md 存在仍執行） |
| judge | 只影響 judge → digest 回饋 loop，不阻斷 report / notify |
| report | 跳過 save / notify |
| save | 不影響 notify |
| notify | 記錄失敗，不阻斷其他 |

---

## 測試計畫

- [ ] `StepResult` 正確記錄 attempts 和 adjusted_prompts
- [ ] `error_aware` 步驟失敗時確認 reflect LLM 被呼叫
- [ ] `plain` 步驟失敗時確認 reflect LLM **不**被呼叫
- [ ] 告警去重：同一步驟同一天第二次失敗不重複發 Telegram
- [ ] `--force <step>` 重跑時清除該步驟告警紀錄
- [ ] judge completeness < 3 → digest 自動重跑
- [ ] fetch ≥ 2 成功 → pipeline 繼續，< 2 → pipeline 停止
