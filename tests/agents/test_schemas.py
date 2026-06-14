"""QualityScore — 品質分（Quality Score）的 typed 唯讀 view。

把 judge_result 散落的三層防呆與雙 missed_urls 對帳集中進 from_dict。
"""

import pytest

from agents.daily_brief.schemas import Article, Digest, QualityScore, SourceCompress


@pytest.mark.unit
def test_from_dict_well_formed() -> None:
    raw = {
        "scores": {
            "relevance": {"score": 4, "reasoning": "x"},
            "completeness": {"score": 2, "reasoning": "y", "missed_urls": ["u1"]},
            "faithfulness": {"score": 5, "reasoning": "z"},
        },
        "missed_urls": ["u1"],
        "overall": 3.7,
        "quality_alert": True,
    }
    q = QualityScore.from_dict(raw)
    assert q.relevance == 4
    assert q.completeness == 2
    assert q.faithfulness == 5
    assert q.missed_urls == ("u1",)
    assert q.overall == 3.7
    assert q.quality_alert is True


@pytest.mark.unit
def test_missed_urls_reconciled_from_top_level_when_nested_absent() -> None:
    raw = {
        "scores": {"completeness": {"score": 2}},
        "missed_urls": ["top1", "top2"],
    }
    assert QualityScore.from_dict(raw).missed_urls == ("top1", "top2")


@pytest.mark.unit
def test_missed_urls_falls_back_to_nested_when_top_level_absent() -> None:
    raw = {"scores": {"completeness": {"score": 2, "missed_urls": ["nested1"]}}}
    assert QualityScore.from_dict(raw).missed_urls == ("nested1",)


@pytest.mark.unit
def test_missing_scores_yield_none_not_zero() -> None:
    # 缺 scores → dim 為 None（而非 0），避免誤觸發 completeness<3 的 retry
    q = QualityScore.from_dict({})
    assert q.relevance is None
    assert q.completeness is None
    assert q.faithfulness is None
    assert q.missed_urls == ()
    assert q.overall == 0.0
    assert q.quality_alert is False


@pytest.mark.unit
def test_non_numeric_completeness_is_none() -> None:
    raw = {"scores": {"completeness": {"score": "n/a"}}}
    assert QualityScore.from_dict(raw).completeness is None


@pytest.mark.unit
def test_is_frozen() -> None:
    q = QualityScore.from_dict({})
    with pytest.raises(Exception):
        q.completeness = 1  # type: ignore[misc]


@pytest.mark.unit
def test_digest_from_dict_maps_fields() -> None:
    raw = {
        "title": "標題",
        "url": "https://x",
        "summary": "摘要",
        "interest": "***",
        "source": "Hatena",
        "_source": "hatena",
    }
    d = Digest.from_dict(raw)
    assert d.title == "標題"
    assert d.url == "https://x"
    assert d.summary == "摘要"
    assert d.interest == "***"
    # _source = 內部鍵（bucketing）；source = 顯示名（呈現）— 兩者語義不同
    assert d.source_key == "hatena"
    assert d.source_label == "Hatena"


@pytest.mark.unit
def test_digest_source_key_falls_back_to_label_then_question_mark() -> None:
    # 只有顯示名時，內部鍵退回顯示名
    assert Digest.from_dict({"source": "HN"}).source_key == "HN"
    # 兩者皆無時退回 "?"
    assert Digest.from_dict({}).source_key == "?"
    assert Digest.from_dict({}).source_label == ""


@pytest.mark.unit
def test_digest_is_frozen() -> None:
    d = Digest.from_dict({})
    with pytest.raises(Exception):
        d.url = "y"  # type: ignore[misc]


@pytest.mark.unit
def test_article_from_dict_maps_fields_and_defaults() -> None:
    a = Article.from_dict({"title": "t", "url": "u", "one_liner": "o", "interest": "***"})
    assert (a.title, a.url, a.one_liner, a.interest) == ("t", "u", "o", "***")
    assert a.comment_summary == ""  # 缺 comment_summary → 空字串


@pytest.mark.unit
def test_source_compress_wraps_themes_and_articles() -> None:
    raw = {
        "themes": ["AI", "資安"],
        "articles": [
            {"title": "a1", "url": "u1"},
            "garbage",  # 非 dict 應被略過
            {"title": "a2", "url": "u2"},
        ],
    }
    sc = SourceCompress.from_dict(raw)
    assert sc.themes == ("AI", "資安")
    assert len(sc.articles) == 2
    assert all(isinstance(a, Article) for a in sc.articles)
    assert sc.articles[0].title == "a1"


@pytest.mark.unit
def test_source_compress_empty_when_missing() -> None:
    sc = SourceCompress.from_dict({})
    assert sc.themes == ()
    assert sc.articles == ()
