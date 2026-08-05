"""Key information extraction (KIE) from OCR blocks — pure Python, CPU-cheap.

This is the v2 ``form_extract`` engine: it does not run another model, it reads
the boxes ``ocr_read`` already produced and pulls structured data out of them by
geometry and pattern — labelled fields (total, tax, date, invoice number …) and
a best-effort line-item table.

It is deliberately rule/layout-based: honest, fast, and self-hosted on a CPU. It
will not match a GPU vision-language model on arbitrary layouts — that backend
slots in behind the same tool for anyone who brings a GPU. Callers can also pass
their own field templates for a known document shape.
"""

from __future__ import annotations

import re

from .engines import OcrBlock
from .render import order_blocks

# A money amount: optional symbol, digits with thousands separators, 2 decimals.
MONEY_RE = re.compile(r"(?:[$€£¥]\s?)?\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})\b|\b\d+\.\d{2}\b")
# Common date shapes: 2026-08-06, 06/08/2026, Aug 6 2026, 6 August 2026.
DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4})\b",
    re.IGNORECASE,
)
# An invoice-number-ish token after a label: letters/digits/dashes.
IDLIKE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/]{2,}")

# name -> anchor phrases that tend to sit next to the value on a form/invoice.
DEFAULT_FIELDS: dict[str, list[str]] = {
    "total": ["grand total", "amount due", "balance due", "total due", "total"],
    "subtotal": ["subtotal", "sub total"],
    "tax": ["tax", "vat", "gst", "sales tax"],
    "invoice_number": ["invoice number", "invoice no", "invoice #", "inv #", "invoice"],
    "date": ["invoice date", "date"],
}

_MONEY_FIELDS = {"total", "subtotal", "tax"}


def _lines_with_text(blocks: list[OcrBlock]) -> list[dict]:
    """Return lines as {text, blocks} in reading order."""
    lines = order_blocks(blocks)
    out = []
    for line in lines:
        text = " ".join(b.text for b in line).strip()
        out.append({"text": text, "blocks": line})
    return out


def _anchor_pos(low: str, anchor: str) -> int:
    """Index of ``anchor`` in ``low`` on a word boundary, else -1.

    The boundary is what stops the ``total`` anchor from matching inside
    ``subtotal`` — the classic invoice field collision.
    """
    m = re.search(r"(?<![a-z0-9])" + re.escape(anchor), low)
    return m.start() if m else -1


def _value_after_anchor(line_text: str, anchor: str) -> str | None:
    """The text following the anchor phrase within a line, if any."""
    idx = _anchor_pos(line_text.lower(), anchor)
    if idx < 0:
        return None
    tail = line_text[idx + len(anchor):].lstrip(" :\t-").strip()
    return tail or None


def _extract_field(name: str, anchors: list[str], lines: list[dict]) -> str | None:
    money = name in _MONEY_FIELDS
    for i, line in enumerate(lines):
        low = line["text"].lower()
        for anchor in anchors:
            if _anchor_pos(low, anchor) >= 0:
                tail = _value_after_anchor(line["text"], anchor) or ""
                if money:
                    m = list(MONEY_RE.finditer(tail)) or list(MONEY_RE.finditer(line["text"]))
                    if m:
                        return m[-1].group(0).strip()
                    # value may have wrapped to the next line
                    if i + 1 < len(lines):
                        m2 = list(MONEY_RE.finditer(lines[i + 1]["text"]))
                        if m2:
                            return m2[-1].group(0).strip()
                elif name == "date":
                    m = DATE_RE.search(tail) or DATE_RE.search(line["text"])
                    if m:
                        return m.group(0).strip()
                elif name == "invoice_number":
                    m = IDLIKE_RE.search(tail)
                    if m and m.group(0).lower() not in {a.split()[0] for a in anchors}:
                        return m.group(0).strip()
                else:
                    if tail:
                        return tail
    return None


def _extract_table(lines: list[dict]) -> list[list[str]]:
    """Best-effort line-item table: rows are lines with 2+ cells (blocks).

    A cell is one OCR block; only rows that actually have multiple blocks are
    kept, which naturally selects the tabular region over prose lines.
    """
    rows: list[list[str]] = []
    for line in lines:
        cells = [b.text.strip() for b in line["blocks"] if b.text.strip()]
        if len(cells) >= 2:
            rows.append(cells)
    return rows


def extract_form(
    blocks: list[OcrBlock],
    *,
    templates: dict[str, list[str]] | None = None,
    include_table: bool = True,
) -> dict:
    """Pull labelled fields and a line-item table out of OCR blocks.

    Args:
        blocks: OCR blocks (text + bbox) for one page.
        templates: extra/override field anchors, ``{name: [anchor, ...]}``.
            Merged over the built-in invoice fields.
        include_table: also attempt a line-item table.
    """
    fields_def = dict(DEFAULT_FIELDS)
    if templates:
        for name, anchors in templates.items():
            fields_def[name] = [a.lower() for a in (anchors if isinstance(anchors, list) else [anchors])]

    lines = _lines_with_text(blocks)
    fields: dict[str, str | None] = {}
    for name, anchors in fields_def.items():
        fields[name] = _extract_field(name, [a.lower() for a in anchors], lines)

    result = {"fields": fields}
    if include_table:
        result["table"] = _extract_table(lines)
    return result


__all__ = ["DEFAULT_FIELDS", "extract_form"]
