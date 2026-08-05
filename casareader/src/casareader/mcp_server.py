"""MCP front end — agents and IDEs read Office documents as a tool.

Run over stdio for Claude Code / Claude Desktop / Cursor::

    python -m casareader.mcp_server

Or over HTTP for a remote client::

    python -m casareader.mcp_server --transport streamable-http
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="casareader",
    version="0.1.0",
    instructions=(
        "Self-hosted Office-document reader, no API keys. Use office_read to "
        "read a Word (.docx), PowerPoint (.pptx), or Excel (.xlsx) file into "
        "markdown plus plain text. The format is auto-detected. Prefer a local "
        "file_path when the file is on disk; use file_base64 for small files."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="office_read",
    description=(
        "Read a Microsoft Office document — Word (.docx), PowerPoint (.pptx), "
        "or Excel (.xlsx) — into clean, formatted text. The format is "
        "auto-detected. Provide one source: file_path, file_url (if enabled), "
        "or file_base64. Returns markdown that preserves structure (headings/"
        "lists for Word, per-slide text + notes for PowerPoint, one table per "
        "sheet for Excel) plus the plain text. Legacy .doc/.xls/.ppt are not "
        "supported."
    ),
)
async def office_read_tool(
    file_path: str | None = None,
    file_url: str | None = None,
    file_base64: str | None = None,
    filename: str | None = None,
) -> dict:
    """Read a Word/PowerPoint/Excel file into markdown + text.

    Args:
        file_path: Local path to a .docx/.pptx/.xlsx file.
        file_url: http(s) URL of an Office file (if URL fetch is enabled).
        file_base64: Base64-encoded document bytes.
        filename: Original filename — a detection hint for base64/URL input.
    """
    return await _toolset.read(
        file_path=file_path,
        file_url=file_url,
        file_base64=file_base64,
        filename=filename,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="CasaReader MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="MCP transport to serve on (default: stdio).",
    )
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
