"""``web_search``: query a self-hosted SearXNG instance.

SearXNG is the only backend here by design — it is open source and runs on
your own box, which the keyed APIs (Google CSE, Brave, Serper) are not.

The tradeoff that comes with that: SearXNG works by querying public engines
from *your* IP. From a datacenter address, Google and Bing begin serving
CAPTCHAs quickly, so :class:`~hiraraweb.config.SearchConfig` defaults to the
engines that tolerate VPS traffic. Tune ``WT_SEARCH_ENGINES`` against what
your host actually gets away with.

Result URLs are treated as untrusted. They come from pages that anyone can
publish to, so they are scheme-checked here and fully re-validated by
:mod:`hiraraweb.guard` if anything later fetches them.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from .config import SearchConfig

_SAFE_SCHEMES = frozenset({"http", "https"})

_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+")

# Just enough to stop "the", "of" and friends dominating a coverage score.
# Deliberately tiny: an aggressive stopword list starts eating real query terms
# in languages this list was never built for.
_STOPWORDS = frozenset(
    """a an and are as at be by for from has how in is it of on or that the to
    what when where which who why with""".split()
)


def normalize_query(query: str) -> str:
    """Canonical form of a query, for cache keys only.

    Never sent to the search backend — engines should see exactly what the
    caller typed. This only decides whether two requests are the same request.

    Word order is preserved on purpose: "dog bites man" and "man bites dog"
    are different searches, so sorting tokens here would serve the wrong
    cached answer.
    """
    text = unicodedata.normalize("NFC", query)
    text = _WHITESPACE.sub(" ", text).strip().lower()
    # Trailing question and exclamation marks carry no search meaning.
    # Full stops are left alone — they are load-bearing in "node.js".
    return text.rstrip("?!").strip()


def relevance_score(query: str, result: "SearchResult") -> float:
    """Fraction of the query's content words that appear in a result, 0.0–1.0.

    A crude signal, and crude is the point: it costs nothing, needs no model,
    and catches the failure that actually happens — an engine that is
    rate-limited but still answering, matching one word of the query and
    returning something unrelated. Bing answered "server-side request forgery"
    with pages about servers.

    Returns 1.0 when the query has no scorable content words, so an unusual
    query never penalises every result equally.
    """
    tokens = [t for t in _TOKEN.findall(query.lower()) if len(t) > 1 and t not in _STOPWORDS]
    if not tokens:
        return 1.0

    haystack = f"{result.title} {result.snippet} {result.url}".lower()
    hits = sum(1 for token in set(tokens) if token in haystack)
    return hits / len(set(tokens))


def rank_by_relevance(query: str, results: list["SearchResult"]) -> list["SearchResult"]:
    """Reorder results so obviously-unrelated ones sink.

    Demotes rather than drops. Dropping would lose results that are relevant
    but share no literal token with the query — an "SSRF explained" page for
    the query "server-side request forgery" scores zero and is still the right
    answer. Sorting is stable, so within an equal score the backend's own
    ranking is preserved.
    """
    scored = [(relevance_score(query, r), r) for r in results]
    for score, result in scored:
        result.relevance = round(score, 3)
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [result for _, result in scored]


class SearchError(RuntimeError):
    """The search backend was unreachable or returned something unusable."""


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    page_age: str | None = None
    engine: str | None = None
    # Set by rank_by_relevance. Exposed so a caller can see *why* the order
    # is what it is, rather than having to trust it.
    relevance: float | None = None

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "page_age": self.page_age,
            "engine": self.engine,
            "relevance": self.relevance,
        }


class SearchProvider(Protocol):
    """Swap-in point for a different backend later without touching callers."""

    name: str

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]: ...


def _domain_matches(host: str, domain: str) -> bool:
    """True if ``host`` is ``domain`` or a subdomain of it.

    Suffix matching alone would let ``evil-example.com`` pass a filter for
    ``example.com``, so the boundary dot is required.
    """
    host = host.lower().rstrip(".")
    domain = domain.lower().strip().lstrip(".").rstrip(".")
    return host == domain or host.endswith("." + domain)


def filter_results(
    results: list[SearchResult],
    *,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> list[SearchResult]:
    """Drop unusable URLs, apply domain rules, and de-duplicate."""
    seen: set[str] = set()
    kept: list[SearchResult] = []

    for result in results:
        parts = urlsplit(result.url)
        if parts.scheme not in _SAFE_SCHEMES or not parts.hostname:
            continue

        host = parts.hostname
        if allowed_domains and not any(_domain_matches(host, d) for d in allowed_domains):
            continue
        if blocked_domains and any(_domain_matches(host, d) for d in blocked_domains):
            continue

        # Engines disagree about trailing slashes and fragments; collapse
        # those so the same page does not occupy three result slots.
        key = f"{parts.scheme}://{host}{parts.path.rstrip('/')}?{parts.query}"
        if key in seen:
            continue
        seen.add(key)
        kept.append(result)

    return kept


def parse_searxng_payload(payload: dict) -> list[SearchResult]:
    """Map a SearXNG JSON response onto :class:`SearchResult`.

    Engines are inconsistent about which fields they populate, so every field
    is treated as optional rather than trusted to exist.
    """
    results = []

    # Infoboxes come first. Some engines — Wikipedia and Wikidata among them —
    # return their content *only* as an infobox and never populate `results`,
    # so a parser that reads `results` alone silently discards them entirely.
    # They are also direct answers, which is why they lead.
    for box in payload.get("infoboxes") or []:
        if not isinstance(box, dict):
            continue
        url = box.get("id")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        results.append(
            SearchResult(
                title=(box.get("infobox") or "").strip(),
                url=url,
                snippet=(box.get("content") or "").strip(),
                page_age=None,
                engine=box.get("engine"),
            )
        )

    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        results.append(
            SearchResult(
                title=(item.get("title") or "").strip(),
                url=url,
                snippet=(item.get("content") or "").strip(),
                page_age=item.get("publishedDate"),
                engine=item.get("engine"),
            )
        )
    return results


class SearXNGProvider:
    """Adapter for a self-hosted SearXNG instance's JSON API.

    The instance must have ``json`` listed under ``search.formats`` in its
    ``settings.yml``; it is not enabled by default.
    """

    name = "searxng"

    def __init__(self, config: SearchConfig | None = None) -> None:
        self.config = config or SearchConfig.from_env()

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        params = {
            "q": query,
            "format": "json",
            "language": self.config.language,
            "safesearch": "0",
        }
        if self.config.engines:
            # `engines` and `categories` are additive in SearXNG, not
            # intersecting: sending both queries the named engines *plus*
            # every engine in the category, which silently defeats the
            # allowlist. Send exactly one of them.
            params["engines"] = ",".join(self.config.engines)
        else:
            params["categories"] = "general"

        url = f"{self.config.searxng_url}/search"
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            detail = f"{type(exc).__name__}: {exc}".rstrip(": ")
            raise SearchError(f"cannot reach SearXNG at {url} ({detail})") from exc

        if response.status_code == 403:
            raise SearchError(
                "SearXNG returned 403. Its limiter usually blocks API clients; "
                "set `server.limiter: false` or allowlist this caller."
            )
        if response.status_code >= 400:
            raise SearchError(f"SearXNG returned HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise SearchError(
                "SearXNG did not return JSON. Add `json` to `search.formats` "
                "in settings.yml."
            ) from exc

        # Over-fetch: de-duplication and domain filters will thin these out,
        # and asking for exactly `max_results` tends to return fewer.
        return parse_searxng_payload(payload)[: max_results * 3]


async def web_search(
    query: str,
    *,
    max_results: int | None = None,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    provider: SearchProvider | None = None,
    config: SearchConfig | None = None,
) -> list[SearchResult]:
    """Search the web and return ranked results.

    Mirrors the shape of the hosted ``web_search`` tool, minus the opaque
    ``encrypted_content`` field, which exists to power citations and has no
    self-hosted equivalent. Pair this with ``web_fetch`` if you need the text.
    """
    cfg = config or SearchConfig.from_env()
    limit = max_results if max_results is not None else cfg.max_results

    if not query.strip():
        raise SearchError("query is empty")

    backend = provider or SearXNGProvider(cfg)
    raw = await backend.search(query, max_results=limit)
    filtered = filter_results(
        raw, allowed_domains=allowed_domains, blocked_domains=blocked_domains
    )
    # Rank before truncating: a demoted result must not hold a slot that a
    # relevant one further down the list should have had.
    ranked = rank_by_relevance(query, filtered)

    floor = cfg.relevance_floor
    if floor > 0:
        kept = [r for r in ranked if (r.relevance or 0.0) >= floor]
        # Never return nothing on account of the floor — a query whose terms
        # simply do not appear literally would otherwise look like an outage.
        ranked = kept or ranked

    return ranked[:limit]
