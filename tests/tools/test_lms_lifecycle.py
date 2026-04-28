"""tools/lms_lifecycle 測試。"""

import pytest
from unittest.mock import patch, MagicMock

from tools.lms_lifecycle import get_loaded_models, ensure_models_loaded, unload_all


_PS_OUTPUT = (
    "IDENTIFIER                                   MODEL                                        STATUS\n"
    "google/gemma-4-e4b                           google/gemma-4-e4b                           IDLE\n"
    "qwen3.5-27b-claude-4.6-opus-distilled-mlx    qwen3.5-27b-claude-4.6-opus-distilled-mlx    IDLE\n"
)


def _mock_ps(stdout: str = _PS_OUTPUT, returncode: int = 0) -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr="")


@pytest.mark.unit
def test_get_loaded_models_returns_identifiers():
    """lms ps 輸出正確時，回傳所有 IDENTIFIER 的集合。"""
    with patch("tools.lms_lifecycle.subprocess.run", return_value=_mock_ps()) as mock_run:
        result = get_loaded_models()
    mock_run.assert_called_once_with(["lms", "ps"], capture_output=True, text=True, timeout=10)
    assert result == {
        "google/gemma-4-e4b",
        "qwen3.5-27b-claude-4.6-opus-distilled-mlx",
    }


@pytest.mark.unit
def test_get_loaded_models_empty_when_none_loaded():
    """只有標題列時回傳空集合。"""
    stdout = "IDENTIFIER    MODEL    STATUS\n"
    with patch("tools.lms_lifecycle.subprocess.run", return_value=_mock_ps(stdout=stdout)):
        result = get_loaded_models()
    assert result == set()


@pytest.mark.unit
def test_get_loaded_models_returns_empty_on_lms_failure():
    """`lms ps` 回傳 non-zero 時不 raise，回傳空集合。"""
    with patch("tools.lms_lifecycle.subprocess.run", return_value=_mock_ps(returncode=1, stdout="")):
        result = get_loaded_models()
    assert result == set()


@pytest.mark.unit
def test_get_loaded_models_returns_empty_when_lms_not_found():
    """`lms` 不在 PATH 時不 raise，回傳空集合。"""
    with patch("tools.lms_lifecycle.subprocess.run", side_effect=FileNotFoundError):
        result = get_loaded_models()
    assert result == set()


@pytest.mark.unit
def test_ensure_skips_already_loaded_model():
    """已載入的模型不呼叫 lms load。"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd == ["lms", "ps"]:
            return _mock_ps()  # both models loaded
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("tools.lms_lifecycle.subprocess.run", side_effect=fake_run):
        ensure_models_loaded(["google/gemma-4-e4b"])

    load_calls = [c for c in calls if len(c) > 1 and c[1] == "load"]
    assert load_calls == []


@pytest.mark.unit
def test_ensure_loads_missing_model():
    """未載入的模型會呼叫 lms load <model> -y，並在 load 後驗證（兩次 lms ps）。"""
    ps_calls = 0

    def fake_run(cmd, **kwargs):
        nonlocal ps_calls
        if cmd == ["lms", "ps"]:
            ps_calls += 1
            if ps_calls == 1:
                return _mock_ps(stdout="IDENTIFIER    MODEL    STATUS\n")  # empty
            return _mock_ps()  # after load: both present
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("tools.lms_lifecycle.subprocess.run", side_effect=fake_run):
        ensure_models_loaded(["google/gemma-4-e4b"])

    assert ps_calls == 2


@pytest.mark.unit
def test_ensure_warns_but_does_not_raise_on_load_failure():
    """`lms load` 失敗時只 warning，不 raise。"""
    def fake_run(cmd, **kwargs):
        if cmd == ["lms", "ps"]:
            return _mock_ps(stdout="IDENTIFIER    MODEL    STATUS\n")
        return MagicMock(returncode=1, stdout="", stderr="model not found")

    with patch("tools.lms_lifecycle.subprocess.run", side_effect=fake_run):
        ensure_models_loaded(["google/gemma-4-e4b"])  # must not raise


@pytest.mark.unit
def test_unload_all_calls_lms_unload_all():
    """`unload_all` 呼叫 lms unload --all。"""
    with patch("tools.lms_lifecycle.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
        unload_all()
    mock_run.assert_called_once_with(
        ["lms", "unload", "--all"], capture_output=True, text=True, timeout=30
    )


@pytest.mark.unit
def test_unload_all_does_not_raise_on_failure():
    """`lms unload --all` 失敗時靜默忽略，不 raise。"""
    with patch("tools.lms_lifecycle.subprocess.run", return_value=MagicMock(returncode=1, stderr="err")):
        unload_all()  # must not raise


@pytest.mark.unit
def test_unload_all_does_not_raise_when_lms_not_found():
    """`lms` 不在 PATH 時靜默忽略。"""
    with patch("tools.lms_lifecycle.subprocess.run", side_effect=FileNotFoundError):
        unload_all()  # must not raise
