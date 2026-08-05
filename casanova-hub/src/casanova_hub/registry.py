"""The tool registry — which backend service serves which tool.

A tool names a *service*; the service's base URL is resolved from config (env),
so the same registry works whether the backends are localhost processes or
compose service names. The gateway never imports a tool's heavy dependencies —
it only knows where to forward.
"""

from __future__ import annotations

from dataclasses import dataclass

# Default loopback ports for each backend service (matches each package's compose).
DEFAULT_PORTS: dict[str, int] = {
    "websearch": 8000,
    "transcriptanova": 8100,
    "casanovapdf": 8200,
    "casanovacode": 8300,
    "casaocr": 8400,
    "casareader": 8500,
}


@dataclass(frozen=True)
class ToolRoute:
    """Where a tool call is forwarded, and its /schemas source."""

    tool: str
    service: str
    path: str
    experimental: bool = False


# tool name -> route. Multiple tools can share one service (it exposes them all
# via its own /schemas), which is why schema aggregation is per *service*.
TOOLS: dict[str, ToolRoute] = {
    "web_search": ToolRoute("web_search", "websearch", "/web_search"),
    "web_fetch": ToolRoute("web_fetch", "websearch", "/web_fetch"),
    "transcribe": ToolRoute("transcribe", "transcriptanova", "/transcribe", experimental=True),
    "pdf_read": ToolRoute("pdf_read", "casanovapdf", "/pdf_read"),
    "pdf_info": ToolRoute("pdf_info", "casanovapdf", "/pdf_info"),
    "pdf_create": ToolRoute("pdf_create", "casanovapdf", "/pdf_create"),
    "execute_code": ToolRoute("execute_code", "casanovacode", "/execute_code"),
    "ocr_read": ToolRoute("ocr_read", "casaocr", "/ocr_read"),
    "form_extract": ToolRoute("form_extract", "casaocr", "/form_extract"),
    "office_read": ToolRoute("office_read", "casareader", "/office_read"),
}


def services() -> list[str]:
    """Unique backend service names, in a stable order."""
    seen: list[str] = []
    for route in TOOLS.values():
        if route.service not in seen:
            seen.append(route.service)
    return seen


__all__ = ["DEFAULT_PORTS", "TOOLS", "ToolRoute", "services"]
