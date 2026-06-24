import pytest

from tools.fetchers.schema import Article, _coerce_int, clean_articles


def test_clean_articles_filters_below_min_interest():
    articles = [
        {
            "title": "A",
            "url": "https://a.com",
            "interest": "***",
            "bookmarks": 200,
            "category": "AI",
            "source": "hatena",
        },
        {
            "title": "B",
            "url": "https://b.com",
            "interest": "**",
            "bookmarks": 100,
            "category": "OSS",
            "source": "hatena",
        },
        {
            "title": "C",
            "url": "https://c.com",
            "interest": "*",
            "bookmarks": 50,
            "category": "Other",
            "source": "hatena",
        },
    ]
    result = clean_articles(articles, min_interest="**")
    urls = [article.url for article in result]
    assert "https://a.com" in urls
    assert "https://b.com" in urls
    assert "https://c.com" not in urls


def test_clean_articles_sorts_interest_desc_then_score_desc():
    articles = [
        {
            "title": "A",
            "url": "https://a.com",
            "interest": "**",
            "bookmarks": 500,
            "category": "",
            "source": "",
        },
        {
            "title": "B",
            "url": "https://b.com",
            "interest": "***",
            "bookmarks": 100,
            "category": "",
            "source": "",
        },
    ]
    result = clean_articles(articles)
    assert result[0].url == "https://b.com"


def test_clean_articles_maps_bookmarks_field():
    result = clean_articles(
        [
            {
                "title": "T",
                "url": "u",
                "interest": "***",
                "bookmarks": 200,
                "category": "",
                "source": "",
            }
        ]
    )
    assert result[0].score == 200


def test_clean_articles_maps_score_field():
    result = clean_articles(
        [
            {
                "title": "T",
                "url": "u",
                "interest": "***",
                "score": 300,
                "category": "",
                "source": "",
            }
        ]
    )
    assert result[0].score == 300


def test_clean_articles_maps_upvotes_field():
    result = clean_articles(
        [
            {
                "title": "T",
                "url": "u",
                "interest": "***",
                "upvotes": 400,
                "category": "",
                "source": "",
            }
        ]
    )
    assert result[0].score == 400


def test_clean_articles_returns_article_instances():
    result = clean_articles(
        [
            {
                "title": "T",
                "url": "https://t.com",
                "interest": "***",
                "bookmarks": 100,
                "category": "AI",
                "source": "hatena",
            }
        ]
    )
    assert isinstance(result[0], Article)
    assert result[0].title == "T"
    assert result[0].interest == "***"


def test_clean_articles_to_dict_roundtrip():
    result = clean_articles(
        [
            {
                "title": "T",
                "url": "https://t.com",
                "interest": "***",
                "bookmarks": 100,
                "category": "AI",
                "source": "hatena",
            }
        ]
    )
    data = result[0].to_dict()
    assert data["title"] == "T"
    assert data["url"] == "https://t.com"
    assert data["score"] == 100


def test_clean_articles_empty_input():
    assert clean_articles([]) == []


# ---------------------------------------------------------------------------
# 回歸：LLM 把星號誤填進 score（生產環境 reddit attempt 1 每天炸的根因）
# invalid literal for int() with base 10: '***'
# ---------------------------------------------------------------------------


def test_clean_articles_survives_stars_in_score_field():
    """score 欄位被 LLM 填成 '***' 時不 crash，分數視為 0。"""
    result = clean_articles(
        [
            {
                "title": "T",
                "url": "https://t.com",
                "interest": "***",
                "score": "***",
                "category": "",
                "source": "",
            }
        ]
    )
    assert len(result) == 1
    assert result[0].score == 0


def test_clean_articles_survives_non_numeric_string_score():
    """score 為任意非數字字串時視為 0，不 crash。"""
    result = clean_articles(
        [
            {
                "title": "T",
                "url": "u",
                "interest": "***",
                "score": "N/A",
                "category": "",
                "source": "",
            }
        ]
    )
    assert result[0].score == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (123, 123),
        ("123", 123),
        ("  456  ", 456),
        ("-7", -7),
        (12.9, 12),
        ("***", 0),
        ("N/A", 0),
        ("", 0),
        (None, 0),
        (True, 0),  # bool 明確排除，不當成 1
        (False, 0),
        ("12.5", 0),  # 含小數點的字串非純數字
    ],
)
def test_coerce_int(value, expected):
    assert _coerce_int(value) == expected
