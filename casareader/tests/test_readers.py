"""Read real (in-memory) docx/pptx/xlsx and check the markdown + detection."""

from __future__ import annotations

import pytest

from casareader.readers import ReaderError, detect_kind, read_office


def test_read_docx(docx_bytes):
    doc = read_office(docx_bytes)
    assert doc.kind == "docx"
    assert "# Title Heading" in doc.markdown
    assert "- Bullet item" in doc.markdown
    assert "| A | B |" in doc.markdown
    assert "A normal paragraph." in doc.text


def test_read_pptx(pptx_bytes):
    doc = read_office(pptx_bytes)
    assert doc.kind == "pptx"
    assert "## Slide 1" in doc.markdown
    assert "Deck Title" in doc.markdown
    assert "Slide body line" in doc.markdown
    assert "Some speaker notes" in doc.markdown
    assert doc.meta["slides"] == 1


def test_read_xlsx(xlsx_bytes):
    doc = read_office(xlsx_bytes)
    assert doc.kind == "xlsx"
    assert "## Sheet: Data" in doc.markdown
    assert "| Name | Qty |" in doc.markdown
    assert "Widget" in doc.markdown
    assert doc.meta["sheet_names"] == ["Data"]


def test_detect_by_content(docx_bytes, pptx_bytes, xlsx_bytes):
    assert detect_kind(docx_bytes) == "docx"
    assert detect_kind(pptx_bytes) == "pptx"
    assert detect_kind(xlsx_bytes) == "xlsx"


def test_legacy_binary_rejected():
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32
    with pytest.raises(ReaderError) as exc:
        detect_kind(ole)
    assert "legacy" in str(exc.value)


def test_garbage_rejected():
    with pytest.raises(ReaderError):
        detect_kind(b"this is not a document")
