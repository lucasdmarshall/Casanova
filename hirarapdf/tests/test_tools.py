"""Tests for the Hirarapdf tool layer — schemas, source handling, envelopes."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from hirarapdf.config import PdfConfig
from hirarapdf.tools import (
    PDF_CREATE_SCHEMA,
    PDF_INFO_SCHEMA,
    PDF_READ_SCHEMA,
    Toolset,
)


def _sample_pdf_b64() -> str:
    ts = Toolset(config=PdfConfig())
    made = ts.create(content="Roundtrip body text.", format="text", title="RT")
    assert made["error"] is None
    return made["pdf_base64"]


def test_schemas_are_agent_ready():
    assert PDF_READ_SCHEMA["name"] == "pdf_read"
    assert PDF_INFO_SCHEMA["name"] == "pdf_info"
    assert PDF_CREATE_SCHEMA["name"] == "pdf_create"
    assert "content" in PDF_CREATE_SCHEMA["input_schema"]["required"]
    assert PDF_CREATE_SCHEMA["input_schema"]["properties"]["format"]["enum"] == [
        "markdown",
        "text",
        "html",
    ]


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("CPDF_MAX_BYTES", "1000")
    monkeypatch.setenv("CPDF_ALLOW_URL_FETCH", "true")
    monkeypatch.setenv("CPDF_PAGE_SIZE", "letter")
    cfg = PdfConfig.from_env()
    assert cfg.max_bytes == 1000
    assert cfg.allow_url_fetch is True
    assert cfg.default_page_size == "LETTER"


def test_create_returns_base64():
    ts = Toolset(config=PdfConfig())
    result = ts.create(content="# Hi\n\nBody.", format="markdown", title="Doc")
    assert result["error"] is None
    assert result["bytes"] > 0
    assert base64.b64decode(result["pdf_base64"])[:5] == b"%PDF-"
    assert result["output_path"] is None


def test_create_html_roundtrips_through_reader():
    ts = Toolset(config=PdfConfig())
    made = ts.create(
        content="<h1>HTML Title</h1><p>Body from HTML.</p>",
        format="html",
        title="HTML Doc",
    )
    assert made["error"] is None
    assert base64.b64decode(made["pdf_base64"])[:5] == b"%PDF-"


def test_create_rejects_unknown_format():
    ts = Toolset(config=PdfConfig())
    result = ts.create(content="hi", format="json")
    assert result["error"]
    assert "format" in result["error"]


def test_create_content_cap():
    ts = Toolset(config=PdfConfig(max_create_chars=5))
    result = ts.create(content="way too long", format="text")
    assert result["error"]
    assert "CPDF_MAX_CREATE_CHARS" in result["error"]


def test_create_writes_file_when_allowed(tmp_path: Path):
    ts = Toolset(config=PdfConfig(allow_local_path=True))
    dest = tmp_path / "out" / "doc.pdf"
    result = ts.create(content="body", format="text", output_path=str(dest))
    assert result["error"] is None
    assert result["output_path"] == str(dest)
    assert dest.read_bytes()[:5] == b"%PDF-"


def test_create_output_path_blocked_when_disabled(tmp_path: Path):
    ts = Toolset(config=PdfConfig(allow_local_path=False))
    result = ts.create(
        content="body", format="text", output_path=str(tmp_path / "x.pdf")
    )
    assert result["error"]
    assert "CPDF_ALLOW_LOCAL_PATH" in result["error"]


@pytest.mark.asyncio
async def test_read_base64_roundtrip():
    ts = Toolset(config=PdfConfig())
    result = await ts.read(pdf_base64=_sample_pdf_b64())
    assert result["error"] is None
    assert "Roundtrip" in result["text"]
    assert result["page_count"] == 1
    assert result["source"] == "pdf_base64"


@pytest.mark.asyncio
async def test_info_base64_roundtrip():
    ts = Toolset(config=PdfConfig())
    result = await ts.info(pdf_base64=_sample_pdf_b64())
    assert result["error"] is None
    assert result["page_count"] == 1
    assert result["has_form"] is False


@pytest.mark.asyncio
async def test_read_path_roundtrip(tmp_path: Path):
    pdf = base64.b64decode(_sample_pdf_b64())
    dest = tmp_path / "doc.pdf"
    dest.write_bytes(pdf)
    ts = Toolset(config=PdfConfig(allow_local_path=True))
    result = await ts.read(pdf_path=str(dest))
    assert result["error"] is None
    assert result["source"] == str(dest)


@pytest.mark.asyncio
async def test_read_path_blocked_when_disabled(tmp_path: Path):
    dest = tmp_path / "doc.pdf"
    dest.write_bytes(base64.b64decode(_sample_pdf_b64()))
    ts = Toolset(config=PdfConfig(allow_local_path=False))
    result = await ts.read(pdf_path=str(dest))
    assert result["error"]
    assert "CPDF_ALLOW_LOCAL_PATH" in result["error"]


@pytest.mark.asyncio
async def test_rejects_multiple_sources():
    ts = Toolset(config=PdfConfig())
    result = await ts.read(pdf_base64=_sample_pdf_b64(), pdf_path="/x.pdf")
    assert result["error"]
    assert "only one" in result["error"]


@pytest.mark.asyncio
async def test_missing_source_returns_envelope():
    ts = Toolset(config=PdfConfig())
    result = await ts.read()
    assert set(result) >= {"text", "pages", "page_count", "metadata", "source", "error"}
    assert result["error"]
    assert result["text"] is None


@pytest.mark.asyncio
async def test_url_fetch_disabled_by_default():
    ts = Toolset(config=PdfConfig(allow_url_fetch=False))
    result = await ts.read(pdf_url="https://example.com/a.pdf")
    assert result["error"]
    assert "CPDF_ALLOW_URL_FETCH" in result["error"]


@pytest.mark.asyncio
async def test_max_bytes_enforced_on_base64():
    ts = Toolset(config=PdfConfig(max_bytes=10))
    result = await ts.read(pdf_base64=_sample_pdf_b64())
    assert result["error"]
    assert "CPDF_MAX_BYTES" in result["error"]


@pytest.mark.asyncio
async def test_url_fetch_routes_through_the_ssrf_guard(monkeypatch):
    """A blocked pdf_url comes back as an error envelope, not an exception.

    The block itself is hirara-core's job (and is tested there); here we
    prove hirarapdf actually calls it and surfaces the refusal.
    """
    from hirara_core import BlockedURL
    import hirarapdf.tools as tools_module

    async def fake_download(url, **kwargs):
        raise BlockedURL("169.254.169.254 is not globally routable")

    monkeypatch.setattr(tools_module, "safe_download", fake_download)
    ts = Toolset(config=PdfConfig(allow_url_fetch=True))
    result = await ts.read(pdf_url="http://169.254.169.254/a.pdf")
    assert result["text"] is None
    assert "blocked" in result["error"]


@pytest.mark.asyncio
async def test_url_fetch_happy_path_uses_downloaded_bytes(monkeypatch):
    from hirara_core import DownloadResult
    import hirarapdf.tools as tools_module

    pdf = base64.b64decode(_sample_pdf_b64())

    async def fake_download(url, **kwargs):
        return DownloadResult(
            content=pdf,
            final_url=url,
            status=200,
            content_type="application/pdf",
            truncated=False,
            redirects=[],
        )

    monkeypatch.setattr(tools_module, "safe_download", fake_download)
    ts = Toolset(config=PdfConfig(allow_url_fetch=True))
    result = await ts.read(pdf_url="https://example.com/doc.pdf")
    assert result["error"] is None
    assert "Roundtrip" in result["text"]
    assert result["source"] == "https://example.com/doc.pdf"


@pytest.mark.asyncio
async def test_url_fetch_truncation_is_reported(monkeypatch):
    from hirara_core import DownloadResult
    import hirarapdf.tools as tools_module

    async def fake_download(url, **kwargs):
        return DownloadResult(
            content=b"%PDF-partial",
            final_url=url,
            status=200,
            content_type="application/pdf",
            truncated=True,
            redirects=[],
        )

    monkeypatch.setattr(tools_module, "safe_download", fake_download)
    ts = Toolset(config=PdfConfig(allow_url_fetch=True, max_bytes=10))
    result = await ts.read(pdf_url="https://example.com/big.pdf")
    assert result["error"]
    assert "CPDF_MAX_BYTES" in result["error"]
