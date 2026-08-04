"""PDF reader / parser — pure-Python text and structure extraction via pypdf.

Two shapes come out of here:

* :func:`read_pdf`   — the *reader*: full text, per-page text, and metadata.
* :func:`inspect_pdf` — the *parser*: cheap structural facts (page count,
  metadata, encryption, outline, form fields, page geometry) without pulling
  every glyph off every page.

Neither touches the network or the filesystem — callers hand in bytes. That
keeps the SSRF-sensitive "where did these bytes come from" decision in one
place (``tools.py``), not scattered across the extractor.
"""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass, field


class ReaderError(RuntimeError):
    """Raised when a PDF cannot be opened, decrypted, or parsed."""


@dataclass(frozen=True)
class PdfPage:
    """One page's extracted text and physical size (in PDF points)."""

    number: int  # 1-based
    text: str
    width: float | None = None
    height: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PdfDocument:
    """JSON-ready result of reading a PDF."""

    text: str
    pages: list[PdfPage] = field(default_factory=list)
    page_count: int = 0
    metadata: dict = field(default_factory=dict)
    encrypted: bool = False
    truncated: bool = False

    def as_dict(self, *, include_pages: bool = True) -> dict:
        return {
            "text": self.text,
            "pages": [p.as_dict() for p in self.pages] if include_pages else [],
            "page_count": self.page_count,
            "metadata": self.metadata,
            "encrypted": self.encrypted,
            "truncated": self.truncated,
        }


def _open(data: bytes, password: str | None):
    """Open bytes as a pypdf PdfReader, decrypting with the given password.

    pypdf already tries an empty password on encrypted files, so a PDF that is
    "encrypted" only to set permissions (very common) opens with no password
    at all. A real user password that is wrong raises ReaderError.
    """
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as exc:  # pragma: no cover - dependency always present
        raise ReaderError(
            "pypdf is not installed. pip install 'casanovapdf' or pip install pypdf"
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise ReaderError(f"could not open PDF: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — malformed input, not our bug
        raise ReaderError(f"not a readable PDF: {exc}") from exc

    # Only decrypt when the file is actually encrypted: pypdf rejects a
    # password handed to a plain file with "Not an encrypted file". An empty
    # password is tried first, which opens the very common "encrypted only to
    # set permissions" case with no password at all.
    if getattr(reader, "is_encrypted", False):
        try:
            decrypted = reader.decrypt(password or "")
        except Exception as exc:  # noqa: BLE001 — malformed crypto dict
            raise ReaderError(f"could not decrypt PDF: {exc}") from exc
        if not decrypted:
            raise ReaderError(
                "PDF is encrypted and the password was missing or wrong"
            )
    return reader


def _clean_metadata(reader) -> dict:
    meta = reader.metadata
    if not meta:
        return {}
    out: dict = {}
    # pypdf exposes friendly properties; fall back to the raw /Key names.
    for key, attr in (
        ("title", "title"),
        ("author", "author"),
        ("subject", "subject"),
        ("creator", "creator"),
        ("producer", "producer"),
        ("creation_date", "creation_date"),
        ("modification_date", "modification_date"),
    ):
        try:
            value = getattr(meta, attr, None)
        except Exception:  # noqa: BLE001 — some producers write junk dates
            value = None
        if value is not None:
            out[key] = str(value)
    return out


def read_pdf(
    data: bytes,
    *,
    password: str | None = None,
    max_chars: int = 200_000,
    include_pages: bool = True,
) -> PdfDocument:
    """Extract text and metadata from PDF bytes.

    Extraction stops once ``max_chars`` characters have been collected across
    pages; the result is flagged ``truncated`` so the agent knows the tail is
    missing rather than silently trusting a half-read document.
    """
    reader = _open(data, password)
    encrypted = bool(getattr(reader, "is_encrypted", False))

    pages: list[PdfPage] = []
    chunks: list[str] = []
    collected = 0
    truncated = False

    for i, page in enumerate(reader.pages):
        if collected >= max_chars:
            truncated = True
            break
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — one bad page shouldn't kill the read
            text = ""
        remaining = max_chars - collected
        if len(text) > remaining:
            text = text[:remaining]
            truncated = True
        collected += len(text)

        width = height = None
        try:
            box = page.mediabox
            width = float(box.width)
            height = float(box.height)
        except Exception:  # noqa: BLE001 — geometry is best-effort
            pass

        chunks.append(text)
        if include_pages:
            pages.append(PdfPage(number=i + 1, text=text, width=width, height=height))

    return PdfDocument(
        text="\n\n".join(c for c in chunks if c).strip(),
        pages=pages,
        page_count=len(reader.pages),
        metadata=_clean_metadata(reader),
        encrypted=encrypted,
        truncated=truncated,
    )


def _outline_titles(reader) -> list[str]:
    """Flatten the document outline (bookmarks / table of contents) to titles."""
    titles: list[str] = []

    def walk(items) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            title = getattr(item, "title", None)
            if title:
                titles.append(str(title))

    try:
        walk(reader.outline)
    except Exception:  # noqa: BLE001 — outline is optional and often malformed
        return []
    return titles


def inspect_pdf(data: bytes, *, password: str | None = None) -> dict:
    """Structural parse: metadata, geometry and structure without full text.

    This is the cheap "what is this file" call — page count, metadata,
    encryption state, outline headings, AcroForm field names, and per-page
    sizes — for when the agent needs to decide *whether* or *how* to read a
    PDF before paying to extract every page.
    """
    reader = _open(data, password)

    page_sizes = []
    for page in reader.pages:
        try:
            box = page.mediabox
            page_sizes.append({"width": float(box.width), "height": float(box.height)})
        except Exception:  # noqa: BLE001
            page_sizes.append({"width": None, "height": None})

    fields: list[str] = []
    try:
        raw_fields = reader.get_fields()
        if raw_fields:
            fields = list(raw_fields.keys())
    except Exception:  # noqa: BLE001 — no AcroForm, or a malformed one
        fields = []

    return {
        "page_count": len(reader.pages),
        "encrypted": bool(getattr(reader, "is_encrypted", False)),
        "metadata": _clean_metadata(reader),
        "outline": _outline_titles(reader),
        "form_fields": fields,
        "has_form": bool(fields),
        "page_sizes": page_sizes,
    }


__all__ = [
    "PdfDocument",
    "PdfPage",
    "ReaderError",
    "inspect_pdf",
    "read_pdf",
]
