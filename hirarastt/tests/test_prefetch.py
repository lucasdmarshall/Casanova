"""The prefetch command downloads the model up front and fails loudly."""

from __future__ import annotations

import hirarastt.prefetch as prefetch
from hirarastt.engine import EngineError


class _Engine:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.loaded = False

    def ensure_loaded(self) -> None:
        if self.fail:
            raise EngineError("could not reach the model weights")
        self.loaded = True

    def info(self) -> dict:
        return {"backend": "fake", "model": "base", "loaded": self.loaded}


def test_prefetch_returns_zero_on_success(monkeypatch):
    engine = _Engine()
    monkeypatch.setattr(prefetch, "build_engine", lambda config: engine)
    assert prefetch.main() == 0
    assert engine.loaded is True


def test_prefetch_returns_nonzero_when_the_model_cannot_load(monkeypatch):
    monkeypatch.setattr(prefetch, "build_engine", lambda config: _Engine(fail=True))
    # A deploy that cannot fetch the weights must fail loudly, not exit 0.
    assert prefetch.main() == 1


def test_prefetch_survives_an_unexpected_error(monkeypatch):
    class Boom:
        def ensure_loaded(self):
            raise RuntimeError("disk full")

        def info(self):
            return {}

    monkeypatch.setattr(prefetch, "build_engine", lambda config: Boom())
    assert prefetch.main() == 1
