import pytest

from config.utils import parse_llm_json


def test_plain_json():
    assert parse_llm_json('{"key": "val"}') == {"key": "val"}


def test_json_in_fence():
    raw = '```json\n{"key": "val"}\n```'
    assert parse_llm_json(raw) == {"key": "val"}


def test_json_fence_without_lang():
    raw = '```\n{"key": "val"}\n```'
    assert parse_llm_json(raw) == {"key": "val"}


def test_fullwidth_colon_repaired():
    broken = '{"title：標題": "val"}'
    result = parse_llm_json(broken)
    assert "raw" not in result


def test_non_string_input():
    with pytest.raises(ValueError, match="parse_llm_json"):
        parse_llm_json(None)


def test_complete_failure_raises():
    with pytest.raises(ValueError, match="parse_llm_json"):
        parse_llm_json("not json at all ><")
