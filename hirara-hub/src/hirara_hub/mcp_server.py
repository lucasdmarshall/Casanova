"""Federating MCP server — one MCP endpoint for the whole hub.

Agents connect here and see every hub tool as a first-class MCP tool. On each
call the server forwards to the tool's backend over HTTP (via the Gateway),
exactly like the /call endpoint. Tools whose backend is unreachable at startup
are still registered from the static registry, so transient backend downtime
does not drop them from the tool list; a call to a down backend returns an
error body.

    python -m hirara_hub.mcp_server
"""

from __future__ import annotations

import argparse
import asyncio

from mcp.server.mcpserver import MCPServer

from . import banner
from .config import HubConfig
from .gateway import Gateway
from .registry import TOOLS

_config = HubConfig.from_env()
_gateway = Gateway(_config)

server = MCPServer(
    name="hirara-hub",
    version="0.1.0",
    instructions=(
        "The Hirara tool hub — one endpoint for web search/fetch, code "
        "execution, PDF, OCR, form extraction, and Office-document reading. "
        "Each tool is self-hosted and key-free. Call a tool directly; the hub "
        "forwards it to the right backend."
    ),
)


def _register(route) -> None:
    """Register one hub tool as an MCP tool that forwards to its backend."""

    async def handler(arguments: dict | None = None) -> dict:
        return await _gateway.call(route.tool, arguments or {})

    handler.__name__ = route.tool
    label = "[experimental] " if route.experimental else ""
    server.tool(
        name=route.tool,
        description=f"{label}Forwarded to the {route.service} backend. "
        f"See the hub /schemas for this tool's arguments.",
    )(handler)


for _route in TOOLS.values():
    _register(_route)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hirara hub MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="MCP transport to serve on (default: stdio).",
    )
    args = parser.parse_args()
    # Banner + which backends are reachable at boot (informational only).
    sub = f"hub | MCP {args.transport}"
    try:
        health = asyncio.run(_gateway.health())
        sub += f" | backends {health['services_up']}/{health['services_total']}"
    except Exception:  # noqa: BLE001
        pass
    banner.show(sub)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
