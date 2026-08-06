"""Hirara — the Python client for the Hirara self-hosted agent tool hub.

    import hirara
    hirara.configure("http://localhost:8080")
    hirara.web_search("rust borrow checker", max_results=5)

A thin client over a running hub (see the `hirara-hub` gateway). No API keys.
"""

from .client import (
    Client,
    HiraraError,
    HiraraToolError,
    call,
    configure,
    execute_code,
    form_extract,
    health,
    ocr_read,
    office_read,
    pdf_create,
    pdf_info,
    pdf_read,
    tools,
    web_fetch,
    web_search,
)

__all__ = [
    "Client",
    "HiraraError",
    "HiraraToolError",
    "configure",
    "call",
    "tools",
    "health",
    "web_search",
    "web_fetch",
    "pdf_read",
    "pdf_info",
    "pdf_create",
    "execute_code",
    "ocr_read",
    "form_extract",
    "office_read",
]

__version__ = "0.1.0"

__banner__ = (
    "    __  __________  ___    ____  ___ \n"
    "   / / / /  _/ __ \\/   |  / __ \\/   |\n"
    "  / /_/ // // /_/ / /| | / /_/ / /| |\n"
    " / __  // // _, _/ ___ |/ _, _/ ___ |\n"
    "/_/ /_/___/_/ |_/_/  |_/_/ |_/_/  |_|"
)
