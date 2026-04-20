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
