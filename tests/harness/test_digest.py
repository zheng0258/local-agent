"""Behavioral tests for digest.json artifact."""


def test_digest_has_digests_key(digest):
    assert "digests" in digest
    assert isinstance(digest["digests"], list)


def test_digest_not_empty(digest):
    assert len(digest["digests"]) > 0, "digest is empty"


def test_digest_articles_have_required_fields(digest):
    required = {"title", "url", "source", "interest", "summary"}
    for item in digest["digests"]:
        missing = required - item.keys()
        assert not missing, f"digest item missing fields: {missing}"


def test_digest_only_top_interest(digest):
    for item in digest["digests"]:
        assert item.get("interest") == "***", (
            f"digest contains non-*** article: {item.get('url')}"
        )


def test_digest_urls_exist_in_compress(compress, digest):
    """All digest URLs must originate from compress -- no hallucinated URLs."""
    source_urls: set[str] = set()
    for source, data in compress.items():
        if source == "compressed_at":
            continue
        for article in data.get("articles", []):
            source_urls.add(article.get("url", ""))

    for item in digest["digests"]:
        url = item.get("url", "")
        assert url in source_urls, f"Hallucinated URL in digest: {url!r}"


def test_digest_no_duplicate_urls(digest):
    urls = [item.get("url") for item in digest["digests"]]
    assert len(urls) == len(set(urls)), "digest contains duplicate URLs"
