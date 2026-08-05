"""Config env parsing."""

from __future__ import annotations

from casareader.config import KINDS, ReaderConfig


def test_defaults():
    c = ReaderConfig()
    assert c.allow_local_path is True
    assert c.allow_url_fetch is False
    assert set(KINDS) == {"docx", "pptx", "xlsx"}


def test_from_env(monkeypatch):
    monkeypatch.setenv("CRDR_MAX_BYTES", "1000")
    monkeypatch.setenv("CRDR_ALLOW_URL_FETCH", "true")
    monkeypatch.setenv("CRDR_MAX_ROWS", "50")
    c = ReaderConfig.from_env()
    assert c.max_bytes == 1000
    assert c.allow_url_fetch is True
    assert c.max_rows == 50
