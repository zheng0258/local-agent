"""LLM 輸出的 json_schema 契約（LM Studio 約束解碼用，見 ADR 0006）。

與 prompts.py 成對：prompt 說明任務，這裡規定模型「只能」輸出的結構。
strict 模式下每個 object 皆 additionalProperties=false、全欄位 required——
文法層直接擋掉 schema 外欄位（judge 自吐 quality_alert、compress/digest 回吐
title/url），而非事後解析時才發現。URL 是資料不是 LLM 輸出：schema 只開放
id + 摘要欄位，title/url 一律由 Python 依 id 從可信輸入重建。

純資料模組；磁碟 artifact 的 typed view 在 schemas.py（JUDGE_DIMENSIONS 共用）。
"""

from __future__ import annotations

from .schemas import JUDGE_DIMENSIONS


def _closed_object(properties: dict) -> dict:
    """strict object：全欄位 required、禁止額外欄位（屬性順序即生成順序）。"""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _array_of(items: dict) -> dict:
    return {"type": "array", "items": items}


_STRING = {"type": "string"}
_ID = {"type": "integer", "minimum": 0}

# 約束解碼時模型不會先思考（spike 實測 reasoning_tokens == 輸出本身），故
# reasoning 排在 score 之前：讓評分理由先於分數生成，作為 CoT 代償。
_JUDGE_DIMENSION = _closed_object(
    {
        "reasoning": _STRING,
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
    }
)

JUDGE_SCHEMA: dict = _closed_object(
    {
        "scores": _closed_object({dim: _JUDGE_DIMENSION for dim in JUDGE_DIMENSIONS}),
        "missed_urls": _array_of(_STRING),
        "overall": {"type": "number"},
    }
)

COMPRESS_SCHEMA: dict = _closed_object(
    {
        "themes": _array_of(_STRING),
        "articles": _array_of(_closed_object({"id": _ID, "one_liner": _STRING})),
    }
)

DIGEST_SCHEMA: dict = _closed_object(
    {"digests": _array_of(_closed_object({"id": _ID, "summary": _STRING}))}
)
