"""The tool layer: schemas and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

Three tools, matching the three things people mean by "a PDF tool":

* ``pdf_read``   — the reader: text + metadata out of a PDF.
* ``pdf_info``   — the parser: structure (pages, outline, form fields) cheaply.
* ``pdf_create`` — the maker: a PDF out of Markdown or plain text.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from hirara_core import BlockedURL, DownloadError, safe_download

from .config import PdfConfig
from .maker import MakeError, build_pdf
from .reader import ReaderError, inspect_pdf, read_pdf

log = logging.getLogger(__name__)

_SOURCE_PROPS = {
    "pdf_path": {
        "type": "string",
        "description": "Absolute or relative path to a local PDF file.",
    },
    "pdf_url": {
        "type": "string",
        "description": "http(s) URL of a PDF (server must allow URL fetch).",
    },
    "pdf_base64": {
        "type": "string",
        "description": "Base64-encoded PDF bytes. Prefer path/upload for large files.",
    },
    "password": {
        "type": "string",
        "description": "Password for an encrypted PDF (omit if not encrypted).",
    },
}

PDF_READ_SCHEMA = {
    "name": "pdf_read",
    "description": (
        "Extract the text of a PDF (and its metadata) so you can read a "
        "document you cannot open directly: reports, papers, invoices, "
        "contracts, scanned-then-OCR'd files, ebooks.\n\n"
        "Provide exactly one source: pdf_path (local file), pdf_url "
        "(http/https, if the server allows URL fetch), or pdf_base64 (raw "
        "bytes). Returns the full text, per-page text, page count and "
        "document metadata. Very long PDFs are truncated at the server's "
        "character cap — the result flags truncated=true when that happens.\n\n"
        "This reads the PDF's embedded text layer; it does not OCR images. A "
        "scanned PDF with no text layer comes back with little or no text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            **_SOURCE_PROPS,
            "include_pages": {
                "type": "boolean",
                "description": "Include per-page text array (default true).",
            },
        },
        "additionalProperties": False,
    },
}

PDF_INFO_SCHEMA = {
    "name": "pdf_info",
    "description": (
        "Inspect a PDF's structure without extracting all its text: page "
        "count, metadata (title/author/dates), whether it is encrypted, the "
        "outline/bookmark headings, AcroForm field names, and each page's "
        "size. Use this first to decide whether or how to read a large or "
        "unfamiliar PDF.\n\n"
        "Provide exactly one source: pdf_path, pdf_url, or pdf_base64."
    ),
    "input_schema": {
        "type": "object",
        "properties": dict(_SOURCE_PROPS),
        "additionalProperties": False,
    },
}

PDF_CREATE_SCHEMA = {
    "name": "pdf_create",
    "description": (
        "Generate a PDF from Markdown, plain text, or HTML and return it as "
        "base64 (and optionally write it to a path). Use this to turn a "
        "report, letter, summary, or any content you have produced into a "
        "shareable PDF file.\n\n"
        "content is the document body. format is 'markdown' (headings with "
        "#, - bullets, 1. numbered lists, ``` code fences, **bold**, "
        "*italic*, `code`), 'text' (plain, blank lines separate paragraphs), "
        "or 'html' (a practical subset of HTML + CSS — headings, paragraphs, "
        "lists, tables, simple styling; no JavaScript, flexbox or grid). "
        "Optional title/author/subject set the document heading and metadata; "
        "page_size is A4, LETTER, LEGAL, A3, or A5.\n\n"
        "output_path writes the PDF to disk when the server allows local "
        "paths; otherwise use the returned pdf_base64."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Document body — Markdown subset, plain text, or HTML.",
            },
            "format": {
                "type": "string",
                "enum": ["markdown", "text", "html"],
                "description": "How to interpret content (default markdown).",
            },
            "title": {"type": "string", "description": "Heading + PDF title metadata."},
            "author": {"type": "string", "description": "PDF author metadata."},
            "subject": {"type": "string", "description": "PDF subject metadata."},
            "page_size": {
                "type": "string",
                "enum": ["A4", "LETTER", "LEGAL", "A3", "A5"],
                "description": "Page size (default A4).",
            },
            "output_path": {
                "type": "string",
                "description": "Write the PDF here (server must allow local paths).",
            },
        },
        "required": ["content"],
        "additionalProperties": False,
    },
}


def _read_envelope(**overrides) -> dict:
    envelope = {
        "text": None,
        "pages": [],
        "page_count": None,
        "metadata": {},
        "encrypted": None,
        "truncated": None,
        "source": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _info_envelope(**overrides) -> dict:
    envelope = {
        "page_count": None,
        "encrypted": None,
        "metadata": {},
        "outline": [],
        "form_fields": [],
        "has_form": None,
        "page_sizes": [],
        "source": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _create_envelope(**overrides) -> dict:
    envelope = {
        "pdf_base64": None,
        "bytes": None,
        "page_size": None,
        "output_path": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """Composed PDF tools sharing one config."""

    config: PdfConfig

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=PdfConfig.from_env())

    def schemas(self) -> list[dict]:
        return [PDF_READ_SCHEMA, PDF_INFO_SCHEMA, PDF_CREATE_SCHEMA]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "config": {
                "max_bytes": self.config.max_bytes,
                "allow_url_fetch": self.config.allow_url_fetch,
                "allow_local_path": self.config.allow_local_path,
                "default_page_size": self.config.default_page_size,
            },
        }

    # --- source resolution (shared by pdf_read and pdf_info) ---

    async def _resolve_to_bytes(
        self,
        *,
        pdf_path: str | None,
        pdf_url: str | None,
        pdf_base64: str | None,
        pdf_bytes: bytes | None,
    ) -> tuple[bytes, str]:
        """Return (data, source_label). Raises ReaderError on any bad source."""
        provided = sum(
            1
            for value in (pdf_path, pdf_url, pdf_base64, pdf_bytes)
            if value is not None and value != ""
        )
        if provided == 0:
            raise ReaderError(
                "provide exactly one of pdf_path, pdf_url, pdf_base64, or an upload"
            )
        if provided > 1:
            raise ReaderError(
                "provide only one PDF source (pdf_path, pdf_url, pdf_base64, or upload)"
            )

        if pdf_bytes is not None:
            self._check_size(len(pdf_bytes))
            return pdf_bytes, "upload"

        if pdf_path:
            if not self.config.allow_local_path:
                raise ReaderError(
                    "pdf_path is disabled on this server. It lets a caller name "
                    "any file on the host, which is unsafe over a network-exposed "
                    "service. Use an upload or pdf_base64 instead, or set "
                    "CPDF_ALLOW_LOCAL_PATH=true if this server is trusted/local."
                )
            path = Path(pdf_path).expanduser()
            if not path.is_file():
                raise ReaderError(f"PDF file not found: {path}")
            self._check_size(path.stat().st_size)
            return path.read_bytes(), str(path)

        if pdf_base64:
            try:
                data = base64.b64decode(pdf_base64, validate=False)
            except Exception as exc:
                raise ReaderError(f"invalid pdf_base64: {exc}") from exc
            self._check_size(len(data))
            return data, "pdf_base64"

        assert pdf_url is not None
        if not self.config.allow_url_fetch:
            raise ReaderError(
                "pdf_url is disabled. Set CPDF_ALLOW_URL_FETCH=true on a trusted "
                "network, or upload / pdf_base64 the file instead."
            )
        # The fetch goes through hirara-core's safe_download, not a bare
        # httpx.get: the URL and every redirect hop run through the SSRF guard
        # (a public URL that 302s to 169.254.169.254 is rejected at the hop)
        # and the body streams under a hard byte cap.
        try:
            result = await safe_download(
                pdf_url,
                max_bytes=self.config.max_bytes,
                timeout=self.config.url_timeout,
            )
        except BlockedURL as exc:
            raise ReaderError(f"pdf_url blocked: {exc}") from exc
        except DownloadError as exc:
            raise ReaderError(f"pdf_url download failed: {exc}") from exc
        if result.truncated:
            raise ReaderError(
                f"pdf_url exceeds CPDF_MAX_BYTES ({self.config.max_bytes} bytes)"
            )
        return result.content, pdf_url

    def _check_size(self, size: int) -> None:
        if size > self.config.max_bytes:
            raise ReaderError(
                f"PDF exceeds CPDF_MAX_BYTES ({self.config.max_bytes} bytes)"
            )

    # --- pdf_read ---

    async def read(
        self,
        *,
        pdf_path: str | None = None,
        pdf_url: str | None = None,
        pdf_base64: str | None = None,
        pdf_bytes: bytes | None = None,
        password: str | None = None,
        include_pages: bool = True,
    ) -> dict:
        source = pdf_path or pdf_url or "upload"
        try:
            data, source = await self._resolve_to_bytes(
                pdf_path=pdf_path,
                pdf_url=pdf_url,
                pdf_base64=pdf_base64,
                pdf_bytes=pdf_bytes,
            )
            doc = read_pdf(
                data,
                password=password,
                max_chars=self.config.max_chars,
                include_pages=include_pages,
            )
            payload = doc.as_dict(include_pages=include_pages)
            payload["source"] = source
            payload["error"] = None
            return payload
        except ReaderError as exc:
            return _read_envelope(error=str(exc), source=source)
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("pdf_read failed")
            return _read_envelope(error=f"pdf_read failed: {exc}", source=source)

    # --- pdf_info ---

    async def info(
        self,
        *,
        pdf_path: str | None = None,
        pdf_url: str | None = None,
        pdf_base64: str | None = None,
        pdf_bytes: bytes | None = None,
        password: str | None = None,
    ) -> dict:
        source = pdf_path or pdf_url or "upload"
        try:
            data, source = await self._resolve_to_bytes(
                pdf_path=pdf_path,
                pdf_url=pdf_url,
                pdf_base64=pdf_base64,
                pdf_bytes=pdf_bytes,
            )
            result = inspect_pdf(data, password=password)
            result["source"] = source
            result["error"] = None
            return result
        except ReaderError as exc:
            return _info_envelope(error=str(exc), source=source)
        except Exception as exc:  # noqa: BLE001
            log.exception("pdf_info failed")
            return _info_envelope(error=f"pdf_info failed: {exc}", source=source)

    # --- pdf_create ---

    def create(
        self,
        *,
        content: str,
        format: str = "markdown",
        title: str | None = None,
        author: str | None = None,
        subject: str | None = None,
        page_size: str | None = None,
        output_path: str | None = None,
    ) -> dict:
        page = (page_size or self.config.default_page_size).upper()
        try:
            if content is not None and len(content) > self.config.max_create_chars:
                raise MakeError(
                    f"content exceeds CPDF_MAX_CREATE_CHARS "
                    f"({self.config.max_create_chars} chars)"
                )
            data = build_pdf(
                content,
                fmt=format,
                title=title,
                author=author,
                subject=subject,
                page_size=page,
            )
            written: str | None = None
            if output_path:
                if not self.config.allow_local_path:
                    raise MakeError(
                        "output_path is disabled on this server. It lets a caller "
                        "write anywhere on the host. Use the returned pdf_base64, "
                        "or set CPDF_ALLOW_LOCAL_PATH=true if this server is "
                        "trusted/local."
                    )
                dest = Path(output_path).expanduser()
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                written = str(dest)
            return _create_envelope(
                pdf_base64=base64.b64encode(data).decode("ascii"),
                bytes=len(data),
                page_size=page,
                output_path=written,
            )
        except MakeError as exc:
            return _create_envelope(error=str(exc), page_size=page)
        except Exception as exc:  # noqa: BLE001
            log.exception("pdf_create failed")
            return _create_envelope(error=f"pdf_create failed: {exc}", page_size=page)


__all__ = [
    "PDF_CREATE_SCHEMA",
    "PDF_INFO_SCHEMA",
    "PDF_READ_SCHEMA",
    "Toolset",
]
