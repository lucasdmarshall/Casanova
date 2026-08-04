"""A redirect-safe, size-capped downloader built on the SSRF guard.

Any Casanova tool that fetches an attacker-influenceable URL should use this
instead of a bare ``httpx.get``. It does the three things a naive fetch skips:

1. Runs the URL — and *every redirect hop* — through :func:`resolve_target`,
   so a public URL that 302s to ``http://169.254.169.254/`` is rejected at the
   hop, not followed blindly.
2. Pins each request to the exact IP the guard validated, carrying the real
   hostname in ``Host`` and SNI so TLS still verifies against the name.
3. Streams the body and aborts the moment it crosses ``max_bytes`` — the cap
   bounds memory *during* the download, not after it has already filled RAM.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .ssrf import BlockedURL, Target, resolve_target

DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; casanova/0.1; +https://github.com/lucasdmarshall/Casanova)"
)


class DownloadError(RuntimeError):
    """A non-security failure: bad status, transport error, too many redirects.

    Security refusals raise :class:`~casanova_core.ssrf.BlockedURL` instead, so
    callers can tell "this URL is not allowed" from "this URL did not work".
    """


@dataclass(slots=True)
class DownloadResult:
    content: bytes
    final_url: str
    status: int
    content_type: str
    truncated: bool
    redirects: list[str]


def _pin(target: Target) -> httpx.URL:
    return httpx.URL(target.url).copy_with(host=target.ip)


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


async def safe_download(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    timeout: float = 30.0,
    user_agent: str = DEFAULT_USER_AGENT,
    accept: str = "*/*",
    allow_private_ips: bool = False,
    resolver=None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> DownloadResult:
    """Fetch ``url`` through the SSRF guard, streaming and size-capped.

    Raises :class:`~casanova_core.ssrf.BlockedURL` if the URL (or any redirect
    hop) fails the perimeter, and :class:`DownloadError` for ordinary failures.

    ``resolver`` and ``transport`` are test seams — production callers leave
    both unset, getting real DNS and a real network. They exist so the SSRF
    and byte-cap behaviour can be exercised without live hosts.
    """
    redirects: list[str] = []
    current = url

    # resolve_target defaults its own resolver to socket.getaddrinfo; only
    # override when a caller (a test) supplies one.
    resolve_kwargs = {"allow_private_ips": allow_private_ips}
    if resolver is not None:
        resolve_kwargs["resolver"] = resolver

    limits = httpx.Limits(max_connections=4, max_keepalive_connections=0)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        limits=limits,
        transport=transport,
    ) as client:
        for _ in range(max_redirects + 1):
            target = resolve_target(current, **resolve_kwargs)

            request = client.build_request(
                "GET",
                _pin(target),
                headers={
                    "Host": target.host_header,
                    "User-Agent": user_agent,
                    "Accept": accept,
                    "Accept-Encoding": "gzip, deflate",
                },
                # Carry the real hostname into the TLS handshake so the
                # certificate is verified against the name, not the pinned IP.
                extensions={"sni_hostname": target.host},
            )

            response = await client.send(request, stream=True)
            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise DownloadError(
                            f"{response.status_code} redirect with no Location header"
                        )
                    redirects.append(current)
                    current = str(httpx.URL(current).join(location))
                    continue

                if response.status_code >= 400:
                    raise DownloadError(f"HTTP {response.status_code} for {current}")

                content_type = (
                    response.headers.get("content-type", "").split(";")[0].strip().lower()
                )
                body, truncated = await _read_capped(response, max_bytes)
            finally:
                await response.aclose()

            return DownloadResult(
                content=body,
                final_url=current,
                status=response.status_code,
                content_type=content_type or "application/octet-stream",
                truncated=truncated,
                redirects=redirects,
            )

    raise DownloadError(f"exceeded {max_redirects} redirects starting at {url}")


def safe_download_sync(url: str, **kwargs) -> DownloadResult:
    """Blocking wrapper, for scripts and non-async callers."""
    import asyncio

    return asyncio.run(safe_download(url, **kwargs))
