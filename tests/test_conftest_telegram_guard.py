"""conftest 的 Telegram 防護：測試用假資料絕不能發出真的 TG 訊息（10-20 00:19 實例）。"""

import pytest

from tools.notifiers import telegram


@pytest.mark.unit
def test_send_is_skipped_because_credentials_are_blanked():
    assert telegram.send("測試不該發出") is False


@pytest.mark.unit
def test_real_telegram_request_fails_the_test(monkeypatch):
    """就算測試自己設了憑證卻忘了 mock urlopen，也要當場失敗而不是送出。"""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "leaked-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    with pytest.raises(RuntimeError, match="Telegram"):
        telegram.send("測試不該發出")
