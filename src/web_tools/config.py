"""Runtime configuration for the fetch/search tools.

Everything is overridable by environment variable so the same image can run
with tighter limits in production than on a laptop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if not raw:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class SearchConfig:
    # Base URL of the self-hosted SearXNG instance. On the compose network
    # this is the service name, not localhost.
    searxng_url: str = "http://searxng:8080"

    timeout: float = 15.0
    max_results: int = 5

    # Engines to ask SearXNG for. Measured, not assumed.
    #
    # Two traps live here, both of which fail silently:
    #
    # 1. An unrecognised engine name does not raise — SearXNG falls back to
    #    its default engine set, so a typo looks like a working engine.
    #    The name is "google cse", with a space; plain "google" does not
    #    exist on a stock image.
    # 2. A rate-limited engine can still answer, just badly. From a datacenter
    #    IP, Bing returned results matching only the first word of the query
    #    ("server" for "server-side request forgery"), and those outranked
    #    good results when merged. Degraded engines are worse than blocked
    #    ones, because nothing reports an error.
    #
    # Run `python -m web_tools.engine_check` on your own host and set
    # WT_SEARCH_ENGINES from its output rather than trusting this list.
    engines: tuple[str, ...] = (
        "google cse",
        "duckduckgo web",
        "yandex",
        "mwmbl",
        "wikipedia",
    )

    language: str = "en"

    # Results scoring below this are dropped, 0.0-1.0. Default 0 = never drop,
    # only reorder. Raise it only if you have measured that your engine mix
    # returns genuine noise; a floor cannot tell "irrelevant" from "relevant
    # but phrased differently".
    relevance_floor: float = 0.0

    @classmethod
    def from_env(cls) -> "SearchConfig":
        return cls(
            searxng_url=os.getenv("WT_SEARXNG_URL", cls.searxng_url).rstrip("/"),
            timeout=_env_float("WT_SEARCH_TIMEOUT", cls.timeout),
            max_results=_env_int("WT_SEARCH_MAX_RESULTS", cls.max_results),
            engines=_env_list("WT_SEARCH_ENGINES", cls.engines),
            language=os.getenv("WT_SEARCH_LANGUAGE", cls.language),
            relevance_floor=_env_float("WT_RELEVANCE_FLOOR", cls.relevance_floor),
        )


@dataclass(frozen=True)
class BudgetConfig:
    """Per-session call caps — the ``max_uses`` equivalent.

    Both default to 0 (unlimited) so the library never caps anything by
    surprise. The shipped docker-compose sets real values: a deployment wants
    runaway protection, a library import does not.
    """

    max_searches: int = 0
    max_fetches: int = 0
    ttl: int = 3600

    @classmethod
    def from_env(cls) -> "BudgetConfig":
        return cls(
            max_searches=_env_int("WT_MAX_SEARCHES_PER_SESSION", cls.max_searches),
            max_fetches=_env_int("WT_MAX_FETCHES_PER_SESSION", cls.max_fetches),
            ttl=_env_int("WT_BUDGET_TTL", cls.ttl),
        )


@dataclass(frozen=True)
class RobotsConfig:
    """robots.txt handling.

    On by default. Note the nuance: robots.txt governs *crawlers*, and this
    tool fetches one page because a caller asked for it — closer to a browser
    than a spider. Plenty of operators would say it does not apply. Honouring
    it is the polite default and costs one cached request per host; set
    WT_RESPECT_ROBOTS=false if your use case genuinely does not warrant it.
    """

    enabled: bool = True
    ttl: int = 86400          # one robots.txt fetch per host per day
    timeout: float = 10.0

    # Matched against User-agent lines in robots.txt. Short and specific:
    # this is the name a site operator would write to address this tool.
    user_agent_token: str = "web-tools"

    user_agent: str = (
        "Mozilla/5.0 (compatible; web-tools/0.1; +https://github.com/lucasdmarshall/web_search)"
    )

    @classmethod
    def from_env(cls) -> "RobotsConfig":
        return cls(
            enabled=_env_bool("WT_RESPECT_ROBOTS", cls.enabled),
            ttl=_env_int("WT_ROBOTS_TTL", cls.ttl),
            timeout=_env_float("WT_ROBOTS_TIMEOUT", cls.timeout),
            user_agent_token=os.getenv("WT_ROBOTS_UA_TOKEN", cls.user_agent_token),
            user_agent=os.getenv("WT_USER_AGENT", cls.user_agent),
        )


@dataclass(frozen=True)
class ProvenanceConfig:
    """Controls whether a URL must be traceable to a trusted source.

    This is an *exfiltration* control, not an SSRF one. The guard stops the
    fetcher reaching your network; this stops it carrying data out to an
    attacker-chosen public address on the instruction of an injected page.
    """

    # strict — unknown URLs are refused (recommended)
    # warn   — unknown URLs are fetched, and the result is flagged
    # off    — no provenance checking at all
    policy: str = "strict"

    ttl: int = 3600
    max_urls_per_session: int = 2000

    @classmethod
    def from_env(cls) -> "ProvenanceConfig":
        policy = os.getenv("WT_FETCH_URL_POLICY", cls.policy).strip().lower()
        if policy not in {"strict", "warn", "off"}:
            policy = cls.policy
        return cls(
            policy=policy,
            ttl=_env_int("WT_URL_TTL", cls.ttl),
            max_urls_per_session=_env_int("WT_MAX_URLS_PER_SESSION", cls.max_urls_per_session),
        )


@dataclass(frozen=True)
class CacheConfig:
    path: str = "./cache.db"
    search_ttl: int = 3600         # 1 hour
    fetch_ttl: int = 86400         # 24 hours
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "CacheConfig":
        return cls(
            path=os.getenv("WT_CACHE_PATH", cls.path),
            search_ttl=_env_int("WT_CACHE_SEARCH_TTL", cls.search_ttl),
            fetch_ttl=_env_int("WT_CACHE_FETCH_TTL", cls.fetch_ttl),
            enabled=_env_bool("WT_CACHE_ENABLED", cls.enabled),
        )


@dataclass(frozen=True)
class FetchConfig:
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    total_timeout: float = 30.0

    # Cap on *decoded* body bytes. Enforced while streaming, so a gzip bomb
    # is aborted mid-download rather than after it has filled memory.
    max_bytes: int = 5 * 1024 * 1024
    max_redirects: int = 5

    # Cap on extracted text handed back to the model.
    max_chars: int = 50_000

    user_agent: str = (
        "Mozilla/5.0 (compatible; web-tools/0.1; +https://github.com/lucasdmarshall/web_search)"
    )

    # DANGEROUS. Disables the SSRF perimeter so tests can hit 127.0.0.1.
    # Never enable this on a process that accepts untrusted URLs.
    allow_private_ips: bool = False

    @classmethod
    def from_env(cls) -> "FetchConfig":
        return cls(
            connect_timeout=_env_float("WT_CONNECT_TIMEOUT", cls.connect_timeout),
            read_timeout=_env_float("WT_READ_TIMEOUT", cls.read_timeout),
            total_timeout=_env_float("WT_TOTAL_TIMEOUT", cls.total_timeout),
            max_bytes=_env_int("WT_MAX_BYTES", cls.max_bytes),
            max_redirects=_env_int("WT_MAX_REDIRECTS", cls.max_redirects),
            max_chars=_env_int("WT_MAX_CHARS", cls.max_chars),
            user_agent=os.getenv("WT_USER_AGENT", cls.user_agent),
            allow_private_ips=_env_bool("WT_ALLOW_PRIVATE_IPS", cls.allow_private_ips),
        )
