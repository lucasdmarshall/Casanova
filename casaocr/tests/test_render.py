"""Reading-order and markdown assembly (pure Python, no image deps)."""

from __future__ import annotations

from casaocr.engines import OcrBlock
from casaocr.render import OcrPage, blocks_to_text, order_blocks, pages_to_markdown


def blk(text, x0, y0, x1, y1):
    return OcrBlock(text=text, bbox=(x0, y0, x1, y1), confidence=0.9)


def test_reading_order_left_to_right_top_to_bottom():
    # deliberately out of order: right-then-left on line 1, line 2 below
    blocks = [
        blk("world", 100, 10, 150, 30),
        blk("hello", 10, 12, 60, 32),
        blk("second", 10, 60, 90, 82),
    ]
    assert blocks_to_text(blocks) == "hello world\nsecond"


def test_order_blocks_groups_lines():
    blocks = [blk("a", 0, 0, 10, 20), blk("b", 20, 2, 30, 22), blk("c", 0, 60, 10, 80)]
    lines = order_blocks(blocks)
    assert len(lines) == 2
    assert [b.text for b in lines[0]] == ["a", "b"]


def test_empty_blocks():
    assert blocks_to_text([]) == ""
    assert order_blocks([]) == []
    assert pages_to_markdown([]) == ""


def test_markdown_single_page_is_plain():
    page = OcrPage(page=1, text="hello world", blocks=[])
    assert pages_to_markdown([page]) == "hello world"


def test_markdown_multi_page_has_separators():
    pages = [OcrPage(1, "alpha", []), OcrPage(2, "beta", [])]
    md = pages_to_markdown(pages)
    assert "## Page 1" in md
    assert "## Page 2" in md
    assert "alpha" in md and "beta" in md
