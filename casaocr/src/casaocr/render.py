"""Turn recognized blocks into reading-order text and agent-friendly markdown.

Pure Python, no image or model dependencies — which is what makes the layout
logic straightforward to unit-test. Engines give us boxes; this decides the
order humans (and agents) actually read them in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .engines import OcrBlock


@dataclass
class OcrPage:
    """One page's recognized text and blocks."""

    page: int
    text: str
    blocks: list[OcrBlock] = field(default_factory=list)
    width: int | None = None
    height: int | None = None


def _center_y(b: OcrBlock) -> float:
    return (b.bbox[1] + b.bbox[3]) / 2.0


def _height(b: OcrBlock) -> float:
    return max(1.0, b.bbox[3] - b.bbox[1])


def order_blocks(blocks: list[OcrBlock]) -> list[list[OcrBlock]]:
    """Group blocks into lines (top-to-bottom), each ordered left-to-right.

    Two blocks share a line when their vertical centers are within ~60% of the
    median block height — tolerant enough for slightly skewed scans, tight
    enough not to merge separate lines.
    """
    if not blocks:
        return []
    ordered = sorted(blocks, key=_center_y)
    med_h = sorted(_height(b) for b in ordered)[len(ordered) // 2]
    tol = med_h * 0.6

    lines: list[list[OcrBlock]] = []
    current: list[OcrBlock] = [ordered[0]]
    line_y = _center_y(ordered[0])
    for b in ordered[1:]:
        if abs(_center_y(b) - line_y) <= tol:
            current.append(b)
        else:
            lines.append(sorted(current, key=lambda x: x.bbox[0]))
            current = [b]
        # track a running center so a gently sloping line still groups
        line_y = _center_y(b)
    lines.append(sorted(current, key=lambda x: x.bbox[0]))
    return lines


def blocks_to_text(blocks: list[OcrBlock]) -> str:
    """Reading-order plain text: blocks joined on a line, lines by newline."""
    lines = order_blocks(blocks)
    return "\n".join(" ".join(b.text for b in line) for line in lines).strip()


def pages_to_markdown(pages: list[OcrPage]) -> str:
    """Markdown output. Multi-page documents get ``## Page N`` separators."""
    if not pages:
        return ""
    if len(pages) == 1:
        return pages[0].text.strip()
    chunks: list[str] = []
    for page in pages:
        chunks.append(f"## Page {page.page}\n\n{page.text.strip()}")
    return "\n\n".join(chunks).strip()


__all__ = ["OcrPage", "blocks_to_text", "order_blocks", "pages_to_markdown"]
