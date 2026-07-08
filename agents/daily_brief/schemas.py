"""Step artifact 的 typed view — 把散落的巢狀 dict 防呆集中於各型別的 from_dict。

這些是唯讀 view，不取代磁碟序列化：artifact 仍以原 JSON schema 寫入，
下游消費者（harness、daily-brief-analyzer）不受影響。型別只罩在記憶體存取點上，
把「每個巢狀 key、每個可能漏、對帳」這條隱性 interface 收成乾淨的小 interface。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Article:
    """compress / source 單篇文章的 typed view。缺值一律為空字串。

    original_title / original_description 是 fetch 階段未經 LLM 改寫的原始素材
    （source artifact 才有；舊 artifact 缺值時為空字串，讀取端自行 fallback title）。
    """

    title: str
    url: str
    one_liner: str
    interest: str
    comment_summary: str
    original_title: str
    original_description: str

    @classmethod
    def from_dict(cls, raw: dict) -> "Article":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            one_liner=raw.get("one_liner", ""),
            interest=raw.get("interest", ""),
            comment_summary=raw.get("comment_summary", ""),
            original_title=raw.get("original_title", ""),
            original_description=raw.get("original_description", ""),
        )


@dataclass(frozen=True)
class SourceCompress:
    """單一來源 compress 結果的 typed view（Theme + Article 清單）。"""

    themes: tuple[str, ...]
    articles: tuple[Article, ...]

    @classmethod
    def from_dict(cls, raw: dict) -> "SourceCompress":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            themes=tuple(raw.get("themes", []) or []),
            articles=tuple(
                Article.from_dict(a)
                for a in raw.get("articles", []) or []
                if isinstance(a, dict)
            ),
        )


@dataclass(frozen=True)
class Digest:
    """Digest（深度摘要）單篇的 typed view。

    source_key 與 source_label 語義不同，不可混用：
    - source_key：內部來源鍵（`_source`，== FETCH_STEPS 名），跨來源均衡 bucketing 用。
    - source_label：來源顯示名（`source`），Obsidian/呈現用。
    """

    title: str
    url: str
    summary: str
    source_key: str
    source_label: str
    interest: str

    @classmethod
    def from_dict(cls, raw: dict) -> "Digest":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            summary=raw.get("summary", ""),
            source_key=raw.get("_source") or raw.get("source") or "?",
            source_label=raw.get("source", ""),
            interest=raw.get("interest", ""),
        )


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
