"""OCR engines behind one swappable interface.

The default is **PaddleOCR** (Apache-2.0, 80+ languages, returns boxes and
confidence); **Tesseract** is the lightweight fallback. Both are imported lazily
so importing casaocr — or running the tests against a fake engine — never pulls
the heavy model stack. New backends (TrOCR, a VLM) slot in behind ``OcrEngine``
in v2 without touching the pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Protocol

log = logging.getLogger(__name__)


class EngineError(RuntimeError):
    """Raised when an engine cannot load or recognize."""


@dataclass(frozen=True)
class OcrBlock:
    """One recognized span of text with its box and confidence."""

    text: str
    # Axis-aligned bounding box in pixels: (x0, y0, x1, y1).
    bbox: tuple[float, float, float, float]
    confidence: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class OcrEngine(Protocol):
    """A recognition backend. Operates on one decoded image at a time."""

    def recognize(self, image, *, languages: list[str]) -> list[OcrBlock]: ...

    def info(self) -> dict: ...

    def ensure_loaded(self) -> None: ...


# --- language code mapping ---------------------------------------------------

# CasaOCR speaks ISO-639-1-ish codes; each engine maps to its own set.
_PADDLE_LANG = {
    "en": "en",
    "ch": "ch",
    "zh": "ch",
    "fr": "fr",
    "de": "german",
    "ko": "korean",
    "ja": "japan",
    "es": "es",
    "pt": "pt",
    "it": "it",
    "ru": "ru",
    "ar": "arabic",
    "hi": "hi",
}

_TESSERACT_LANG = {
    "en": "eng",
    "fr": "fra",
    "de": "deu",
    "es": "spa",
    "pt": "por",
    "it": "ita",
    "ru": "rus",
    "zh": "chi_sim",
    "ch": "chi_sim",
    "ja": "jpn",
    "ko": "kor",
    "ar": "ara",
    "hi": "hin",
    "my": "mya",
}


def _to_ndarray(image):
    """Accept a numpy array or PIL image; return a numpy array (RGB/gray)."""
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise EngineError("numpy is required for OCR") from exc
    if hasattr(image, "mode"):  # PIL.Image
        return np.array(image)
    return image


class PaddleOcrEngine:
    """Default engine — PaddleOCR (PP-OCR), free and self-hosted."""

    def __init__(self, config) -> None:
        self.config = config
        self._models: dict[str, object] = {}

    def info(self) -> dict:
        return {
            "engine": "paddleocr",
            "device": self.config.device,
            "languages": self.config.languages,
            "loaded": sorted(self._models.keys()),
        }

    def ensure_loaded(self) -> None:
        self._model_for(self._lang())

    def _lang(self) -> str:
        langs = self.config.languages or ["en"]
        return _PADDLE_LANG.get(langs[0].lower(), langs[0].lower())

    def _model_for(self, lang: str):
        if lang in self._models:
            return self._models[lang]
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise EngineError(
                "paddleocr is not installed. pip install 'casaocr[paddle]' "
                "(or pip install paddleocr paddlepaddle)"
            ) from exc
        log.info("loading PaddleOCR lang=%s device=%s", lang, self.config.device)
        # Targets the PaddleOCR 2.x classic API (see the pinned extra in
        # pyproject): use_angle_cls + .ocr(img, cls=True). The 3.x/paddlex
        # rewrite changed both the constructor and the output shape.
        model = PaddleOCR(
            use_angle_cls=True,
            lang=lang,
            use_gpu=(self.config.device == "gpu"),
            show_log=False,
        )
        self._models[lang] = model
        return model

    def recognize(self, image, *, languages: list[str]) -> list[OcrBlock]:
        lang = _PADDLE_LANG.get((languages or ["en"])[0].lower(), (languages or ["en"])[0].lower())
        model = self._model_for(lang)
        img = _to_ndarray(image)
        try:
            raw = model.ocr(img, cls=True)
        except Exception as exc:  # noqa: BLE001 — model/version quirks
            raise EngineError(f"paddleocr recognition failed: {exc}") from exc
        return _parse_paddle(raw)

    def close(self) -> None:
        self._models.clear()


def _parse_paddle(raw) -> list[OcrBlock]:
    """Normalize PaddleOCR's nested output to OcrBlocks (version-tolerant)."""
    blocks: list[OcrBlock] = []
    if not raw:
        return blocks
    # Classic API returns [ page ] where page is [ [box, (text, conf)], ... ].
    page = raw[0] if isinstance(raw, list) and raw and isinstance(raw[0], list) else raw
    if page is None:
        return blocks
    for line in page:
        try:
            box, (text, conf) = line[0], line[1]
        except (TypeError, ValueError, IndexError):
            continue
        if not text:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        blocks.append(
            OcrBlock(
                text=str(text),
                bbox=(min(xs), min(ys), max(xs), max(ys)),
                confidence=float(conf) if conf is not None else None,
            )
        )
    return blocks


class TesseractEngine:
    """Lightweight fallback — Tesseract via pytesseract."""

    def __init__(self, config) -> None:
        self.config = config
        self._checked = False

    def info(self) -> dict:
        return {
            "engine": "tesseract",
            "device": "cpu",
            "languages": self.config.languages,
            "loaded": self._checked,
        }

    def ensure_loaded(self) -> None:
        try:
            import pytesseract
        except ImportError as exc:
            raise EngineError(
                "pytesseract is not installed. pip install 'casaocr[tesseract]'"
            ) from exc
        try:
            pytesseract.get_tesseract_version()
        except Exception as exc:  # noqa: BLE001 — binary missing/misconfigured
            raise EngineError(
                "the tesseract binary was not found. Install tesseract-ocr "
                "(apt-get install tesseract-ocr)."
            ) from exc
        self._checked = True

    def _langs(self, languages: list[str]) -> str:
        mapped = [_TESSERACT_LANG.get(code.lower(), code.lower()) for code in (languages or ["en"])]
        return "+".join(dict.fromkeys(mapped))  # de-dupe, preserve order

    def recognize(self, image, *, languages: list[str]) -> list[OcrBlock]:
        import pytesseract
        from pytesseract import Output

        img = _to_ndarray(image)
        try:
            data = pytesseract.image_to_data(
                img, lang=self._langs(languages), output_type=Output.DICT
            )
        except Exception as exc:  # noqa: BLE001
            raise EngineError(f"tesseract recognition failed: {exc}") from exc

        blocks: list[OcrBlock] = []
        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            x, y, w, h = (
                float(data["left"][i]),
                float(data["top"][i]),
                float(data["width"][i]),
                float(data["height"][i]),
            )
            blocks.append(
                OcrBlock(
                    text=text,
                    bbox=(x, y, x + w, y + h),
                    confidence=(conf / 100.0) if conf >= 0 else None,
                )
            )
        return blocks


def build_engine(config, name: str | None = None) -> OcrEngine:
    """Construct the configured (or named) engine."""
    engine = (name or config.engine).lower()
    if engine == "tesseract":
        return TesseractEngine(config)
    return PaddleOcrEngine(config)


__all__ = [
    "EngineError",
    "OcrBlock",
    "OcrEngine",
    "PaddleOcrEngine",
    "TesseractEngine",
    "build_engine",
]
