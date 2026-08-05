"""Tests for Hiraracode configuration and the language allowlist."""

from __future__ import annotations

import pytest

from hiraracode.config import DEFAULT_LANGUAGES, ExecConfig


def test_defaults_are_strict():
    cfg = ExecConfig()
    assert cfg.allow_network is False
    assert cfg.user == "65534:65534"
    assert cfg.memory == "256m"
    assert cfg.pids_limit == 128
    assert set(cfg.languages) == set(DEFAULT_LANGUAGES)


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("CCODE_ALLOW_NETWORK", "true")
    monkeypatch.setenv("CCODE_MEMORY", "512m")
    monkeypatch.setenv("CCODE_CPUS", "2")
    monkeypatch.setenv("CCODE_TIMEOUT", "10")
    cfg = ExecConfig.from_env()
    assert cfg.allow_network is True
    assert cfg.memory == "512m"
    assert cfg.cpus == 2.0
    assert cfg.timeout == 10.0


def test_extra_language_via_env(monkeypatch):
    monkeypatch.setenv(
        "CCODE_IMAGES",
        '{"ruby": {"image": "ruby:3.3-slim", "cmd": ["ruby", "/workspace/main.rb"], "filename": "main.rb"}}',
    )
    cfg = ExecConfig.from_env()
    assert "ruby" in cfg.languages
    assert cfg.languages["ruby"].image == "ruby:3.3-slim"
    assert "python" in cfg.languages  # defaults preserved


def test_bad_images_json_raises(monkeypatch):
    monkeypatch.setenv("CCODE_IMAGES", "{not json}")
    with pytest.raises(ValueError):
        ExecConfig.from_env()


def test_images_entry_requires_image(monkeypatch):
    monkeypatch.setenv("CCODE_IMAGES", '{"x": {"cmd": ["x"]}}')
    with pytest.raises(ValueError):
        ExecConfig.from_env()


def test_clamp_timeout():
    cfg = ExecConfig(timeout=30.0, max_timeout=60.0)
    assert cfg.clamp_timeout(None) == 30.0
    assert cfg.clamp_timeout(10) == 10.0
    assert cfg.clamp_timeout(999) == 60.0
    assert cfg.clamp_timeout(0) == 0.1  # floored to a positive value
