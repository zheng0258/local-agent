"""llm_schemas — judge/compress/digest 的 json_schema 契約。

約束解碼的價值在於「模型只能輸出這些欄位」，故測試鎖住：每個 object 皆
additionalProperties=false + 全欄位 required（strict 模式要求）、只開放 id + 摘要欄位
（URL/title 不經 LLM）、judge 維度與 schemas.py typed view 對齊。
"""

import pytest

from agents.daily_brief import llm_schemas
from agents.daily_brief.schemas import JUDGE_DIMENSIONS, QualityScore

jsonschema = pytest.importorskip("jsonschema")

_ALL = {
    "judge": llm_schemas.JUDGE_SCHEMA,
    "compress": llm_schemas.COMPRESS_SCHEMA,
    "digest": llm_schemas.DIGEST_SCHEMA,
}


def _objects(node):
    """走訪 schema 內所有 type=object 節點。"""
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for v in node.values():
            yield from _objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from _objects(v)


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(_ALL))
def test_every_object_is_closed_and_fully_required(name):
    for obj in _objects(_ALL[name]):
        assert obj.get("additionalProperties") is False, name
        assert set(obj["required"]) == set(obj["properties"]), name


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(_ALL))
def test_schema_is_valid_draft(name):
    jsonschema.Draft202012Validator.check_schema(_ALL[name])


@pytest.mark.unit
def test_judge_schema_top_level_only_scores_missed_urls_overall():
    assert set(llm_schemas.JUDGE_SCHEMA["properties"]) == {
        "scores",
        "missed_urls",
        "overall",
    }


@pytest.mark.unit
def test_judge_schema_rejects_leaked_quality_alert():
    leaked = {
        "scores": {
            d: {"reasoning": "r", "score": 4} for d in JUDGE_DIMENSIONS
        },
        "missed_urls": [],
        "overall": 4.0,
        "quality_alert": True,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(leaked, llm_schemas.JUDGE_SCHEMA)


@pytest.mark.unit
def test_judge_dimensions_align_with_quality_score_view():
    scores = llm_schemas.JUDGE_SCHEMA["properties"]["scores"]["properties"]
    assert tuple(scores) == JUDGE_DIMENSIONS
    assert set(JUDGE_DIMENSIONS) <= set(QualityScore.__dataclass_fields__)


@pytest.mark.unit
def test_judge_reasoning_precedes_score():
    """約束解碼使模型不思考；reasoning 排在 score 前，讓理由先於分數生成（CoT 代償）。"""
    dim = llm_schemas.JUDGE_SCHEMA["properties"]["scores"]["properties"]["relevance"]
    assert list(dim["properties"]) == ["reasoning", "score"]


@pytest.mark.unit
def test_judge_score_bounded_integer():
    dim = llm_schemas.JUDGE_SCHEMA["properties"]["scores"]["properties"]["faithfulness"]
    score = dim["properties"]["score"]
    assert score["type"] == "integer"
    assert (score["minimum"], score["maximum"]) == (1, 5)


@pytest.mark.unit
def test_compress_article_only_id_and_one_liner():
    item = llm_schemas.COMPRESS_SCHEMA["properties"]["articles"]["items"]
    assert set(item["properties"]) == {"id", "one_liner"}
    assert set(llm_schemas.COMPRESS_SCHEMA["properties"]) == {"themes", "articles"}


@pytest.mark.unit
def test_digest_item_only_id_and_summary():
    item = llm_schemas.DIGEST_SCHEMA["properties"]["digests"]["items"]
    assert set(item["properties"]) == {"id", "summary"}
    assert set(llm_schemas.DIGEST_SCHEMA["properties"]) == {"digests"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "name, sample",
    [
        ("compress", {"themes": ["AI"], "articles": [{"id": 0, "one_liner": "x"}]}),
        ("digest", {"digests": [{"id": 0, "summary": "x"}]}),
        (
            "judge",
            {
                "scores": {d: {"reasoning": "r", "score": 3} for d in JUDGE_DIMENSIONS},
                "missed_urls": ["https://a"],
                "overall": 3.0,
            },
        ),
    ],
)
def test_canonical_response_validates(name, sample):
    jsonschema.validate(sample, _ALL[name])


@pytest.mark.unit
@pytest.mark.parametrize(
    "name, sample",
    [
        ("compress", {"themes": [], "articles": [{"id": 0, "one_liner": "x", "url": "https://evil"}]}),
        ("digest", {"digests": [{"id": 0, "summary": "x", "title": "t"}]}),
    ],
)
def test_url_and_title_cannot_pass_through_llm(name, sample):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(sample, _ALL[name])
