"""Runtime configuration for the Casanova hub gateway.

Auth is opt-in: with no HUB_TOKEN set the gateway runs open (intended for a
loopback/local deployment). Set HUB_TOKEN only when you expose the gateway on a
network — then every call must carry ``Authorization: Bearer <token>``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .registry import DEFAULT_PORTS


def _resolve_service_urls() -> dict[str, str]:
    """Base URL per backend service — HUB_<SERVICE>_URL, else localhost:<port>."""
    urls: dict[str, str] = {}
    for name, port in DEFAULT_PORTS.items():
        env = f"HUB_{name.upper()}_URL"
        urls[name] = os.getenv(env, f"http://localhost:{port}").rstrip("/")
    return urls


@dataclass(frozen=True)
class HubConfig:
    """Gateway knobs."""

    # Bearer token required on calls. None (unset) = no auth = loopback only.
    token: str | None = None

    # Per-request timeout when forwarding to a backend.
    timeout: float = 120.0

    # Short timeout for /health and /schemas probes so one slow backend does not
    # stall the whole aggregate.
    probe_timeout: float = 5.0

    service_urls: dict[str, str] = field(default_factory=_resolve_service_urls)

    @classmethod
    def from_env(cls) -> "HubConfig":
        token = os.getenv("HUB_TOKEN", "").strip() or None
        timeout = float(os.getenv("HUB_TIMEOUT", "120"))
        probe = float(os.getenv("HUB_PROBE_TIMEOUT", "5"))
        return cls(
            token=token,
            timeout=timeout,
            probe_timeout=probe,
            service_urls=_resolve_service_urls(),
        )

    @property
    def auth_enabled(self) -> bool:
        return self.token is not None


__all__ = ["HubConfig"]
