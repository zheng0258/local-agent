"""
Article dataclass + clean_articles() -- deterministic fetcher output normalization.

Layer 1 of hierarchical summarization: no LLM, pure function.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

_INTEREST_ORDER: dict[str, int] = {"***": 3, "**": 2, "*": 1}


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
        score = int(
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
    result.sort(key=lambda item: (_INTEREST_ORDER.get(item.interest, 0), item.score), reverse=True)
    return result
