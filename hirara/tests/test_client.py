"""Client behaviour against a mock hub (httpx MockTransport)."""

from __future__ import annotations

import base64

import httpx
import pytest

from hirara import Client, HiraraError, HiraraToolError

_last: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    _last["path"] = request.url.path
    _last["auth"] = request.headers.get("authorization")
    if request.url.path == "/call":
        import json

        body = json.loads(request.content)
        _last["name"] = body["name"]
        _last["arguments"] = body["arguments"]
        name = body["name"]
        if name == "boom":
            return httpx.Response(200, json={"error": "blocked URL", "tool": "boom"})
        if name == "web_search":
            return httpx.Response(200, json={"results": ["a", "b"], "error": None})
        return httpx.Response(200, json={"echo": body["arguments"], "error": None})
    if request.url.path == "/schemas":
        return httpx.Response(200, json={"tools": [{"name": "web_search"}], "unavailable": []})
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    return httpx.Response(404)


def _client(token: str | None = None) -> Client:
    c = Client("http://hub.local", token=token)
    c._client = httpx.Client(
        base_url="http://hub.local",
        transport=httpx.MockTransport(_handler),
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )
    return c


def test_web_search_forwards_arguments():
    c = _client()
    r = c.web_search("rust", max_results=5)
    assert r["results"] == ["a", "b"]
    assert _last["name"] == "web_search"
    assert _last["arguments"] == {"query": "rust", "max_results": 5}


def test_execute_code():
    c = _client()
    c.execute_code("python", "print(1)", stdin="x")
    assert _last["arguments"] == {"language": "python", "code": "print(1)", "stdin": "x"}


def test_pdf_read_from_path_sends_pdf_base64(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 hello")
    c = _client()
    c.pdf_read(path=str(f))
    assert _last["name"] == "pdf_read"
    assert base64.b64decode(_last["arguments"]["pdf_base64"]) == b"%PDF-1.4 hello"


def test_office_read_from_path_sends_file_base64_and_filename(tmp_path):
    f = tmp_path / "deck.pptx"
    f.write_bytes(b"PK\x03\x04zip")
    c = _client()
    c.office_read(path=str(f))
    assert "file_base64" in _last["arguments"]
    assert _last["arguments"]["filename"] == "deck.pptx"


def test_ocr_read_url_uses_file_url():
    c = _client()
    c.ocr_read(url="https://example.com/a.png", languages=["en"])
    assert _last["arguments"]["file_url"] == "https://example.com/a.png"
    assert _last["arguments"]["languages"] == ["en"]


def test_requires_exactly_one_source(tmp_path):
    c = _client()
    with pytest.raises(ValueError):
        c.pdf_read()
    with pytest.raises(ValueError):
        c.pdf_read(url="x", base64="y")


def test_tool_error_raises():
    c = _client()
    with pytest.raises(HiraraToolError) as exc:
        c.call("boom", {})
    assert exc.value.tool == "boom"
    assert "blocked URL" in exc.value.error


def test_tool_error_can_be_returned():
    c = _client()
    r = c.call("boom", {}, raise_on_error=False)
    assert r["error"] == "blocked URL"


def test_auth_header_sent():
    c = _client(token="secret")
    c.tools()
    assert _last["auth"] == "Bearer secret"


def test_unauthorized_maps_to_hiraraerror():
    def unauth(request):
        return httpx.Response(401, json={"detail": "nope"})

    c = Client("http://hub.local")
    c._client = httpx.Client(base_url="http://hub.local", transport=httpx.MockTransport(unauth))
    with pytest.raises(HiraraError) as exc:
        c.web_search("x")
    assert "unauthorized" in str(exc.value).lower()


def test_discovery():
    c = _client()
    assert c.tools() == [{"name": "web_search"}]
    assert c.health()["status"] == "ok"
