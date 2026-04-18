"""Behavioral tests for telegram artifact files."""

_FORBIDDEN_TAGS = ["<br>", "<br/>", "<p>", "<p/>", "</p>", "<div>", "</div>", "<span>", "</span>"]
_MAX_LEN = 4096


def test_telegram_overview_length(telegram_overview):
    assert len(telegram_overview) <= _MAX_LEN, (
        f"telegram_overview exceeds {_MAX_LEN} chars: {len(telegram_overview)}"
    )


def test_telegram_overview_no_forbidden_tags(telegram_overview):
    for tag in _FORBIDDEN_TAGS:
        assert tag not in telegram_overview.lower(), f"telegram_overview contains forbidden tag: {tag}"


def test_telegram_overview_not_empty(telegram_overview):
    assert len(telegram_overview.strip()) > 0


def test_telegram_digest_length(telegram_digest_txt):
    assert len(telegram_digest_txt) <= _MAX_LEN, (
        f"telegram_digest exceeds {_MAX_LEN} chars: {len(telegram_digest_txt)}"
    )


def test_telegram_digest_no_forbidden_tags(telegram_digest_txt):
    for tag in _FORBIDDEN_TAGS:
        assert tag not in telegram_digest_txt.lower(), f"telegram_digest contains forbidden tag: {tag}"


def test_telegram_digest_not_empty(telegram_digest_txt):
    assert len(telegram_digest_txt.strip()) > 0
