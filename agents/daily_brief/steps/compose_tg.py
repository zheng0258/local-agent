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

from config import get_logger

from .. import alerts, links, prompts
from ..schemas import Digest
from ..step import Step, StepOutput

logger = get_logger(__name__)

# Telegram 單封 4096 字元上限下的條目數。
# overview 為純連結列表（標題連結，無說明），實測 ~120 字元/則；24 則約 2880 字，
# 安全落在 4096 內。digest 帶 2–3 句說明 ~540 字元/則。
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
        overview = self._compose(
            ctx,
            pick_top_balanced(digests, TG_OVERVIEW_MAX_ITEMS),
            prompts.build_telegram_overview_prompt,
            reflect_context,
        )
        tg_digest = self._compose(
            ctx,
            pick_top_balanced(digests, TG_DIGEST_MAX_ITEMS),
            prompts.build_telegram_digest_prompt,
            reflect_context,
        )
        composed = {"overview": overview, "digest": tg_digest}
        return StepOutput(persist=composed, value=composed)

    def _compose(self, ctx, picked: list[dict], build_prompt, reflect_context: str) -> str:
        """單封訊息：LLM 只寫 href="@@id@@" token，程式依 id 替換真實 URL。

        LLM 永不經手網址；替換後仍殘留的非 http(s) href（未知 id / LLM 亂填）由
        strip_invalid_anchors 拆掉外殼，確保送達訊息絕無死連結，並記 alert 供觀測。
        """
        url_by_id = {i: d.get("url", "") for i, d in enumerate(picked)}
        payload = [{"id": i, **d} for i, d in enumerate(picked)]
        prompt = self._with_reflect(
            build_prompt(json.dumps(payload, ensure_ascii=False), ctx.today),
            reflect_context,
        )
        raw = extract_tg_text(self._complete(ctx, prompt).strip())
        substituted = links.substitute_href_tokens(raw, url_by_id)
        cleaned, removed = links.strip_invalid_anchors(substituted)
        if removed:
            logger.warning("compose_tg：%d 個連結無法解析，已移除外殼", removed)
            alerts.record_failure(
                ctx.steps_dir,
                "compose_tg",
                f"{removed} 個 href token 未能替換為有效 URL，已降級為純標題",
            )
        return cleaned

    def _default(self, input):
        return {}
