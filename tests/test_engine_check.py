from __future__ import annotations

import httpx
import pytest

from hiraraweb.engine_check import format_report, probe_engine


def client_returning(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def probe(handler, engine="duckduckgo") -> dict:
    async with client_returning(handler) as client:
        return await probe_engine(client, "http://searxng:8080", engine, "q")


async def test_engine_with_results_is_ok():
    def handler(request):
        return httpx.Response(200, json={"results": [{"url": "https://a/"}, {"url": "https://b/"}]})

    result = await probe(handler)
    assert result["status"] == "ok"
    assert result["results"] == 2


async def test_engine_listed_as_unresponsive_is_reported_as_blocked():
    def handler(request):
        return httpx.Response(
            200,
            json={"results": [], "unresponsive_engines": [["duckduckgo", "CAPTCHA"]]},
        )

    result = await probe(handler)
    assert "BLOCKED" in result["status"]
    assert "CAPTCHA" in result["status"]


async def test_silent_zero_result_engine_is_flagged():
    """The failure mode that matters: no error, just nothing."""
    def handler(request):
        return httpx.Response(200, json={"results": []})

    result = await probe(handler)
    assert "no results" in result["status"]


async def test_non_json_response_names_the_settings_fix():
    def handler(request):
        return httpx.Response(200, text="<html>not json</html>")

    result = await probe(handler)
    assert "search.formats" in result["status"]


async def test_http_error_status_is_surfaced():
    def handler(request):
        return httpx.Response(403, json={})

    result = await probe(handler)
    assert result["status"] == "HTTP 403"


async def test_transport_failure_is_reported_not_raised():
    def handler(request):
        raise httpx.ConnectError("refused")

    result = await probe(handler)
    assert result["status"] == "ConnectError"
    assert result["results"] == 0


async def test_malformed_unresponsive_entries_do_not_crash():
    def handler(request):
        return httpx.Response(200, json={"results": [], "unresponsive_engines": [[], ["x"]]})

    result = await probe(handler)
    assert result["results"] == 0


async def test_degraded_engine_answering_off_topic_is_flagged():
    """The worst failure mode: healthy result count, wrong subject.

    A rate-limited engine can keep answering while matching only the first
    word of the query. Counting results calls that success.
    """
    def handler(request):
        return httpx.Response(200, json={"results": [
            {"url": "https://en.wikipedia.org/wiki/Server", "title": "Server (computing)",
             "content": "A server is a piece of computer hardware."},
        ]})

    async with client_returning(handler) as client:
        result = await probe_engine(
            client, "http://searxng:8080", "bing", "server-side request forgery", "forgery"
        )
    assert result["status"].startswith("DEGRADED")
    assert "forgery" in result["status"]


async def test_relevant_results_are_not_flagged_as_degraded():
    def handler(request):
        return httpx.Response(200, json={"results": [
            {"url": "https://owasp.org/ssrf", "title": "Server Side Request Forgery Prevention",
             "content": "Cheat sheet"},
        ]})

    async with client_returning(handler) as client:
        result = await probe_engine(
            client, "http://searxng:8080", "google cse", "server-side request forgery", "forgery"
        )
    assert result["status"] == "ok"


async def test_relevance_check_also_reads_infoboxes():
    def handler(request):
        return httpx.Response(200, json={"infoboxes": [
            {"infobox": "Server-side request forgery",
             "id": "https://en.wikipedia.org/wiki/Server-side_request_forgery",
             "content": "SSRF is a vulnerability."},
        ]})

    async with client_returning(handler) as client:
        result = await probe_engine(
            client, "http://searxng:8080", "wikipedia", "server-side request forgery", "forgery"
        )
    assert result["status"] == "ok"


async def test_unknown_engine_names_are_not_probed():
    """SearXNG answers unknown engine names from its default pool.

    Probing them would report a made-up name as working, which is how a bad
    engine list gets recommended with confidence.
    """
    from hiraraweb.engine_check import run_check

    probed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/config":
            return httpx.Response(200, json={"engines": [{"name": "google cse"}]})
        probed.append(request.url.params.get("engines"))
        return httpx.Response(200, json={"results": [{"url": "https://a/"}]})

    import hiraraweb.engine_check as module

    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    module.httpx.AsyncClient = lambda *a, **k: original(*a, **{**k, "transport": transport})
    try:
        results = await run_check(
            "http://searxng:8080", ("google cse", "marginalia"), (("q", ""),), 10.0
        )
    finally:
        module.httpx.AsyncClient = original

    by_engine = {r["engine"]: r for r in results}
    assert by_engine["marginalia"]["status"] == "UNKNOWN NAME (not on this instance)"
    assert by_engine["google cse"]["status"] == "ok"
    # The unknown name must never have been sent as a query.
    assert "marginalia" not in probed


def test_unknown_engines_are_excluded_from_the_recommendation():
    report = format_report([
        {"engine": "google cse", "results": 20, "ms": 250, "status": "ok"},
        {"engine": "marginalia", "results": 0, "ms": 0,
         "status": "UNKNOWN NAME (not on this instance)"},
    ])
    assert "WT_SEARCH_ENGINES=google cse" in report
    assert "marginalia" not in report.split("Usable engines")[1]


def test_report_emits_a_copy_pasteable_env_var():
    report = format_report([
        {"engine": "mojeek", "results": 8, "ms": 300, "status": "ok"},
        {"engine": "google", "results": 0, "ms": 900, "status": "BLOCKED/ERROR (CAPTCHA)"},
    ])
    assert "WT_SEARCH_ENGINES=mojeek" in report
    assert "google" not in report.split("Usable engines")[1]


def test_report_explains_a_total_failure():
    report = format_report([{"engine": "google", "results": 0, "ms": 10, "status": "HTTP 403"}])
    assert "No engine returned results" in report
    assert "search.formats" in report
