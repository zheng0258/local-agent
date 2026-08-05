"""reconcile — pipeline 各階段 URL 對齊 join/filter 的純函數測試。"""

import pytest

from agents.daily_brief.reconcile import (
    attach_original_fields,
    filter_source_data_by_urls,
    filter_top_articles,
    original_pairs_for_digests,
)


@pytest.mark.unit
def test_filter_top_articles_keeps_only_triple_star():
    source = {
        "hn": {
            "themes": ["AI"],
            "articles": [
                {"url": "a", "interest": "***"},
                {"url": "b", "interest": "**"},
            ],
        },
        "rss": {"articles": [{"url": "c", "interest": "*"}]},  # 無 *** → 整源剔除
    }
    result = filter_top_articles(source)
    assert set(result) == {"hn"}
    assert result["hn"]["articles"] == [{"url": "a", "interest": "***"}]
    assert result["hn"]["themes"] == ["AI"]  # 其他欄位保留


@pytest.mark.unit
def test_filter_source_data_by_urls():
    source = {"hn": {"articles": [{"url": "a"}, {"url": "b"}]}}
    result = filter_source_data_by_urls(source, {"a"})
    assert result["hn"]["articles"] == [{"url": "a"}]


@pytest.mark.unit
def test_attach_original_fields_by_url_and_hn_url():
    scored = [{"title": "繁中", "url": "https://x/post"}]
    raw = [{"title": "Raw", "url": "https://x/post", "description": "desc"}]
    out = attach_original_fields(scored, raw)
    assert out[0]["original_title"] == "Raw"
    assert out[0]["original_description"] == "desc"
    assert out[0]["title"] == "繁中"  # 既有欄位不動


@pytest.mark.unit
def test_attach_original_fields_does_not_mutate_input():
    scored = [{"title": "t", "url": "u"}]
    attach_original_fields(scored, [{"title": "R", "url": "u"}])
    assert scored == [{"title": "t", "url": "u"}]


@pytest.mark.unit
def test_original_pairs_falls_back_to_source_title():
    source_data = {"hatena": {"articles": [{"title": "Legacy", "url": "u2"}]}}
    pairs = original_pairs_for_digests([{"url": "u2"}], source_data)
    assert pairs[0]["original_title"] == "Legacy"
