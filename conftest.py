import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="執行標記 @pytest.mark.integration 的整合測試（會發實際網路請求 / 啟動瀏覽器）",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """預設跳過 integration 測試（對齊 pytest.ini 的宣告）；--run-integration 才執行。"""
    if config.getoption("--run-integration"):
        return
    skip_integration = pytest.mark.skip(
        reason="整合測試預設跳過，加 --run-integration 才執行"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
