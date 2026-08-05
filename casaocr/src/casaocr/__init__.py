"""CasaOCR — self-hosted OCR for AI agents. No API keys.

Pluggable engines (PaddleOCR default, Tesseract fallback), an OpenCV
preprocessing pipeline, image + scanned-PDF input, and agent-native markdown /
layout output. URL fetches route through casanova-core's SSRF guard.
"""

from .config import ENGINES, OcrConfig
from .engines import EngineError, OcrBlock, OcrEngine, build_engine
from .render import OcrPage, blocks_to_text, pages_to_markdown
from .tools import OCR_READ_SCHEMA, Toolset

__all__ = [
    "ENGINES",
    "OCR_READ_SCHEMA",
    "EngineError",
    "OcrBlock",
    "OcrConfig",
    "OcrEngine",
    "OcrPage",
    "Toolset",
    "blocks_to_text",
    "build_engine",
    "pages_to_markdown",
]

__version__ = "0.1.0"
