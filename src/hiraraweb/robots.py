"""robots.txt support.

Two things this does *not* do, both deliberate:

It does not use :func:`urllib.robotparser.RobotFileParser.read`. That method
fetches the URL itself with ``urllib.request.urlopen`` — bypassing the SSRF
perimeter entirely. A hostile redirect on a robots.txt fetch would reach
straight into your network. We fetch the file ourselves through
:mod:`hiraraweb.guard` and hand the parser only the text.

It does not fail closed. RFC 9309 permits treating a 5xx as "disallow
everything", which is right for a bulk crawler hammering a site unattended.
This tool fetches one page because something asked it to, so a flaky robots.txt
returning 503 should not silently make a site unreadable. Unreachable robots
means allowed, and the reason is reported so the caller can see it happened.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from .config import RobotsConfig
from .guard import BlockedURL, resolve_target

# RFC 9309 says parsers must handle at least 500 KiB.
_MAX_ROBOTS_BYTES = 512_000
_MAX_ROBOTS_REDIRECTS = 3


@dataclass(slots=True)
class RobotsVerdict:
    allowed: bool
    reason: str | None = None


def robots_url_for(url: str) -> str | None:
    """The robots.txt that governs ``url``, or ``None`` if it has no host."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


async def _get_robots_text(robots_url: str, config: RobotsConfig, allow_private_ips: bool):
    """Fetch robots.txt through the guard. Returns ``(status, text)``.

    ``status`` is ``None`` when the file could not be retrieved at all.
    """
    current = robots_url
    timeout = httpx.Timeout(connect=config.timeout, read=config.timeout,
                            write=config.timeout, pool=config.timeout)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(_MAX_ROBOTS_REDIRECTS + 1):
            # Every hop re-validated and re-pinned, exactly as in web_fetch.
            target = resolve_target(current, allow_private_ips=allow_private_ips)
            response = await client.get(
                httpx.URL(current).copy_with(host=target.ip),
                headers={
                    "Host": target.host_header,
                    "User-Agent": config.user_agent,
                    "Accept": "text/plain, */*;q=0.5",
                },
                extensions={"sni_hostname": target.host},
            )

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    return response.status_code, ""
                current = str(httpx.URL(current).join(location))
                continue

            body = response.content[:_MAX_ROBOTS_BYTES]
            return response.status_code, body.decode("utf-8", errors="replace")

    return None, ""


class RobotsCache:
    """Per-host robots.txt rules, cached so one file is fetched once per host."""

    def __init__(self, config: RobotsConfig | None = None) -> None:
        self.config = config or RobotsConfig.from_env()
        # host key -> (expires_at, parser or None)
        self._entries: dict[str, tuple[float, RobotFileParser | None]] = {}

    def _key(self, robots_url: str) -> str:
        parts = urlsplit(robots_url)
        return f"{parts.scheme}://{parts.netloc.lower()}"

    def clear(self) -> None:
        self._entries.clear()

    async def _parser_for(self, robots_url: str, allow_private_ips: bool):
        key = self._key(robots_url)
        now = time.monotonic()

        entry = self._entries.get(key)
        if entry is not None and entry[0] > now:
            return entry[1]

        parser: RobotFileParser | None = None
        try:
            status, text = await _get_robots_text(robots_url, self.config, allow_private_ips)
        except (httpx.HTTPError, BlockedURL):
            status, text = None, ""

        # 2xx: parse it. Anything else (missing, forbidden, server error,
        # unreachable) means "no rules we can honour" — see module docstring.
        if status is not None and 200 <= status < 300:
            parser = RobotFileParser()
            parser.parse(text.splitlines())

        self._entries[key] = (now + self.config.ttl, parser)
        return parser

    async def check(self, url: str, *, allow_private_ips: bool = False) -> RobotsVerdict:
        if not self.config.enabled:
            return RobotsVerdict(True)

        robots_url = robots_url_for(url)
        if robots_url is None:
            return RobotsVerdict(True)

        try:
            parser = await self._parser_for(robots_url, allow_private_ips)
        except Exception:
            # Never let a robots problem break a fetch.
            return RobotsVerdict(True, "robots.txt could not be evaluated")

        if parser is None:
            return RobotsVerdict(True, "no usable robots.txt")

        if parser.can_fetch(self.config.user_agent_token, url):
            return RobotsVerdict(True)

        return RobotsVerdict(
            False,
            f"robots.txt at {robots_url} disallows {self.config.user_agent_token}",
        )
