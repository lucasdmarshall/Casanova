"""Key-information extraction from OCR blocks (pure Python, no models)."""

from __future__ import annotations

from hiraraocr.engines import OcrBlock
from hiraraocr.extract import extract_form


def blk(text, x, y, w=40, h=20):
    return OcrBlock(text=text, bbox=(x, y, x + w, y + h), confidence=0.9)


def _invoice_blocks():
    # each line at a distinct y; label + value(s) share a y
    return [
        blk("Invoice #:", 0, 10), blk("INV-2026-0042", 120, 10, w=120),
        blk("Date:", 0, 50), blk("2026-08-06", 80, 50, w=100),
        blk("Widget A", 0, 90), blk("2", 150, 90, w=10), blk("10.00", 200, 90),
        blk("Widget B", 0, 130), blk("1", 150, 130, w=10), blk("5.00", 200, 130),
        blk("Subtotal:", 0, 170), blk("25.00", 120, 170),
        blk("Tax:", 0, 210), blk("2.50", 120, 210),
        blk("Total:", 0, 250), blk("27.50", 120, 250),
    ]


def test_extracts_invoice_fields():
    r = extract_form(_invoice_blocks())
    f = r["fields"]
    assert f["total"] == "27.50"        # not 25.00 — 'total' must not match 'subtotal'
    assert f["subtotal"] == "25.00"
    assert f["tax"] == "2.50"
    assert f["date"] == "2026-08-06"
    assert f["invoice_number"] == "INV-2026-0042"


def test_total_does_not_capture_subtotal():
    # a document with only a subtotal line: 'total' should stay unfound
    blocks = [blk("Subtotal:", 0, 10), blk("42.00", 120, 10)]
    r = extract_form(blocks)
    assert r["fields"]["subtotal"] == "42.00"
    assert r["fields"]["total"] is None


def test_line_item_table_has_rows():
    r = extract_form(_invoice_blocks())
    assert ["Widget A", "2", "10.00"] in r["table"]
    assert ["Widget B", "1", "5.00"] in r["table"]


def test_custom_template_field():
    blocks = [blk("PO #:", 0, 10), blk("PO-77", 100, 10)]
    r = extract_form(blocks, templates={"po_number": ["po #"]})
    assert r["fields"]["po_number"] == "PO-77"


def test_empty_blocks():
    r = extract_form([])
    assert r["fields"]["total"] is None
    assert r["table"] == []
