"""URL Digest — 所有 LLM prompts。"""

SYSTEM = """\
你是一個文章摘要 agent。
輸出語言：繁體中文（英文、日文標題均需翻譯）。
需要結構化輸出時，回傳合法 JSON（可用 ```json 包裹）。\
"""


def build_summary_prompt(title: str, content: str, url: str, comments: str = "") -> str:
    comments_section = f"\n\n## 社群留言\n\n{comments}" if comments else ""
    return f"""\
## 文章標題

{title}

## 文章內容

{content}{comments_section}

## 任務

1. 將標題翻譯為繁體中文（若已是中文則保留）
2. 生成 3–5 行摘要（核心訊息{" + 社群反應" if comments else ""}）
3. 保留原始 URL：{url}

## 輸出格式

```json
{{
  "title_zh": "繁體中文標題",
  "summary": "3–5 行摘要",
  "url": "{url}"
}}
```\
"""
