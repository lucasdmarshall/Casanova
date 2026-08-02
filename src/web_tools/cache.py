"""TTL cache backed by SQLite.

SQLite rather than Redis so the tool stays a single self-contained process:
one fewer container, one fewer thing to secure on a public VPS. Volumes here
are tiny — an agent loop issues tens of searches a minute, not thousands.

Caching is what makes a self-hosted SearXNG survive real agent traffic. Agent
loops re-issue near-identical queries constantly, and every cache hit is one
less scrape against an engine that is deciding whether to CAPTCHA you.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_expires ON entries (expires_at);
"""


def make_key(namespace: str, *parts: Any) -> str:
    """Stable cache key. Hashed so long URLs and queries stay bounded."""
    raw = "\x00".join([namespace, *(json.dumps(p, sort_keys=True, default=str) for p in parts)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Cache:
    def __init__(self, path: str = "./cache.db", *, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled
        self._lock = asyncio.Lock()
        if enabled:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        # WAL lets reads proceed while a write is in flight, which matters
        # once several tool calls are in the air at once.
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _get_sync(self, key: str) -> Any | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM entries WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if expires_at < time.time():
            return None
        try:
            return json.loads(value)
        except ValueError:
            return None

    def _set_sync(self, key: str, value: Any, ttl: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO entries (key, value, expires_at) VALUES (?, ?, ?)",
                (key, json.dumps(value), time.time() + ttl),
            )

    def _purge_sync(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM entries WHERE expires_at < ?", (time.time(),))
            return cursor.rowcount

    async def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        return await asyncio.to_thread(self._get_sync, key)

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if not self.enabled or ttl <= 0:
            return
        # Serialised because SQLite writers block each other; without this,
        # concurrent tool calls spend their time losing lock races.
        async with self._lock:
            await asyncio.to_thread(self._set_sync, key, value, ttl)

    async def purge_expired(self) -> int:
        if not self.enabled:
            return 0
        async with self._lock:
            return await asyncio.to_thread(self._purge_sync)
