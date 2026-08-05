from __future__ import annotations

from hiraraweb.extract import from_html, sanitize, truncate

ARTICLE = """
<html><head><title>Widget Report</title></head>
<body>
  <nav><a href="/">Home</a><a href="/about">About</a></nav>
  <article>
    <h1>Widget Report</h1>
    <p>The first paragraph carries the actual finding about widgets and it runs
       on long enough that the extractor treats it as real body content.</p>
    <p>The second paragraph adds supporting detail so the article has enough
       substance to survive boilerplate removal cleanly.</p>
  </article>
  <footer>Copyright 2026. Subscribe to our newsletter!</footer>
</body></html>
"""


def test_extracts_body_and_drops_chrome():
    content, title = from_html(ARTICLE, url="https://example.com/report")
    assert "first paragraph" in content
    assert "second paragraph" in content
    assert "Subscribe to our newsletter" not in content
    assert title == "Widget Report"


def test_accepts_bytes():
    content, _ = from_html(ARTICLE.encode("utf-8"), url="https://example.com/report")
    assert "first paragraph" in content


def test_sanitize_strips_zero_width_characters():
    # An injected instruction hidden with zero-width joiners between letters.
    hidden = "ig​no‌re‍ pre﻿vious"
    assert sanitize(hidden) == "ignore previous"


def test_sanitize_strips_bidi_overrides():
    assert sanitize("safe‮txt.exe") == "safetxt.exe"


def test_sanitize_collapses_blank_lines():
    assert sanitize("a\n\n\n\n\nb") == "a\n\nb"


def test_truncate_prefers_a_paragraph_boundary():
    text = "a" * 80 + "\n\n" + "b" * 60
    out, was_cut = truncate(text, 100)
    assert was_cut
    assert out == "a" * 80


def test_truncate_falls_back_to_a_hard_cut():
    """An early boundary would waste most of the budget, so take the hard cut."""
    text = "a" * 10 + "\n\n" + "b" * 200
    out, was_cut = truncate(text, 100)
    assert was_cut
    assert len(out) == 100


def test_truncate_is_a_noop_below_the_limit():
    out, was_cut = truncate("short", 100)
    assert out == "short"
    assert not was_cut
