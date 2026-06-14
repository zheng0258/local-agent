"""Step artifact 的 typed view — 把散落的巢狀 dict 防呆集中於各型別的 from_dict。

這些是唯讀 view，不取代磁碟序列化：artifact 仍以原 JSON schema 寫入，
下游消費者（harness、daily-brief-analyzer）不受影響。型別只罩在記憶體存取點上，
把「每個巢狀 key、每個可能漏、對帳」這條隱性 interface 收成乾淨的小 interface。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityScore:
    """品質分（Quality Score）— LLM-as-Judge 對最終 Brief 的三軸自評之 typed view。

    relevance / completeness / faithfulness 為缺值或非數字時為 None（不轉 0），
    以保留「completeness 非數字 → 不觸發 retry」的判定語義。
    missed_urls 自頂層或 scores.completeness 對帳而來。
    """

    relevance: int | float | None
    completeness: int | float | None
    faithfulness: int | float | None
    missed_urls: tuple[str, ...]
    overall: float
    quality_alert: bool

    @classmethod
    def from_dict(cls, raw: dict) -> "QualityScore":
        scores = raw.get("scores", {}) if isinstance(raw, dict) else {}
        if not isinstance(scores, dict):
            scores = {}

        def dim_score(name: str) -> int | float | None:
            entry = scores.get(name, {})
            value = entry.get("score") if isinstance(entry, dict) else None
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

        completeness_entry = scores.get("completeness", {})
        nested_missed = (
            completeness_entry.get("missed_urls", [])
            if isinstance(completeness_entry, dict)
            else []
        )
        missed = raw.get("missed_urls") or nested_missed or []

        overall_raw = raw.get("overall", 0.0)
        overall = float(overall_raw) if isinstance(overall_raw, (int, float)) else 0.0

        return cls(
            relevance=dim_score("relevance"),
            completeness=dim_score("completeness"),
            faithfulness=dim_score("faithfulness"),
            missed_urls=tuple(missed),
            overall=overall,
            quality_alert=bool(raw.get("quality_alert", False)),
        )
