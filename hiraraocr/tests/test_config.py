"""Config env parsing."""

from __future__ import annotations

from hiraraocr.config import ENGINES, OcrConfig


def test_defaults():
    c = OcrConfig()
    assert c.engine == "paddleocr"
    assert c.languages == ["en"]
    assert c.preprocess is True
    assert "tesseract" in ENGINES


def test_from_env(monkeypatch):
    monkeypatch.setenv("COCR_ENGINE", "tesseract")
    monkeypatch.setenv("COCR_LANGUAGES", "en, fr ,de")
    monkeypatch.setenv("COCR_ALLOW_URL_FETCH", "true")
    monkeypatch.setenv("COCR_PREPROCESS", "false")
    monkeypatch.setenv("COCR_MAX_PAGES", "5")
    c = OcrConfig.from_env()
    assert c.engine == "tesseract"
    assert c.languages == ["en", "fr", "de"]
    assert c.allow_url_fetch is True
    assert c.preprocess is False
    assert c.max_pages == 5


def test_bad_engine_falls_back(monkeypatch):
    monkeypatch.setenv("COCR_ENGINE", "nope")
    assert OcrConfig.from_env().engine == "paddleocr"


def test_bad_device_falls_back(monkeypatch):
    monkeypatch.setenv("COCR_DEVICE", "tpu")
    assert OcrConfig.from_env().device == "cpu"
