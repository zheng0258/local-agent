"""ReportStep — 最終趨勢報告（純 markdown，寫 report.md）。

producer 邏輯住 _produce（讀 ctx.llm、ctx.today）；input 是 (compress_data, digests)。
LLM 直接輸出純 markdown（不包 JSON）；_produce 剝除 LLM 可能加上的 markdown fence。
artifact 在 day_dir（非 steps_dir），用 TextCodec。value 為 None（終端步）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from config import get_logger

from .. import alerts, links, prompts
from ..codecs import TextCodec
from ..schemas import Digest
from ..step import Step, StepOutput

logger = get_logger(__name__)


def _index_urls(compress_data: dict, digests: list[dict]) -> dict[str, int]:
    """替 compress（全來源）+ digests 中每個唯一 URL 指派全域 id（穩定枚舉）。"""
    url_to_id: dict[str, int] = {}
    for name, section in compress_data.items():
        if not isinstance(section, dict):
            continue
        for art in section.get("articles", []):
            url = art.get("url", "") if isinstance(art, dict) else ""
            if links.is_valid_url(url) and url not in url_to_id:
                url_to_id[url] = len(url_to_id)
    for d in digests:
        url = Digest.from_dict(d).url
        if links.is_valid_url(url) and url not in url_to_id:
            url_to_id[url] = len(url_to_id)
    return url_to_id


def _inject_ids_compress(compress_data: dict, url_to_id: dict[str, int]) -> dict:
    """回傳附上 id 的 compress 副本（不 mutate 輸入）。"""
    out: dict = {}
    for name, section in compress_data.items():
        if not isinstance(section, dict) or "articles" not in section:
            out[name] = section
            continue
        out[name] = {
            **section,
            "articles": [
                {**a, "id": url_to_id[a["url"]]}
                if isinstance(a, dict) and a.get("url") in url_to_id
                else a
                for a in section.get("articles", [])
            ],
        }
    return out


class ReportStep(Step):
    name = "report"
    codec = TextCodec()

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "report.md"

    def _guard(self, ctx, input) -> bool:
        _compress, digests = input
        return bool(digests)

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        compress_data, digests = input
        seen: set[str] = set()
        deduped: list[dict] = []
        for d in digests:
            url = Digest.from_dict(d).url
            if url and url not in seen:
                seen.add(url)
                deduped.append(d)

        # URL 是資料不是 LLM 輸出：全域 id → LLM 寫 [標題](@@id@@) → 程式替換
        url_to_id = _index_urls(compress_data, deduped)
        url_by_id = {i: u for u, i in url_to_id.items()}
        compress_json = json.dumps(
            _inject_ids_compress(compress_data, url_to_id), ensure_ascii=False
        )
        digests_with_id = [
            {**d, "id": url_to_id[Digest.from_dict(d).url]}
            if Digest.from_dict(d).url in url_to_id
            else d
            for d in deduped
        ]
        prompt = self._with_reflect(
            prompts.build_report_prompt_from_compress(
                compress_json=compress_json,
                digests_json=json.dumps(digests_with_id, ensure_ascii=False),
                today=ctx.today,
            ),
            reflect_context,
        )
        content = self._complete(ctx, prompt).strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content).rstrip("`").strip()

        content = links.substitute_md_link_tokens(content, url_by_id)
        content, removed = links.strip_invalid_md_links(content)
        if removed:
            logger.warning("report：%d 個 markdown 連結無法解析，已降級為純文字", removed)
            alerts.record_failure(
                ctx.steps_dir,
                "report",
                f"{removed} 個 [標題](@@id@@) token 未能替換為有效 URL，已降級為純文字",
            )
        return StepOutput(persist=content or "（報告生成失敗）", value=None)

    def _default(self, input):
        return None
