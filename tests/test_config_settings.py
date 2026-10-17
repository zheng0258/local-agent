import os
from unittest.mock import patch


def test_get_judge_llm_returns_local_backend_by_default():
    from config.settings import LocalLLMBackend, get_judge_llm

    llm = get_judge_llm()
    assert isinstance(llm, LocalLLMBackend)


def test_get_judge_llm_uses_judge_env_vars():
    from config.settings import LocalLLMBackend, get_judge_llm

    with patch.dict(
        os.environ,
        {"JUDGE_LLM_URL": "http://localhost:1235", "JUDGE_LLM_MODEL": "gemma-4b"},
    ):
        llm = get_judge_llm()

    assert isinstance(llm, LocalLLMBackend)
    assert llm.base_url == "http://localhost:1235"
    assert llm.model == "gemma-4b"


def test_get_judge_llm_falls_back_to_local_url():
    from config.settings import DEFAULT_LOCAL_LLM_URL, LocalLLMBackend, get_judge_llm

    with patch.dict(os.environ, {}, clear=True):
        llm = get_judge_llm()

    assert isinstance(llm, LocalLLMBackend)
    assert llm.base_url == DEFAULT_LOCAL_LLM_URL


# ── 結構化輸出（json_schema 約束解碼）──────────────────────────────

import json
from contextlib import contextmanager

import pytest

_SCHEMA = {
    "type": "object",
    "properties": {"x": {"type": "integer"}},
    "required": ["x"],
    "additionalProperties": False,
}


@contextmanager
def _fake_server(message: dict):
    """攔截 urlopen：記錄送出的 body，回傳指定 message。"""
    sent: list[dict] = []

    class _Resp:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

    def _urlopen(req, timeout=None):
        sent.append(json.loads(req.data.decode()))
        body = {"choices": [{"message": message}], "usage": {"total_tokens": 1}}
        return _Resp(json.dumps(body).encode())

    with patch("urllib.request.urlopen", _urlopen):
        yield sent


def _backend(**kwargs):
    from config.settings import LocalLLMBackend

    return LocalLLMBackend(base_url="http://x", model="m", **kwargs)


@pytest.mark.unit
def test_complete_without_schema_sends_no_response_format():
    with _fake_server({"content": "hi"}) as sent:
        out = _backend().complete("p")
    assert out == "hi"
    assert "response_format" not in sent[0]


@pytest.mark.unit
def test_complete_with_schema_sends_strict_json_schema_response_format():
    with _fake_server({"content": '{"x": 1}'}) as sent:
        _backend().complete("p", system="s", schema=_SCHEMA)
    rf = sent[0]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == _SCHEMA
    assert rf["json_schema"]["name"]


@pytest.mark.unit
def test_complete_with_schema_falls_back_to_reasoning_content_when_content_empty():
    """spike 實測：LM Studio 對 qwen3.6 帶 schema 時 JSON 落在 reasoning_content、content 為空。"""
    msg = {"content": "", "reasoning_content": '{"x": 1}'}
    with _fake_server(msg):
        out = _backend().complete("p", schema=_SCHEMA)
    assert out == '{"x": 1}'


@pytest.mark.unit
def test_complete_with_schema_prefers_content_when_present():
    msg = {"content": '{"x": 2}', "reasoning_content": "思考過程"}
    with _fake_server(msg):
        out = _backend().complete("p", schema=_SCHEMA)
    assert out == '{"x": 2}'


@pytest.mark.unit
def test_complete_without_schema_never_returns_reasoning_content():
    """無 schema 時 reasoning_content 是隱藏思考，不是答案，絕不能當輸出。"""
    msg = {"content": "", "reasoning_content": "我在想……"}
    with _fake_server(msg):
        out = _backend().complete("p")
    assert out == ""


@pytest.mark.unit
def test_structured_output_disabled_ignores_schema():
    """回退開關：structured_output=False 時 schema 不送出（走純 prompt + parse_llm_json）。"""
    with _fake_server({"content": '{"x": 1}'}) as sent:
        _backend(structured_output=False).complete("p", schema=_SCHEMA)
    assert "response_format" not in sent[0]


@pytest.mark.unit
@pytest.mark.parametrize("raw, expected", [(None, True), ("1", True), ("0", False), ("off", False), ("false", False)])
def test_get_llm_reads_structured_output_env(raw, expected):
    from config.settings import get_judge_llm, get_llm

    env = {} if raw is None else {"LLM_STRUCTURED_OUTPUT": raw}
    with patch.dict(os.environ, env, clear=True):
        assert get_llm().structured_output is expected
        assert get_judge_llm().structured_output is expected
