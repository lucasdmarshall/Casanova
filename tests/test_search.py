from __future__ import annotations

import pytest

from hiraraweb.search import (
    SearchError,
    SearchResult,
    _domain_matches,
    filter_results,
    parse_searxng_payload,
    web_search,
)


def result(url: str, title: str = "t", snippet: str = "s") -> SearchResult:
    return SearchResult(title=title, url=url, snippet=snippet)


class StubProvider:
    name = "stub"

    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        self.calls.append((query, max_results))
        return self.results


# --- domain matching -------------------------------------------------------

async def test_engine_allowlist_is_not_widened_by_categories():
    """`engines` and `categories` are additive in SearXNG.

    Sending both queries the named engines *plus* the whole category, which
    silently defeats WT_SEARCH_ENGINES — including re-enabling engines that
    are known to be blocked from this host.
    """
    import httpx

    from hiraraweb.config import SearchConfig
    from hiraraweb.search import SearXNGProvider

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"results": []})

    provider = SearXNGProvider(SearchConfig(engines=("mojeek", "wikipedia")))
    transport = httpx.MockTransport(handler)

    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    import hiraraweb.search as search_module

    search_module.httpx.AsyncClient = patched
    try:
        await provider.search("q", max_results=5)
    finally:
        search_module.httpx.AsyncClient = original

    assert seen.get("engines") == "mojeek,wikipedia"
    assert "categories" not in seen


def test_domain_matches_host_and_subdomains():
    assert _domain_matches("example.com", "example.com")
    assert _domain_matches("news.example.com", "example.com")
    assert _domain_matches("EXAMPLE.COM", "example.com")


def test_domain_matching_requires_a_label_boundary():
    """The bug that makes allowlists useless: suffix matching without a dot."""
    assert not _domain_matches("evil-example.com", "example.com")
    assert not _domain_matches("notexample.com", "example.com")
    assert not _domain_matches("example.com.attacker.net", "example.com")


# --- filtering -------------------------------------------------------------

def test_drops_non_http_result_urls():
    kept = filter_results([
        result("javascript:alert(1)"),
        result("file:///etc/passwd"),
        result("https://good.example/a"),
    ])
    assert [r.url for r in kept] == ["https://good.example/a"]


def test_deduplicates_urls_differing_only_by_slash_or_fragment():
    kept = filter_results([
        result("https://example.com/page"),
        result("https://example.com/page/"),
        result("https://example.com/page#section"),
    ])
    assert len(kept) == 1


def test_allowed_domains_excludes_everything_else():
    kept = filter_results(
        [result("https://example.com/a"), result("https://other.com/b")],
        allowed_domains=["example.com"],
    )
    assert [r.url for r in kept] == ["https://example.com/a"]


def test_blocked_domains_wins_over_presence():
    kept = filter_results(
        [result("https://spam.com/a"), result("https://ok.com/b")],
        blocked_domains=["spam.com"],
    )
    assert [r.url for r in kept] == ["https://ok.com/b"]


# --- payload parsing -------------------------------------------------------

def test_parses_a_searxng_payload():
    payload = {
        "results": [
            {
                "url": "https://example.com/a",
                "title": "  A  ",
                "content": "  snippet  ",
                "publishedDate": "2026-01-01",
                "engine": "mojeek",
            }
        ]
    }
    (parsed,) = parse_searxng_payload(payload)
    assert parsed.url == "https://example.com/a"
    assert parsed.title == "A"
    assert parsed.snippet == "snippet"
    assert parsed.page_age == "2026-01-01"
    assert parsed.engine == "mojeek"


def test_infoboxes_are_parsed_and_lead():
    """Wikipedia/Wikidata populate `infoboxes` and never `results`.

    Reading only `results` silently drops them, which looks identical to the
    engine being blocked.
    """
    payload = {
        "infoboxes": [
            {
                "infobox": "Server-side request forgery",
                "id": "https://en.wikipedia.org/wiki/Server-side_request_forgery",
                "content": "SSRF is a computer security vulnerability.",
                "engine": "wikipedia",
            }
        ],
        "results": [{"url": "https://other.example/", "title": "Other"}],
    }
    parsed = parse_searxng_payload(payload)
    assert len(parsed) == 2
    assert parsed[0].url == "https://en.wikipedia.org/wiki/Server-side_request_forgery"
    assert parsed[0].title == "Server-side request forgery"
    assert parsed[0].engine == "wikipedia"


@pytest.mark.parametrize(
    "box",
    [
        {"infobox": "no id"},
        {"id": "not-a-url", "infobox": "x"},
        {"id": "javascript:alert(1)", "infobox": "x"},
        "not a dict",
    ],
)
def test_malformed_infoboxes_are_skipped(box):
    assert parse_searxng_payload({"infoboxes": [box]}) == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": None},
        {"infoboxes": None},
        {"results": []},
        {"results": ["not a dict"]},
        {"results": [{"title": "no url"}]},
        {"results": [{"url": ""}]},
    ],
)
def test_parsing_tolerates_missing_and_malformed_fields(payload):
    assert parse_searxng_payload(payload) == []


def test_parsing_defaults_absent_optional_fields():
    (parsed,) = parse_searxng_payload({"results": [{"url": "https://a.example/"}]})
    assert parsed.title == ""
    assert parsed.snippet == ""
    assert parsed.page_age is None


# --- web_search ------------------------------------------------------------

async def test_web_search_applies_the_result_limit():
    provider = StubProvider([result(f"https://example.com/{i}") for i in range(10)])
    out = await web_search("cats", max_results=3, provider=provider)
    assert len(out) == 3


async def test_web_search_rejects_an_empty_query():
    with pytest.raises(SearchError, match="empty"):
        await web_search("   ", provider=StubProvider([]))


async def test_web_search_passes_domain_filters_through():
    provider = StubProvider([
        result("https://keep.example/a"),
        result("https://drop.example/b"),
    ])
    out = await web_search("x", provider=provider, blocked_domains=["drop.example"])
    assert [r.url for r in out] == ["https://keep.example/a"]
