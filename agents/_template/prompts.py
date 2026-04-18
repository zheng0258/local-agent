"""
[AgentName] Prompts — 所有 LLM prompt 集中定義於此。

慣例：
- 每個 prompt 為模組層級常數（全大寫）或函數（需動態插值時）
- prompt 函數命名：build_<step>_prompt(...)
- 禁止在 agent.py 內寫 prompt 字串
"""

SYSTEM = """\
你是一個嚴格按照指示執行的 agent。
輸出語言：繁體中文。
需要結構化輸出時，回傳合法 JSON（可用 ```json 包裹）。\
"""

# 範例：靜態 prompt
EXAMPLE_PROMPT = """\
## 任務

說明此步驟要做什麼。

## 輸出格式

```json
{"key": "value"}
```\
"""


# 範例：動態 prompt（需插值）
def build_example_prompt(data: str) -> str:
    return f"""\
## 輸入資料

{data}

## 任務

分析上方資料並回傳摘要。
"""
