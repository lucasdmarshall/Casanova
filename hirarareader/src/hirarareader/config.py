"""Runtime configuration for HiraraReader.

Everything is overridable by environment variable so the same image can run
locked down on a network-exposed host or open on a trusted laptop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Office formats read in v1. All backed by permissive (MIT) libraries.
KINDS = ("docx", "pptx", "xlsx")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


@dataclass(frozen=True)
class ReaderConfig:
    """Reader knobs."""

    # Max size of an input document accepted from callers.
    max_bytes: int = 25 * 1024 * 1024

    # Cap on extracted text/markdown returned; flags truncated when hit.
    max_chars: int = 500_000

    # Per-sheet row cap for spreadsheets — a runaway sheet shouldn't return a
    # million rows of markdown.
    max_rows: int = 2_000

    # Fetch a document from an http(s) URL. Off by default; when on the fetch
    # goes through hirara-core's safe_download (resolve-then-pin, redirect
    # re-validation, streamed byte cap), never a bare httpx.get.
    allow_url_fetch: bool = False
    url_timeout: float = 30.0

    # Read a local file the caller names by path. Fine for a local/MCP server;
    # set CRDR_ALLOW_LOCAL_PATH=false on a network-exposed service and use
    # upload / base64 instead.
    allow_local_path: bool = True

    @classmethod
    def from_env(cls) -> "ReaderConfig":
        return cls(
            max_bytes=_env_int("CRDR_MAX_BYTES", cls.max_bytes),
            max_chars=_env_int("CRDR_MAX_CHARS", cls.max_chars),
            max_rows=_env_int("CRDR_MAX_ROWS", cls.max_rows),
            allow_url_fetch=_env_bool("CRDR_ALLOW_URL_FETCH", cls.allow_url_fetch),
            url_timeout=_env_float("CRDR_URL_TIMEOUT", cls.url_timeout),
            allow_local_path=_env_bool("CRDR_ALLOW_LOCAL_PATH", cls.allow_local_path),
        )


__all__ = ["KINDS", "ReaderConfig"]
