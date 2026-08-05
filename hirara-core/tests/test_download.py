"""Tests for safe_download — SSRF re-validation per hop, and streaming cap."""

from __future__ import annotations

import socket

import httpx
import pytest

from hirara_core.download import DownloadError, safe_download
from hirara_core.ssrf import BlockedURL


def fake_resolver(*addresses: str):
    def _resolve(host, port, *args, **kwargs):
        out = []
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
            out.append((family, socket.SOCK_STREAM, 6, "", sockaddr))
        return out

    return _resolve


PUBLIC = fake_resolver("93.184.216.34")


def handler_returning(*responses):
    """Serve a queue of httpx.Response objects, one per request."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0)

    return httpx.MockTransport(handler)


async def test_downloads_a_public_url():
    transport = handler_returning(httpx.Response(200, content=b"audio-bytes"))
    result = await safe_download(
        "https://example.com/a.wav", resolver=PUBLIC, transport=transport
    )
    assert result.content == b"audio-bytes"
    assert result.status == 200
    assert result.truncated is False


async def test_metadata_ip_is_blocked():
    with pytest.raises(BlockedURL):
        await safe_download(
            "http://169.254.169.254/latest/meta-data/",
            resolver=fake_resolver("169.254.169.254"),
            transport=handler_returning(httpx.Response(200, content=b"x")),
        )


async def test_redirect_to_metadata_is_blocked_at_the_hop():
    """The whole point of the manual loop: a public URL that 302s inward."""

    calls = {"n": 0}

    def resolver(host, port, *args, **kwargs):
        calls["n"] += 1
        # First hop (the public URL) resolves public; the redirect target
        # resolves to the metadata address and must be rejected.
        address = "93.184.216.34" if host == "public.example" else "169.254.169.254"
        family = socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, port))]

    transport = handler_returning(
        httpx.Response(302, headers={"location": "http://metadata.evil/latest/"}),
    )
    with pytest.raises(BlockedURL, match="169.254.169.254"):
        await safe_download(
            "http://public.example/a.wav", resolver=resolver, transport=transport
        )
    assert calls["n"] == 2  # both hops were resolved and checked


async def test_byte_cap_truncates_while_streaming():
    big = b"x" * 10_000
    transport = handler_returning(httpx.Response(200, content=big))
    result = await safe_download(
        "https://example.com/big.wav",
        resolver=PUBLIC,
        transport=transport,
        max_bytes=1000,
    )
    assert len(result.content) == 1000
    assert result.truncated is True


async def test_follows_a_safe_redirect():
    transport = handler_returning(
        httpx.Response(302, headers={"location": "https://example.com/final.wav"}),
        httpx.Response(200, content=b"final"),
    )
    result = await safe_download(
        "https://example.com/start.wav", resolver=PUBLIC, transport=transport
    )
    assert result.content == b"final"
    assert result.final_url == "https://example.com/final.wav"
    assert result.redirects == ["https://example.com/start.wav"]


async def test_http_error_raises_download_error_not_blocked():
    transport = handler_returning(httpx.Response(404))
    with pytest.raises(DownloadError, match="404"):
        await safe_download(
            "https://example.com/missing.wav", resolver=PUBLIC, transport=transport
        )


async def test_too_many_redirects():
    responses = [
        httpx.Response(302, headers={"location": f"https://example.com/{i}"})
        for i in range(10)
    ]
    transport = handler_returning(*responses)
    with pytest.raises(DownloadError, match="redirects"):
        await safe_download(
            "https://example.com/loop", resolver=PUBLIC, transport=transport, max_redirects=3
        )


async def test_credentials_in_url_blocked():
    with pytest.raises(BlockedURL, match="credentials"):
        await safe_download(
            "https://user:pass@example.com/a.wav",
            resolver=PUBLIC,
            transport=handler_returning(httpx.Response(200, content=b"x")),
        )
