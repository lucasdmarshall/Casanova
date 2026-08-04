# casanova-core

Shared building blocks for [Casanova](https://github.com/lucasdmarshall/Casanova)
agent tools. Small on purpose.

## Why it exists

A tool that fetches an attacker-influenceable URL needs an SSRF perimeter. If
each tool hand-rolls its own, a new tool eventually ships without one — and
that is not hypothetical: the transcription tool added a URL-fetch path with a
bare `httpx.get(url, follow_redirects=True)` and no guard at all. This package
is the one guard every tool imports, so that hole can only be fixed — or
forgotten — in one place.

## What's in it

| Symbol | Role |
|---|---|
| `resolve_target(url)` | Resolve-then-pin: validates the URL, checks **every** returned address, returns a `Target` pinned to one vetted IP. Raises `BlockedURL`. |
| `check_ip(ip)` | Is this address globally routable and not reserved? |
| `safe_download(url)` | A full redirect-safe, size-capped fetcher built on the guard — re-validates every hop, pins each request, streams and aborts at `max_bytes`. |

## Usage

```python
from casanova_core import safe_download, BlockedURL, DownloadError

try:
    result = await safe_download(audio_url, max_bytes=25 * 1024 * 1024)
    data = result.content            # bytes, never larger than max_bytes
except BlockedURL as exc:
    ...   # the URL is not allowed — a private IP, a bad scheme, a redirect inward
except DownloadError as exc:
    ...   # it was allowed but did not work — bad status, transport error
```

`BlockedURL` (a security refusal) is kept distinct from `DownloadError` (an
ordinary failure) on purpose — a caller should treat "not allowed" and "did
not work" differently.

## The two rules

1. **Resolve, then check every address, then pin.** Rejecting only the first
   resolved address lets a resolver hand back one good IP and one bad one.
2. **Connect to the pinned IP, hostname in `Host` + SNI.** Validating a name
   and letting the client resolve it again is a DNS-rebinding hole.

`safe_download` runs *every redirect hop* back through rule 1, so a public URL
that `302`s to `http://169.254.169.254/` is rejected at the hop.

## Tests

```bash
pip install -e '.[dev]'
pytest -q
```

One case per real technique: metadata IPs, CGNAT, v4-mapped IPv6, 6to4,
split-horizon DNS answers, credential-stuffed URLs, non-web ports, redirect-to-
metadata, and the streaming byte cap.
