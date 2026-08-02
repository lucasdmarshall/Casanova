"""Per-session tool-use budgets.

Mirrors the ``max_uses`` parameter on the hosted web tools. This is a
structural guardrail — it counts calls. It never inspects what the query
means, which is what separates a guardrail from a classifier: the model
decides *whether* to search, this only decides *how many times* it may.

Cached searches are not counted. The budget exists to bound load on search
engines and the cost of real outbound work; a loop re-asking a question whose
answer is already in the cache costs nothing externally, and burning budget on
it would push callers toward disabling the limit entirely.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class _Counters:
    used: dict[str, int] = field(default_factory=dict)
    touched_at: float = field(default_factory=time.monotonic)


class UsageBudget:
    """Counts tool calls per session, with the same TTL model as the registry.

    A limit of ``0`` means unlimited — the library default, so importing this
    package never silently caps anything. Deployments opt in (the shipped
    compose file does).
    """

    def __init__(self, ttl: int = 3600) -> None:
        self.ttl = ttl
        self._sessions: dict[str, _Counters] = {}
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        stale = [k for k, c in self._sessions.items() if now - c.touched_at > self.ttl]
        for key in stale:
            del self._sessions[key]

    def check(self, session_id: str | None, tool: str, limit: int) -> str | None:
        """Reason to refuse the call, or ``None`` to allow it. Does not consume."""
        if limit <= 0 or not session_id:
            return None

        with self._lock:
            self._expire(time.monotonic())
            used = self._sessions.get(session_id, _Counters()).used.get(tool, 0)

        if used < limit:
            return None
        return (
            f"{tool} budget exhausted for this session ({used}/{limit} used). "
            "Start a new session, or raise the limit."
        )

    def consume(self, session_id: str | None, tool: str, amount: int = 1) -> int:
        """Record a call. Returns the new count."""
        if not session_id:
            return 0
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            counters = self._sessions.setdefault(session_id, _Counters())
            counters.touched_at = now
            counters.used[tool] = counters.used.get(tool, 0) + amount
            return counters.used[tool]

    def used(self, session_id: str | None, tool: str) -> int:
        if not session_id:
            return 0
        with self._lock:
            counters = self._sessions.get(session_id)
            return counters.used.get(tool, 0) if counters else 0

    def reset(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None
