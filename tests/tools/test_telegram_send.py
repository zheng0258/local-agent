"""telegram.send() 的網路回應行為測試。

迴歸 #15：Telegram 回 HTTP 200 但 body {"ok": false} 時，send() 必須視為失敗，
否則 NotifyStep 會 touch sentinel 造成訊息靜默遺失。mock urlopen，不碰網路。
"""

import pytest

from tools.notifiers import telegram


class _FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body


@pytest.fixture
def _creds(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")


@pytest.mark.unit
def test_send_returns_true_when_ok_true(_creds, monkeypatch):
    monkeypatch.setattr(
        telegram.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResp(b'{"ok": true, "result": {"message_id": 1}}'),
    )
    assert telegram.send("hi") is True


@pytest.mark.unit
def test_send_returns_false_when_ok_false(_creds, monkeypatch):
    monkeypatch.setattr(
        telegram.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResp(b'{"ok": false, "description": "Bad Request"}'),
    )
    assert telegram.send("hi") is False
