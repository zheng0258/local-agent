import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

_TELEGRAM_HOST = "api.telegram.org"
_TELEGRAM_ENV = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


@pytest.fixture(autouse=True)
def _no_real_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    """測試假資料絕不能發出真的 TG（10-20 00:19：judge 測試跑到 send_summary 實發告警）。

    1. 憑證清成空字串 —— load_project_env 用 setdefault，不會把 .env 的值補回來，
       telegram.send() 因此在組 URL 前就略過。
    2. 往 api.telegram.org 的 urlopen 一律拋 RuntimeError —— 測試自設憑證卻忘了
       mock 時當場失敗；不用 URLError，因為 send() 會吞掉它。
    """
    for name in _TELEGRAM_ENV:
        monkeypatch.setenv(name, "")

    real_urlopen = urllib.request.urlopen

    def guarded_urlopen(url, *args, **kwargs):
        target = getattr(url, "full_url", url)
        if _TELEGRAM_HOST in str(target):
            raise RuntimeError("測試中禁止發送真的 Telegram 訊息；請 mock notify_fn／tg_send")
        return real_urlopen(url, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", guarded_urlopen)


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
