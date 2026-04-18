"""Behavioral tests for compress.json artifact."""


def test_compress_has_all_sources(compress):
    assert set(compress.keys()) >= {"hatena", "hn", "reddit", "security"}


def test_compress_each_source_has_themes(compress):
    for source in ["hatena", "hn", "reddit", "security"]:
        assert "themes" in compress[source], f"{source} missing 'themes'"
        assert isinstance(compress[source]["themes"], list)


def test_compress_each_source_has_articles(compress):
    for source in ["hatena", "hn", "reddit", "security"]:
        assert "articles" in compress[source], f"{source} missing 'articles'"
        assert isinstance(compress[source]["articles"], list)


def test_compress_articles_have_required_fields(compress):
    required = {"title", "url", "one_liner", "interest"}
    for source, data in compress.items():
        if source == "compressed_at":
            continue
        for article in data.get("articles", []):
            missing = required - article.keys()
            assert not missing, f"{source} article missing fields: {missing}"


def test_compress_articles_only_top_interest(compress):
    allowed = {"***", "**"}
    for source, data in compress.items():
        if source == "compressed_at":
            continue
        for article in data.get("articles", []):
            assert article.get("interest") in allowed, (
                f"{source} article has low interest: {article.get('interest')}"
            )


def test_compress_articles_urls_are_valid(compress):
    for source, data in compress.items():
        if source == "compressed_at":
            continue
        for article in data.get("articles", []):
            url = article.get("url", "")
            assert url.startswith("http"), f"{source} article has invalid URL: {url!r}"
