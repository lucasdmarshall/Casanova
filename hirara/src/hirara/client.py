"""The Hirara Python client — call the hub's tools like functions.

    import hirara
    hirara.configure("http://localhost:8080", token="...")   # or env HIRARA_HUB_URL
    print(hirara.web_search("rust borrow checker", max_results=5))
    print(hirara.office_read(path="deck.pptx")["markdown"])

Or with an explicit client::

    from hirara import Client
    hub = Client("http://localhost:8080")
    hub.pdf_read(path="report.pdf")

The client is thin: it talks to a running hub over HTTP. When you pass a local
``path=``, the client reads the file and sends it as base64 — so it works even
when the hub has no access to your filesystem (the default for a networked hub).
"""

from __future__ import annotations

import base64 as _b64
import os

import httpx

DEFAULT_URL = "http://localhost:8080"


class HiraraError(RuntimeError):
    """Transport-level failure: the hub is unreachable or returned junk."""


class HiraraToolError(RuntimeError):
    """A tool ran but reported an error (e.g. blocked URL, bad input)."""

    def __init__(self, tool: str, error: str, response: dict) -> None:
        super().__init__(f"{tool}: {error}")
        self.tool = tool
        self.error = error
        self.response = response


def _encode_file(path: str) -> str:
    with open(os.path.expanduser(path), "rb") as fh:
        return _b64.b64encode(fh.read()).decode("ascii")


class Client:
    """A connection to a Hirara hub."""

    def __init__(
        self,
        url: str | None = None,
        *,
        token: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.url = (url or os.getenv("HIRARA_HUB_URL") or DEFAULT_URL).rstrip("/")
        self.token = token if token is not None else os.getenv("HIRARA_HUB_TOKEN")
        self.timeout = timeout
        self._client: httpx.Client | None = None

    # allow dependency injection in tests
    def _http(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return httpx.Client(base_url=self.url, headers=headers, timeout=self.timeout)

    # --- low level ---

    def call(self, name: str, arguments: dict | None = None, *, raise_on_error: bool = True) -> dict:
        """Invoke a tool by name with a raw arguments dict."""
        client = self._http()
        try:
            resp = client.post("/call", json={"name": name, "arguments": arguments or {}})
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise HiraraError("unauthorized — set the hub token (HIRARA_HUB_TOKEN)") from exc
            raise HiraraError(f"hub returned HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise HiraraError(f"could not reach hub at {self.url}: {exc}") from exc
        except ValueError as exc:
            raise HiraraError("hub returned a non-JSON response") from exc
        finally:
            if self._client is None:
                client.close()

        if raise_on_error and isinstance(data, dict) and data.get("error"):
            raise HiraraToolError(name, data["error"], data)
        return data

    def tools(self) -> list[dict]:
        """The aggregated tool schemas from every reachable backend."""
        return self._get("/schemas").get("tools", [])

    def health(self) -> dict:
        return self._get("/health")

    def _get(self, path: str) -> dict:
        client = self._http()
        try:
            resp = client.get(path)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise HiraraError(f"could not reach hub at {self.url}: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

    # --- file helper ---

    def _source(self, prefix: str, path, url, base64) -> dict:
        given = [x for x in (path, url, base64) if x]
        if len(given) != 1:
            raise ValueError("provide exactly one of path=, url=, or base64=")
        if path:
            return {f"{prefix}_base64": _encode_file(path)}
        if url:
            return {f"{prefix}_url": url}
        return {f"{prefix}_base64": base64}

    # --- typed tools ---

    def web_search(self, query: str, *, max_results: int | None = None, **extra) -> dict:
        args = {"query": query, **extra}
        if max_results is not None:
            args["max_results"] = max_results
        return self.call("web_search", args)

    def web_fetch(self, url: str, *, max_chars: int | None = None, **extra) -> dict:
        args = {"url": url, **extra}
        if max_chars is not None:
            args["max_chars"] = max_chars
        return self.call("web_fetch", args)

    def pdf_read(self, *, path=None, url=None, base64=None, **extra) -> dict:
        return self.call("pdf_read", {**self._source("pdf", path, url, base64), **extra})

    def pdf_info(self, *, path=None, url=None, base64=None, **extra) -> dict:
        return self.call("pdf_info", {**self._source("pdf", path, url, base64), **extra})

    def pdf_create(self, content: str, *, format: str = "markdown", **extra) -> dict:
        return self.call("pdf_create", {"content": content, "format": format, **extra})

    def execute_code(self, language: str, code: str, **extra) -> dict:
        return self.call("execute_code", {"language": language, "code": code, **extra})

    def ocr_read(self, *, path=None, url=None, base64=None, **extra) -> dict:
        return self.call("ocr_read", {**self._source("file", path, url, base64), **extra})

    def form_extract(self, *, path=None, url=None, base64=None, **extra) -> dict:
        return self.call("form_extract", {**self._source("file", path, url, base64), **extra})

    def office_read(self, *, path=None, url=None, base64=None, **extra) -> dict:
        args = {**self._source("file", path, url, base64), **extra}
        if path and "filename" not in args:
            args["filename"] = os.path.basename(path)
        return self.call("office_read", args)


# --- module-level convenience: `import hirara; hirara.web_search(...)` ---

_default: Client | None = None


def configure(url: str | None = None, *, token: str | None = None, timeout: float = 120.0) -> Client:
    """Set the default hub the module-level functions talk to."""
    global _default
    _default = Client(url, token=token, timeout=timeout)
    return _default


def _get_default() -> Client:
    global _default
    if _default is None:
        _default = Client()
    return _default


def _delegate(name):
    def method(*args, **kwargs):
        return getattr(_get_default(), name)(*args, **kwargs)

    method.__name__ = name
    return method


web_search = _delegate("web_search")
web_fetch = _delegate("web_fetch")
pdf_read = _delegate("pdf_read")
pdf_info = _delegate("pdf_info")
pdf_create = _delegate("pdf_create")
execute_code = _delegate("execute_code")
ocr_read = _delegate("ocr_read")
form_extract = _delegate("form_extract")
office_read = _delegate("office_read")
call = _delegate("call")
tools = _delegate("tools")
health = _delegate("health")


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
