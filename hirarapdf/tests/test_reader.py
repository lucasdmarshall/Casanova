"""Tests for the PDF reader / parser (pypdf), roundtripped through the maker."""

from __future__ import annotations

from hirarapdf.maker import build_pdf
from hirarapdf.reader import ReaderError, inspect_pdf, read_pdf


def _sample(text: str = "Hello Hirara PDF world.", title: str = "Sample") -> bytes:
    return build_pdf(text, fmt="text", title=title, author="Tester")


def test_read_extracts_text_and_metadata():
    pdf = _sample()
    doc = read_pdf(pdf)
    assert "Hirara" in doc.text
    assert doc.page_count == 1
    assert doc.encrypted is False
    assert doc.truncated is False
    assert len(doc.pages) == 1
    assert doc.pages[0].number == 1
    assert doc.pages[0].width and doc.pages[0].height
    assert doc.metadata.get("author") == "Tester"


def test_read_respects_max_chars():
    pdf = _sample("word " * 500)
    doc = read_pdf(pdf, max_chars=20)
    assert doc.truncated is True
    assert len(doc.text) <= 20


def test_read_can_skip_pages():
    pdf = _sample()
    doc = read_pdf(pdf, include_pages=False)
    assert doc.pages == []
    assert doc.text  # text still returned


def test_inspect_reports_structure():
    pdf = _sample()
    info = inspect_pdf(pdf)
    assert info["page_count"] == 1
    assert info["encrypted"] is False
    assert info["has_form"] is False
    assert info["form_fields"] == []
    assert len(info["page_sizes"]) == 1
    assert info["page_sizes"][0]["width"]


def test_not_a_pdf_raises():
    try:
        read_pdf(b"this is definitely not a pdf")
    except ReaderError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ReaderError on garbage input")
