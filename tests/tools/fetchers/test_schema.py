from tools.fetchers.schema import Article, clean_articles


def test_clean_articles_filters_below_min_interest():
    articles = [
        {"title": "A", "url": "https://a.com", "interest": "***", "bookmarks": 200, "category": "AI", "source": "hatena"},
        {"title": "B", "url": "https://b.com", "interest": "**", "bookmarks": 100, "category": "OSS", "source": "hatena"},
        {"title": "C", "url": "https://c.com", "interest": "*", "bookmarks": 50, "category": "Other", "source": "hatena"},
    ]
    result = clean_articles(articles, min_interest="**")
    urls = [article.url for article in result]
    assert "https://a.com" in urls
    assert "https://b.com" in urls
    assert "https://c.com" not in urls


def test_clean_articles_sorts_interest_desc_then_score_desc():
    articles = [
        {"title": "A", "url": "https://a.com", "interest": "**", "bookmarks": 500, "category": "", "source": ""},
        {"title": "B", "url": "https://b.com", "interest": "***", "bookmarks": 100, "category": "", "source": ""},
    ]
    result = clean_articles(articles)
    assert result[0].url == "https://b.com"


def test_clean_articles_maps_bookmarks_field():
    result = clean_articles(
        [{"title": "T", "url": "u", "interest": "***", "bookmarks": 200, "category": "", "source": ""}]
    )
    assert result[0].score == 200


def test_clean_articles_maps_score_field():
    result = clean_articles(
        [{"title": "T", "url": "u", "interest": "***", "score": 300, "category": "", "source": ""}]
    )
    assert result[0].score == 300


def test_clean_articles_maps_upvotes_field():
    result = clean_articles(
        [{"title": "T", "url": "u", "interest": "***", "upvotes": 400, "category": "", "source": ""}]
    )
    assert result[0].score == 400


def test_clean_articles_returns_article_instances():
    result = clean_articles(
        [{"title": "T", "url": "https://t.com", "interest": "***", "bookmarks": 100, "category": "AI", "source": "hatena"}]
    )
    assert isinstance(result[0], Article)
    assert result[0].title == "T"
    assert result[0].interest == "***"


def test_clean_articles_to_dict_roundtrip():
    result = clean_articles(
        [{"title": "T", "url": "https://t.com", "interest": "***", "bookmarks": 100, "category": "AI", "source": "hatena"}]
    )
    data = result[0].to_dict()
    assert data["title"] == "T"
    assert data["url"] == "https://t.com"
    assert data["score"] == 100


def test_clean_articles_empty_input():
    assert clean_articles([]) == []
