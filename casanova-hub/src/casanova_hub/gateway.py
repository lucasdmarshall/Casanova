"""The aggregating gateway: fan out to backends, present one surface.

Holds no tool dependencies — it only speaks HTTP to the backend services. The
httpx client is injectable so the tests can drive it against mock backends.
"""

from __future__ import annotations

import logging

import httpx

from .config import HubConfig
from .registry import TOOLS, services

log = logging.getLogger(__name__)


class Gateway:
    def __init__(self, config: HubConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._client = client  # injected in tests; else made per-call

    def _aclient(self, timeout: float) -> tuple[httpx.AsyncClient, bool]:
        """Return (client, should_close)."""
        if self._client is not None:
            return self._client, False
        return httpx.AsyncClient(timeout=timeout), True

    def _url(self, service: str, path: str) -> str:
        base = self.config.service_urls.get(service, f"http://{service}")
        return f"{base}{path}"

    async def schemas(self) -> dict:
        """Aggregate every reachable backend's tool definitions into one array.

        Tools whose backend is down are simply absent — the gateway never
        advertises a tool it cannot actually route to.
        """
        client, close = self._aclient(self.config.probe_timeout)
        tools: list[dict] = []
        unavailable: list[str] = []
        try:
            for service in services():
                url = self._url(service, "/schemas")
                try:
                    resp = await client.get(url, timeout=self.config.probe_timeout)
                    resp.raise_for_status()
                    payload = resp.json()
                    tools.extend(payload.get("tools", []))
                except Exception as exc:  # noqa: BLE001 — a down backend is expected
                    log.info("schemas: %s unavailable (%s)", service, exc)
                    unavailable.append(service)
        finally:
            if close:
                await client.aclose()
        return {"tools": tools, "unavailable": unavailable}

    async def health(self) -> dict:
        client, close = self._aclient(self.config.probe_timeout)
        status: dict[str, str] = {}
        try:
            for service in services():
                url = self._url(service, "/health")
                try:
                    resp = await client.get(url, timeout=self.config.probe_timeout)
                    status[service] = "up" if resp.status_code == 200 else f"http {resp.status_code}"
                except Exception:  # noqa: BLE001
                    status[service] = "down"
        finally:
            if close:
                await client.aclose()
        up = sum(1 for v in status.values() if v == "up")
        return {
            "status": "ok",
            "version": "0.1.0",
            "auth": "enabled" if self.config.auth_enabled else "disabled",
            "services": status,
            "services_up": up,
            "services_total": len(status),
        }

    async def call(self, name: str, arguments: dict) -> dict:
        """Forward a tool call to its backend and return the backend's JSON.

        A missing tool or an unreachable backend comes back as an error body
        (not an exception), so the caller — an agent loop — gets something to
        reason about, consistent with how every tool behaves.
        """
        route = TOOLS.get(name)
        if route is None:
            return {"error": f"unknown tool: {name}", "tool": name}
        url = self._url(route.service, route.path)
        client, close = self._aclient(self.config.timeout)
        try:
            resp = await client.post(url, json=arguments or {}, timeout=self.config.timeout)
            if resp.status_code >= 500:
                return {
                    "error": f"backend {route.service} error (HTTP {resp.status_code})",
                    "tool": name,
                }
            return resp.json()
        except httpx.HTTPError as exc:
            return {
                "error": f"tool '{name}' unavailable: {route.service} unreachable ({exc})",
                "tool": name,
            }
        except Exception as exc:  # noqa: BLE001
            log.exception("call %s failed", name)
            return {"error": f"gateway call failed: {exc}", "tool": name}
        finally:
            if close:
                await client.aclose()


__all__ = ["Gateway"]
