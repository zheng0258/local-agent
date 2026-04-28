"""tools/lms_lifecycle 測試。"""

import pytest
from unittest.mock import patch, MagicMock

from tools.lms_lifecycle import get_loaded_models


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
    mock_run.assert_called_once_with(["lms", "ps"], capture_output=True, text=True)
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
