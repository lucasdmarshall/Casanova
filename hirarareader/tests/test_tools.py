"""Toolset orchestration — source handling, detection, guards."""

from __future__ import annotations

import base64

import pytest

from hirarareader.config import ReaderConfig
from hirarareader.tools import OFFICE_READ_SCHEMA, Toolset


def _toolset(**cfg) -> Toolset:
    return Toolset(config=ReaderConfig(**cfg))


def test_schema_is_agent_ready():
    assert OFFICE_READ_SCHEMA["name"] == "office_read"
    props = OFFICE_READ_SCHEMA["input_schema"]["properties"]
    assert {"file_path", "file_url", "file_base64", "filename"} <= set(props)


@pytest.mark.asyncio
async def test_read_docx_base64(docx_bytes):
    r = await _toolset().read(file_base64=base64.b64encode(docx_bytes).decode())
    assert r["error"] is None
    assert r["kind"] == "docx"
    assert "# Title Heading" in r["markdown"]
    assert r["source"] == "file_base64"


@pytest.mark.asyncio
async def test_read_xlsx_upload(xlsx_bytes):
    r = await _toolset().read(file_bytes=xlsx_bytes, filename="book.xlsx")
    assert r["error"] is None
    assert r["kind"] == "xlsx"
    assert "| Name | Qty |" in r["markdown"]


@pytest.mark.asyncio
async def test_rejects_multiple_sources(docx_bytes):
    r = await _toolset().read(
        file_base64=base64.b64encode(docx_bytes).decode(), file_path="/x.docx"
    )
    assert r["error"] and "only one" in r["error"]


@pytest.mark.asyncio
async def test_missing_source_returns_envelope():
    r = await _toolset().read()
    assert r["error"]
    assert set(r) >= {"kind", "markdown", "text", "meta", "source", "error"}


@pytest.mark.asyncio
async def test_local_path_can_be_disabled():
    r = await _toolset(allow_local_path=False).read(file_path="/etc/x.docx")
    assert r["error"] and "CRDR_ALLOW_LOCAL_PATH" in r["error"]


@pytest.mark.asyncio
async def test_url_fetch_disabled_by_default():
    r = await _toolset(allow_url_fetch=False).read(file_url="https://example.com/a.docx")
    assert r["error"] and "CRDR_ALLOW_URL_FETCH" in r["error"]


@pytest.mark.asyncio
async def test_max_bytes_enforced(docx_bytes):
    r = await _toolset(max_bytes=10).read(file_base64=base64.b64encode(docx_bytes).decode())
    assert r["error"] and "CRDR_MAX_BYTES" in r["error"]


@pytest.mark.asyncio
async def test_garbage_bytes_report_cleanly():
    r = await _toolset().read(file_base64=base64.b64encode(b"not an office file").decode())
    assert r["error"] and "unrecognized" in r["error"]


@pytest.mark.asyncio
async def test_url_fetch_routes_through_the_ssrf_guard(monkeypatch):
    from hirara_core import BlockedURL
    import hirarareader.tools as tools_module

    async def fake_download(url, **kwargs):
        raise BlockedURL("169.254.169.254 is not globally routable")

    monkeypatch.setattr(tools_module, "safe_download", fake_download)
    r = await _toolset(allow_url_fetch=True).read(file_url="http://169.254.169.254/a.docx")
    assert r["markdown"] is None
    assert "blocked" in r["error"]


@pytest.mark.asyncio
async def test_url_fetch_happy_path(monkeypatch, docx_bytes):
    from hirara_core import DownloadResult
    import hirarareader.tools as tools_module

    async def fake_download(url, **kwargs):
        return DownloadResult(
            content=docx_bytes,
            final_url=url,
            status=200,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            truncated=False,
            redirects=[],
        )

    monkeypatch.setattr(tools_module, "safe_download", fake_download)
    r = await _toolset(allow_url_fetch=True).read(file_url="https://example.com/a.docx")
    assert r["error"] is None
    assert r["kind"] == "docx"
    assert r["source"] == "https://example.com/a.docx"
