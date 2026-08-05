"""ComposeTgStep — 生成兩封 Telegram 訊息文字並持久化（不發送）。

producer 邏輯住 _produce（讀 ctx.llm）：兩次 LLM 生成（overview + digest）。
TG 單封 4096 上限下用「條目數上限」控制長度：送 LLM 前跨來源均衡挑選
（pick_top_balanced），再解包 LLM 可能的 JSON 包裝（extract_tg_text）。
JsonCodec 落盤 {"overview": str, "digest": str}；重跑有 artifact 時 LOAD 不重生。
發送由 send-only 的 NotifyStep 負責。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .. import prompts
from ..schemas import Digest
from ..step import Step, StepOutput

# Telegram 單封 4096 字元上限下的條目數（依實測 overview ~155、digest ~540 字元/則估算）
TG_OVERVIEW_MAX_ITEMS = 24
TG_DIGEST_MAX_ITEMS = 7


def pick_top_balanced(digests: list[dict], n: int) -> list[dict]:
    """從各來源 round-robin 各取一篇，湊滿 n 篇，確保 TG 訊息跨來源均衡。"""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for d in digests:
        buckets[Digest.from_dict(d).source_key].append(d)

    source_order = list(dict.fromkeys(Digest.from_dict(d).source_key for d in digests))
    picked: list[dict] = []
    i = 0
    while len(picked) < n and any(buckets[s] for s in source_order):
        src = source_order[i % len(source_order)]
        if buckets[src]:
            picked.append(buckets[src].pop(0))
        i += 1
    return picked


def extract_tg_text(raw: str) -> str:
    """LLM 有時用 JSON 包裝輸出；嘗試解包取出第一個字串值，否則原樣返回。"""
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                for v in parsed.values():
                    if isinstance(v, str):
                        return v
        except (json.JSONDecodeError, Exception):
            pass
    return raw


class ComposeTgStep(Step):
    name = "compose_tg"

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "compose_tg.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        digests = input
        overview_json = json.dumps(
            pick_top_balanced(digests, TG_OVERVIEW_MAX_ITEMS), ensure_ascii=False
        )
        digest_json = json.dumps(
            pick_top_balanced(digests, TG_DIGEST_MAX_ITEMS), ensure_ascii=False
        )
        overview_prompt = self._with_reflect(
            prompts.build_telegram_overview_prompt(overview_json, ctx.today),
            reflect_context,
        )
        digest_prompt = self._with_reflect(
            prompts.build_telegram_digest_prompt(digest_json, ctx.today),
            reflect_context,
        )
        overview = extract_tg_text(self._complete(ctx, overview_prompt).strip())
        tg_digest = extract_tg_text(self._complete(ctx, digest_prompt).strip())
        composed = {"overview": overview, "digest": tg_digest}
        return StepOutput(persist=composed, value=composed)

    def _default(self, input):
        return {}
