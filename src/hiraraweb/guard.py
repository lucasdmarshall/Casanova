"""SSRF perimeter — now a thin shim over :mod:`hirara_core.ssrf`.

The guard used to live here. It moved to the shared ``hirara-core`` package
so every tool in the hub uses one implementation instead of a private copy —
the transcription tool proved why: a new tool with its own URL fetch shipped
without any perimeter at all. There is now exactly one place to fix, or forget.

This module re-exports the guard so existing imports (``from .guard import
resolve_target``) keep working unchanged.
"""

from __future__ import annotations

from hirara_core.ssrf import (
    ALLOWED_PORTS,
    ALLOWED_SCHEMES,
    BlockedURL,
    Target,
    check_ip,
    resolve_target,
)

__all__ = [
    "ALLOWED_PORTS",
    "ALLOWED_SCHEMES",
    "BlockedURL",
    "Target",
    "check_ip",
    "resolve_target",
]
