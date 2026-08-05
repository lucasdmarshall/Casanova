"""Tests for the PDF maker (reportlab)."""

from __future__ import annotations

import pytest

from hirarapdf.maker import MakeError, build_pdf


def test_build_markdown_produces_a_pdf():
    data = build_pdf(
        "# Title\n\nA paragraph with **bold** and *italic* and `code`.\n\n"
        "- one\n- two\n\n```\ncode block\n```",
        fmt="markdown",
        title="Report",
    )
    assert data[:5] == b"%PDF-"
    assert data.rstrip().endswith(b"%%EOF")
    assert len(data) > 500


def test_build_text_produces_a_pdf():
    data = build_pdf("first para\n\nsecond para", fmt="text")
    assert data[:5] == b"%PDF-"


def test_inline_special_chars_do_not_break_markup():
    # `<` `&` `>` must be escaped before reportlab's mini-HTML is applied,
    # otherwise this raises inside doc.build and surfaces as MakeError.
    data = build_pdf("a < b & c > d and <not a tag>", fmt="text")
    assert data[:5] == b"%PDF-"


def test_page_size_letter():
    data = build_pdf("hi", fmt="text", page_size="LETTER")
    assert data[:5] == b"%PDF-"


def test_unknown_page_size_rejected():
    with pytest.raises(MakeError):
        build_pdf("hi", fmt="text", page_size="A0")


def test_empty_content_rejected():
    with pytest.raises(MakeError):
        build_pdf("   ", fmt="markdown")


def test_bad_format_rejected():
    with pytest.raises(MakeError):
        build_pdf("hi", fmt="json")


def test_build_html_fragment_produces_a_pdf():
    data = build_pdf(
        "<h1>Report</h1><p>Body with <b>bold</b></p><ul><li>a</li><li>b</li></ul>",
        fmt="html",
        title="HTML Doc",
        author="Tester",
    )
    assert data[:5] == b"%PDF-"
    assert len(data) > 500


def test_build_html_full_document():
    data = build_pdf(
        "<html><head><title>Full</title></head><body><h1>Hi</h1>"
        "<table><tr><td>a</td><td>b</td></tr></table></body></html>",
        fmt="html",
    )
    assert data[:5] == b"%PDF-"


def test_html_unknown_page_size_rejected():
    with pytest.raises(MakeError):
        build_pdf("<p>hi</p>", fmt="html", page_size="A0")


def test_html_empty_content_rejected():
    with pytest.raises(MakeError):
        build_pdf("   ", fmt="html")
