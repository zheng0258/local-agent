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
