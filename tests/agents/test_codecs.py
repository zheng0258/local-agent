"""ArtifactCodec adapters — dumb format/location seam for a step's primary artifact."""

import pytest

from agents.daily_brief.codecs import JsonCodec, SentinelCodec, TextCodec


@pytest.mark.unit
def test_json_codec_round_trip(tmp_path):
    path = tmp_path / "x.json"
    codec = JsonCodec()
    assert codec.exists(path) is False
    codec.write(path, {"a": 1, "z": "ä"})
    assert codec.exists(path) is True
    assert codec.read(path) == {"a": 1, "z": "ä"}


@pytest.mark.unit
def test_json_codec_writes_utf8_unescaped(tmp_path):
    path = tmp_path / "x.json"
    JsonCodec().write(path, {"k": "日本"})
    assert "日本" in path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_text_codec_round_trip(tmp_path):
    path = tmp_path / "report.md"
    codec = TextCodec()
    assert codec.exists(path) is False
    codec.write(path, "# hello")
    assert codec.exists(path) is True
    assert codec.read(path) == "# hello"


@pytest.mark.unit
def test_sentinel_codec_touches_and_reads_none(tmp_path):
    path = tmp_path / "done.flag"
    codec = SentinelCodec()
    assert codec.exists(path) is False
    codec.write(path, "ignored payload")
    assert codec.exists(path) is True
    assert codec.read(path) is None
