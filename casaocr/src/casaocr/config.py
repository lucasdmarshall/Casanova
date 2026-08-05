"""Runtime configuration for CasaOCR.

CPU-first defaults so the same image runs on a plain VPS; point ``COCR_DEVICE=gpu``
where a GPU is available. Everything is overridable by environment variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Engines that ship in v1. Both are permissively licensed (Apache-2.0), which
# keeps the hub clean. Heavier handwriting/VLM backends arrive in v2 behind the
# same OcrEngine seam.
ENGINES = ("paddleocr", "tesseract")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return list(default)
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass(frozen=True)
class OcrConfig:
    """Reader knobs for the OCR pipeline."""

    # Default recognition engine. A request may override it per call.
    engine: str = "paddleocr"

    # Language hints (ISO-639-1-ish, e.g. en, fr, de). Each engine maps these to
    # its own code set. English by default.
    languages: list[str] = field(default_factory=lambda: ["en"])

    # cpu | gpu. Only the deep-learning engines (PaddleOCR) use this.
    device: str = "cpu"

    # Run the OpenCV preprocessing pipeline (deskew, denoise, binarize) before
    # recognition. The single biggest accuracy lever; on by default.
    preprocess: bool = True

    # Max size of an input image/PDF accepted from callers.
    max_bytes: int = 25 * 1024 * 1024

    # Cap on extracted text returned; result flags truncated when hit.
    max_chars: int = 500_000

    # Scanned-PDF handling: how many pages to OCR, and at what rasterization DPI.
    max_pages: int = 50
    pdf_dpi: int = 200

    # Fetch an image/PDF from an http(s) URL. Off by default; when on, the fetch
    # goes through casanova-core's safe_download (resolve-then-pin, redirect
    # re-validation, streamed byte cap) rather than a bare httpx.get.
    allow_url_fetch: bool = False
    url_timeout: float = 30.0

    # Read a local file the caller names by path. Fine for a local/MCP server;
    # set COCR_ALLOW_LOCAL_PATH=false on a network-exposed service and use
    # upload / base64 instead.
    allow_local_path: bool = True

    @classmethod
    def from_env(cls) -> "OcrConfig":
        engine = os.getenv("COCR_ENGINE", cls.engine).strip().lower()
        if engine not in ENGINES:
            engine = cls.engine
        device = os.getenv("COCR_DEVICE", cls.device).strip().lower()
        if device not in {"cpu", "gpu"}:
            device = cls.device
        return cls(
            engine=engine,
            languages=_env_list("COCR_LANGUAGES", ["en"]),
            device=device,
            preprocess=_env_bool("COCR_PREPROCESS", cls.preprocess),
            max_bytes=_env_int("COCR_MAX_BYTES", cls.max_bytes),
            max_chars=_env_int("COCR_MAX_CHARS", cls.max_chars),
            max_pages=_env_int("COCR_MAX_PAGES", cls.max_pages),
            pdf_dpi=_env_int("COCR_PDF_DPI", cls.pdf_dpi),
            allow_url_fetch=_env_bool("COCR_ALLOW_URL_FETCH", cls.allow_url_fetch),
            url_timeout=_env_float("COCR_URL_TIMEOUT", cls.url_timeout),
            allow_local_path=_env_bool("COCR_ALLOW_LOCAL_PATH", cls.allow_local_path),
        )


__all__ = ["ENGINES", "OcrConfig"]
