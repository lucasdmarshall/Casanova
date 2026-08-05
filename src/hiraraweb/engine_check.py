"""Find out which SearXNG engines actually work from this host.

This is the question that decides whether self-hosted search is viable on a
given box. Engines do not fail loudly — a blocked engine usually returns zero
results rather than an error, so it silently contributes nothing while still
costing latency on every query. This probes each engine on its own and reports
what came back.

    python -m hiraraweb.engine_check
    python -m hiraraweb.engine_check --engines google,bing,duckduckgo

Feed the winners back in via WT_SEARCH_ENGINES.
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx

from .config import SearchConfig

# Candidates worth probing. Google and Bing are included precisely because
# they are the ones expected to fail from a datacenter IP — better to measure
# that than assume it.
# Note "google cse" — the space is part of the name on a stock SearXNG
# image. There is no engine called plain "google", and asking for one gets
# the silent fallback rather than an error.
CANDIDATE_ENGINES = (
    "google cse",
    "duckduckgo",
    "brave",
    "mojeek",
    "wikipedia",
    "wikidata",
    "startpage",
    "qwant",
    "bing",
)

# (query, distinctive term that a relevant result should mention).
#
# Mixed shapes on purpose: encyclopaedic engines answer entity lookups and
# return nothing for how-to queries, so probing with keyword queries alone
# reports them as dead when they are merely being asked the wrong question.
#
# The second element catches the failure that counting cannot. A rate-limited
# engine may keep answering while quietly matching only the first word of the
# query — Bing returned pages about "server" for "server-side request
# forgery". That looks healthy by result count and poisons every merged
# ranking it takes part in.
DEFAULT_QUERIES = (
    ("python asyncio tutorial", "asyncio"),
    ("Server-side request forgery", "forgery"),
)


def _looks_relevant(payload: dict, term: str) -> bool:
    """True if any result mentions ``term`` in its title, snippet or URL."""
    term = term.lower()
    items = list(payload.get("results") or []) + list(payload.get("infoboxes") or [])
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        haystack = " ".join(
            str(item.get(field) or "")
            for field in ("title", "content", "url", "id", "infobox")
        ).lower()
        if term in haystack:
            return True
    return False


async def fetch_engine_names(client: httpx.AsyncClient, base_url: str) -> set[str]:
    """Names this instance actually recognises, from its /config endpoint.

    Essential, because SearXNG does not reject an unknown engine name — it
    silently falls back to the default engine set. A probe that skips this
    check reports made-up names as working, since the fallback pool answers
    on their behalf.
    """
    try:
        response = await client.get(f"{base_url}/config")
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return set()
    return {
        engine["name"]
        for engine in payload.get("engines") or []
        if isinstance(engine, dict) and engine.get("name")
    }


async def probe_engine(
    client: httpx.AsyncClient,
    base_url: str,
    engine: str,
    query: str,
    term: str = "",
) -> dict:
    """Run one query against one engine and summarise the outcome."""
    started = time.monotonic()
    try:
        response = await client.get(
            f"{base_url}/search",
            # No `categories` here. SearXNG unions `engines` with
            # `categories`, so sending both would query every general engine
            # alongside this one and every probe would report the same pooled
            # result count.
            params={"q": query, "format": "json", "engines": engine},
        )
    except httpx.HTTPError as exc:
        return {
            "engine": engine,
            "results": 0,
            "ms": int((time.monotonic() - started) * 1000),
            "status": f"{type(exc).__name__}",
        }

    elapsed = int((time.monotonic() - started) * 1000)

    if response.status_code != 200:
        return {"engine": engine, "results": 0, "ms": elapsed,
                "status": f"HTTP {response.status_code}"}

    try:
        payload = response.json()
    except ValueError:
        return {"engine": engine, "results": 0, "ms": elapsed,
                "status": "non-JSON (enable `json` in search.formats)"}

    # SearXNG reports engines that errored or timed out separately from
    # engines that simply returned nothing.
    unresponsive = {
        item[0]: (item[1] if len(item) > 1 else "unresponsive")
        for item in payload.get("unresponsive_engines") or []
        if item
    }

    # Count infoboxes too: Wikipedia and Wikidata return content only in that
    # field, so counting `results` alone reports them as dead when they work.
    count = len(payload.get("results") or []) + len(payload.get("infoboxes") or [])
    if engine in unresponsive:
        status = f"BLOCKED/ERROR ({unresponsive[engine]})"
    elif count == 0:
        status = "no results (likely rate-limited)"
    elif term and not _looks_relevant(payload, term):
        # Answering, but not with anything about the query.
        status = f"DEGRADED (no result mentions {term!r})"
    else:
        status = "ok"

    return {"engine": engine, "results": count, "ms": elapsed, "status": status}


async def run_check(
    base_url: str,
    engines: tuple[str, ...],
    queries: tuple[str, ...],
    timeout: float,
) -> list[dict]:
    results: list[dict] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        known = await fetch_engine_names(client, base_url)

        for engine in engines:
            if known and engine not in known:
                # Do not probe: the answer would come from the fallback pool
                # and look like success.
                results.append({
                    "engine": engine,
                    "results": 0,
                    "ms": 0,
                    "status": "UNKNOWN NAME (not on this instance)",
                })
                continue

            # Serially, and averaged over a couple of queries: hammering an
            # engine in parallel is the fastest way to get the answer wrong.
            runs = [
                await probe_engine(client, base_url, engine, q, term)
                for q, term in queries
            ]
            # A degraded verdict from any query wins over an ok from another:
            # an engine that mangles one query will mangle others.
            degraded = next((r for r in runs if r["status"].startswith("DEGRADED")), None)
            chosen = degraded or max(runs, key=lambda r: r["results"])
            results.append({
                "engine": engine,
                "results": sum(r["results"] for r in runs),
                "ms": sum(r["ms"] for r in runs) // len(runs),
                "status": chosen["status"],
            })
    return results


def format_report(results: list[dict]) -> str:
    lines = [f"{'engine':<14}{'results':>9}{'avg ms':>9}  status", "-" * 62]
    for row in sorted(results, key=lambda r: (-r["results"], r["ms"])):
        lines.append(
            f"{row['engine']:<14}{row['results']:>9}{row['ms']:>9}  {row['status']}"
        )

    working = [r["engine"] for r in results if r["status"] == "ok"]
    lines.append("")
    if working:
        lines.append(f"Usable engines ({len(working)}):")
        lines.append(f"  WT_SEARCH_ENGINES={','.join(working)}")
    else:
        lines.append("No engine returned results.")
        lines.append("  Check that SearXNG is reachable and `json` is in search.formats.")
        lines.append("  If it is, this host's IP is blocked by every engine tried.")
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    config = SearchConfig.from_env()
    base_url = (args.url or config.searxng_url).rstrip("/")
    engines = tuple(e.strip() for e in args.engines.split(",")) if args.engines \
        else CANDIDATE_ENGINES

    print(f"Probing {len(engines)} engines via {base_url}\n")
    results = await run_check(base_url, engines, DEFAULT_QUERIES, args.timeout)
    print(format_report(results))
    return 0 if any(r["status"] == "ok" for r in results) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="SearXNG base URL (default: WT_SEARXNG_URL)")
    parser.add_argument("--engines", help="Comma-separated engines to probe")
    parser.add_argument("--timeout", type=float, default=20.0)
    raise SystemExit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
