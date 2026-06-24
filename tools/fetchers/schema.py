"""
Article dataclass + clean_articles() -- deterministic fetcher output normalization.

Layer 1 of hierarchical summarization: no LLM, pure function.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

_INTEREST_ORDER: dict[str, int] = {"***": 3, "**": 2, "*": 1}


def _coerce_int(value: object) -> int:
    """把來自 LLM 的分數欄位安全轉成 int。

    LLM 偶爾把 interest 星號（如 "***"）誤填進 score/bookmarks 欄位，
    直接 int("***") 會 ValueError。此處在系統邊界做防禦：任何非數字
    一律視為 0，deterministic tool 不因髒資料 crash。
    """
    if isinstance(value, bool):  # bool 是 int 子類，明確排除
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return 0


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    interest: str
    score: int
    category: str
    source: str

    def to_dict(self) -> dict:
        return asdict(self)


def clean_articles(articles: list[dict], min_interest: str = "**") -> list[Article]:
    """
    Deterministic cleaning:
    1. Drop articles below min_interest threshold.
    2. Normalize to Article fields (bookmarks / score / upvotes -> score).
    3. Sort by interest desc, then score desc.
    """
    min_level = _INTEREST_ORDER.get(min_interest, 2)
    result: list[Article] = []
    for article in articles:
        interest = article.get("interest", "*")
        if _INTEREST_ORDER.get(interest, 0) < min_level:
            continue
        score = _coerce_int(
            article.get("bookmarks")
            or article.get("score")
            or article.get("upvotes")
            or 0
        )
        result.append(
            Article(
                title=article.get("title", ""),
                url=article.get("url", ""),
                interest=interest,
                score=score,
                category=article.get("category", ""),
                source=article.get("source", ""),
            )
        )
    result.sort(
        key=lambda item: (_INTEREST_ORDER.get(item.interest, 0), item.score),
        reverse=True,
    )
    return result
