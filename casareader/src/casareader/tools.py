"""The tool layer: schema and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

One tool: ``office_read`` — a Word, PowerPoint, or Excel file in, markdown +
plain text out.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

from casanova_core import BlockedURL, DownloadError, safe_download

from .config import ReaderConfig
from .readers import ReaderError, read_office

log = logging.getLogger(__name__)


OFFICE_READ_SCHEMA = {
    "name": "office_read",
    "description": (
        "Read a Microsoft Office document — Word (.docx), PowerPoint (.pptx), "
        "or Excel (.xlsx) — into clean, formatted text. Use this whenever the "
        "content you need is inside an Office file and you want its text: a "
        "report, a slide deck, a spreadsheet.\n\n"
        "The format is auto-detected, so one tool handles all three. Provide "
        "exactly one source: file_path (local file), file_url (http/https, if "
        "the server allows URL fetch), or file_base64 (raw bytes). Returns "
        "markdown that preserves structure — headings and lists for Word, "
        "per-slide text and speaker notes for PowerPoint, one markdown table "
        "per sheet for Excel — plus the plain text.\n\n"
        "Legacy binary formats (.doc/.xls/.ppt) are not supported; ask for the "
        "modern .docx/.pptx/.xlsx instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute or relative path to a local .docx/.pptx/.xlsx.",
            },
            "file_url": {
                "type": "string",
                "description": "http(s) URL of an Office file (server must allow URL fetch).",
            },
            "file_base64": {
                "type": "string",
                "description": "Base64-encoded document bytes.",
            },
            "filename": {
                "type": "string",
                "description": "Original filename — a detection hint for base64/URL input.",
            },
        },
        "additionalProperties": False,
    },
}


def _envelope(**overrides) -> dict:
    envelope = {
        "kind": None,
        "markdown": None,
        "text": None,
        "meta": {},
        "truncated": None,
        "source": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """Office-reading tool sharing one config."""

    config: ReaderConfig

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=ReaderConfig.from_env())

    def schemas(self) -> list[dict]:
        return [OFFICE_READ_SCHEMA]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "formats": ["docx", "pptx", "xlsx"],
        }

    async def _resolve_bytes(
        self,
        *,
        file_path: str | None,
        file_url: str | None,
        file_base64: str | None,
        file_bytes: bytes | None,
    ) -> tuple[bytes, str]:
        provided = sum(1 for v in (file_path, file_url, file_base64, file_bytes) if v)
        if provided == 0:
            raise ReaderError(
                "provide exactly one of file_path, file_url, file_base64, or an upload"
            )
        if provided > 1:
            raise ReaderError(
                "provide only one source (file_path, file_url, file_base64, or upload)"
            )

        if file_bytes is not None:
            self._check_size(len(file_bytes))
            return file_bytes, "upload"

        if file_path:
            if not self.config.allow_local_path:
                raise ReaderError(
                    "file_path is disabled on this server. It lets a caller name "
                    "any file on the host. Use an upload or file_base64 instead, "
                    "or set CRDR_ALLOW_LOCAL_PATH=true if this server is trusted."
                )
            from pathlib import Path

            path = Path(file_path).expanduser()
            if not path.is_file():
                raise ReaderError(f"file not found: {path}")
            self._check_size(path.stat().st_size)
            return path.read_bytes(), str(path)

        if file_base64:
            try:
                data = base64.b64decode(file_base64, validate=False)
            except Exception as exc:
                raise ReaderError(f"invalid file_base64: {exc}") from exc
            self._check_size(len(data))
            return data, "file_base64"

        assert file_url is not None
        if not self.config.allow_url_fetch:
            raise ReaderError(
                "file_url is disabled. Set CRDR_ALLOW_URL_FETCH=true on a trusted "
                "network, or upload / file_base64 the file instead."
            )
        try:
            result = await safe_download(
                file_url, max_bytes=self.config.max_bytes, timeout=self.config.url_timeout
            )
        except BlockedURL as exc:
            raise ReaderError(f"file_url blocked: {exc}") from exc
        except DownloadError as exc:
            raise ReaderError(f"file_url download failed: {exc}") from exc
        if result.truncated:
            raise ReaderError(f"file_url exceeds CRDR_MAX_BYTES ({self.config.max_bytes} bytes)")
        return result.content, file_url

    def _check_size(self, size: int) -> None:
        if size > self.config.max_bytes:
            raise ReaderError(f"file exceeds CRDR_MAX_BYTES ({self.config.max_bytes} bytes)")

    async def read(
        self,
        *,
        file_path: str | None = None,
        file_url: str | None = None,
        file_base64: str | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
    ) -> dict:
        import asyncio

        source = file_path or file_url or filename or "upload"
        try:
            data, source = await self._resolve_bytes(
                file_path=file_path,
                file_url=file_url,
                file_base64=file_base64,
                file_bytes=file_bytes,
            )
            hint = filename or (file_path or file_url or None)
            doc = await asyncio.to_thread(
                read_office, data, filename=hint, max_rows=self.config.max_rows
            )

            markdown = doc.markdown
            text = doc.text
            truncated = doc.truncated
            if len(markdown) > self.config.max_chars:
                markdown = markdown[: self.config.max_chars]
                truncated = True
            if len(text) > self.config.max_chars:
                text = text[: self.config.max_chars]
                truncated = True

            return _envelope(
                kind=doc.kind,
                markdown=markdown,
                text=text,
                meta=doc.meta,
                truncated=truncated,
                source=source,
                error=None,
            )
        except ReaderError as exc:
            return _envelope(error=str(exc), source=source)
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("office_read failed")
            return _envelope(error=f"office_read failed: {exc}", source=source)


__all__ = ["OFFICE_READ_SCHEMA", "Toolset"]
