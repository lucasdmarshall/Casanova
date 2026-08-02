"""Turn a fetched body into text a model can actually use.

Raw HTML is mostly navigation, scripts and cookie banners; handing it straight
to a model burns tokens and buries the content. We run boilerplate removal
first, then normalise the result.

The sanitising step is a security control, not cosmetics. Fetched pages are
untrusted input, and the usual trick is to hide instructions where a human
reviewer will not see them: white-on-white text, HTML comments, zero-width
characters, bidi overrides. We strip the invisible carriers so that anything
addressed at the model is at least readable in the transcript.
"""

from __future__ import annotations

import io
import re
import unicodedata

import trafilatura

# Zero-width and directionality characters. Legitimate prose does not need
# them; injected payloads use them to hide from human review.
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)


def sanitize(text: str) -> str:
    """Normalise text and drop characters that exist only to hide content."""
    text = unicodedata.normalize("NFC", text)
    text = _INVISIBLE.sub("", text)
    # Keep newlines and tabs, drop every other control character.
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) != "Cc")
    text = _TRAILING_SPACE.sub("", text)
    return _EXCESS_BLANK_LINES.sub("\n\n", text).strip()


def from_html(html: str | bytes, url: str | None = None) -> tuple[str, str | None]:
    """Extract main content as markdown. Returns ``(content, title)``.

    Accepts bytes so trafilatura can sniff the page's own declared encoding
    instead of inheriting a guess from the caller.
    """
    content = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=True,
        include_tables=True,
        include_comments=False,
        # Precision over recall: a short clean article beats a long one with
        # the sidebar glued back on.
        favor_precision=True,
    )
    if not content:
        # Trafilatura returns None on pages with no article-shaped body
        # (search results, app shells). Fall back to bare text so the caller
        # still gets something to judge.
        content = trafilatura.extract(html, url=url, output_format="txt") or ""

    title = None
    try:
        meta = trafilatura.extract_metadata(html, default_url=url)
        if meta is not None:
            title = meta.title
    except Exception:
        # Metadata is a nice-to-have; never fail a fetch over it.
        title = None

    return sanitize(content), title


def from_pdf(data: bytes) -> tuple[str, str | None]:
    """Extract text from a PDF. Returns ``(content, title)``."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            # One malformed page should not lose the rest of the document.
            continue

    title = None
    try:
        if reader.metadata:
            title = reader.metadata.title
    except Exception:
        title = None

    return sanitize("\n\n".join(pages)), title


def from_text(data: str) -> tuple[str, str | None]:
    return sanitize(data), None


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Cut ``text`` to ``max_chars``, preferring a paragraph boundary."""
    if len(text) <= max_chars:
        return text, False

    window = text[:max_chars]
    cut = window.rfind("\n\n")
    # Only honour the boundary if it is not throwing away most of the budget.
    if cut > max_chars * 0.6:
        window = window[:cut]
    return window.rstrip(), True
