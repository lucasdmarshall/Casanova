"""``web_fetch``: retrieve one URL and return clean text.

Redirects are followed manually rather than by httpx, because every hop is a
fresh chance to be pointed at the cloud metadata endpoint. Each hop is
re-validated by :mod:`hiraraweb.guard` and re-pinned to a vetted IP.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from .config import FetchConfig
from .extract import from_html, from_pdf, from_text, truncate
from .guard import BlockedURL, Target, resolve_target

_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_PDF_TYPES = {"application/pdf", "application/x-pdf"}
_TEXT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/xml",
    "application/xml",
    "application/json",
    "application/ld+json",
    "application/rss+xml",
    "application/atom+xml",
}


class FetchError(RuntimeError):
    """The fetch failed for a non-security reason (status, type, transport)."""


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    title: str | None
    content: str
    truncated: bool
    bytes_downloaded: int
    elapsed_ms: int
    redirects: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "content_type": self.content_type,
            "title": self.title,
            "content": self.content,
            "truncated": self.truncated,
            "bytes_downloaded": self.bytes_downloaded,
            "elapsed_ms": self.elapsed_ms,
            "redirects": self.redirects,
        }


def _pin(target: Target) -> httpx.URL:
    """Rewrite the URL to the validated IP, keeping path, query and port."""
    return httpx.URL(target.url).copy_with(host=target.ip)


def _request_headers(target: Target, cfg: FetchConfig) -> dict[str, str]:
    return {
        "Host": target.host_header,
        "User-Agent": cfg.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }


async def _read_capped(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    """Read the body, stopping at ``max_bytes`` of *decoded* content.

    Capping after decompression is what makes this bomb-proof: a 1 KB gzip
    payload that expands to 10 GB is aborted a few chunks in.
    """
    chunks: list[bytes] = []
    total = 0
    hit_cap = False

    async for chunk in response.aiter_bytes():
        remaining = max_bytes - total
        if len(chunk) >= remaining:
            chunks.append(chunk[:remaining])
            total += remaining
            hit_cap = True
            break
        chunks.append(chunk)
        total += len(chunk)

    return b"".join(chunks), hit_cap


async def _fetch(url: str, cfg: FetchConfig, max_chars: int) -> FetchResult:
    started = time.monotonic()
    redirects: list[str] = []
    current = url

    timeout = httpx.Timeout(
        connect=cfg.connect_timeout,
        read=cfg.read_timeout,
        write=cfg.read_timeout,
        pool=cfg.connect_timeout,
    )

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=0),
    ) as client:
        for _ in range(cfg.max_redirects + 1):
            target = resolve_target(current, allow_private_ips=cfg.allow_private_ips)

            request = client.build_request(
                "GET",
                _pin(target),
                headers=_request_headers(target, cfg),
                # Carry the real hostname into the TLS handshake so the
                # certificate is still verified against the name, not the IP.
                extensions={"sni_hostname": target.host},
            )

            response = await client.send(request, stream=True)
            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError(f"{response.status_code} redirect with no Location header")
                    redirects.append(current)
                    current = str(httpx.URL(current).join(location))
                    continue

                if response.status_code >= 400:
                    raise FetchError(f"HTTP {response.status_code} for {current}")

                raw_type = response.headers.get("content-type", "")
                content_type = raw_type.split(";")[0].strip().lower()
                body, body_capped = await _read_capped(response, cfg.max_bytes)
            finally:
                await response.aclose()

            content, title = _decode(body, content_type, response, current, body_capped)
            content, text_capped = truncate(content, max_chars)

            return FetchResult(
                url=url,
                final_url=current,
                status=response.status_code,
                content_type=content_type or "application/octet-stream",
                title=title,
                content=content,
                truncated=body_capped or text_capped,
                bytes_downloaded=len(body),
                elapsed_ms=int((time.monotonic() - started) * 1000),
                redirects=redirects,
            )

    raise FetchError(f"exceeded {cfg.max_redirects} redirects starting at {url}")


def _decode(
    body: bytes,
    content_type: str,
    response: httpx.Response,
    url: str,
    body_capped: bool,
) -> tuple[str, str | None]:
    if content_type in _HTML_TYPES or (not content_type and body.lstrip()[:1] == b"<"):
        # trafilatura sniffs the encoding itself, including from the meta tag,
        # so it gets the bytes rather than our guess at a decoding.
        return from_html(body, url=url)

    if content_type in _PDF_TYPES:
        if body_capped:
            raise FetchError("PDF exceeded the size limit; a partial PDF cannot be parsed")
        return from_pdf(body)

    if content_type in _TEXT_TYPES or content_type.startswith("text/"):
        encoding = response.charset_encoding or "utf-8"
        return from_text(body.decode(encoding, errors="replace"))

    raise FetchError(f"unsupported content type {content_type!r} for {url}")


async def web_fetch(
    url: str,
    *,
    max_chars: int | None = None,
    config: FetchConfig | None = None,
) -> FetchResult:
    """Fetch ``url`` and return its main content as text.

    Raises :class:`~hiraraweb.guard.BlockedURL` if the URL fails the security
    perimeter, and :class:`FetchError` for ordinary failures.
    """
    cfg = config or FetchConfig.from_env()
    limit = max_chars if max_chars is not None else cfg.max_chars

    try:
        async with asyncio.timeout(cfg.total_timeout):
            return await _fetch(url, cfg, limit)
    except TimeoutError as exc:
        raise FetchError(f"timed out after {cfg.total_timeout}s fetching {url}") from exc
    except BlockedURL:
        raise
    except httpx.HTTPError as exc:
        # Several httpx exceptions (ReadTimeout in particular) stringify to "",
        # so lead with the class name or the message is empty.
        detail = f"{type(exc).__name__}: {exc}".rstrip(": ")
        raise FetchError(f"transport error fetching {url} ({detail})") from exc


def web_fetch_sync(url: str, **kwargs) -> FetchResult:
    """Blocking wrapper, for scripts and tests."""
    return asyncio.run(web_fetch(url, **kwargs))
