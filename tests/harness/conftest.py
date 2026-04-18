"""
Fixtures for behavioral tests.
Loads artifacts from outputs/daily-brief/{date}/steps/.
Use: pytest tests/harness/ --date=2026-04-13
"""

import json
from datetime import date
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_OUTPUTS = _PROJECT_ROOT / "outputs" / "daily-brief"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--date",
        default=date.today().strftime("%Y-%m-%d"),
        help="Date of artifacts to test (YYYY-MM-DD)",
    )


def _steps_dir(config: pytest.Config) -> Path:
    return _OUTPUTS / config.getoption("--date") / "steps"


def _load_json(config: pytest.Config, filename: str) -> dict | list:
    path = _steps_dir(config) / filename
    if not path.exists():
        pytest.skip(f"{filename} not found for date {config.getoption('--date')}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def compress(pytestconfig: pytest.Config) -> dict:
    return _load_json(pytestconfig, "compress.json")


@pytest.fixture
def digest(pytestconfig: pytest.Config) -> dict:
    return _load_json(pytestconfig, "digest.json")


@pytest.fixture
def judge(pytestconfig: pytest.Config) -> dict:
    return _load_json(pytestconfig, "judge.json")


@pytest.fixture
def telegram_overview(pytestconfig: pytest.Config) -> str:
    path = _steps_dir(pytestconfig) / "telegram_overview.txt"
    if not path.exists():
        pytest.skip("telegram_overview.txt not found")
    return path.read_text(encoding="utf-8")


@pytest.fixture
def telegram_digest_txt(pytestconfig: pytest.Config) -> str:
    path = _steps_dir(pytestconfig) / "telegram_digest.txt"
    if not path.exists():
        pytest.skip("telegram_digest.txt not found")
    return path.read_text(encoding="utf-8")
