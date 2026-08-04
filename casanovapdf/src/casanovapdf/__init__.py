"""Casanovapdf — self-hosted PDF read / parse / create tools for AI agents.

No API keys, pure-Python: pypdf reads and parses, reportlab writes. URL fetches
route through casanova-core's SSRF guard.
"""

from .config import PAGE_SIZES, PdfConfig
from .maker import MakeError, build_pdf
from .reader import PdfDocument, PdfPage, ReaderError, inspect_pdf, read_pdf
from .tools import (
    PDF_CREATE_SCHEMA,
    PDF_INFO_SCHEMA,
    PDF_READ_SCHEMA,
    Toolset,
)

__all__ = [
    "PAGE_SIZES",
    "PDF_CREATE_SCHEMA",
    "PDF_INFO_SCHEMA",
    "PDF_READ_SCHEMA",
    "MakeError",
    "PdfConfig",
    "PdfDocument",
    "PdfPage",
    "ReaderError",
    "Toolset",
    "build_pdf",
    "inspect_pdf",
    "read_pdf",
]

__version__ = "0.1.0"
