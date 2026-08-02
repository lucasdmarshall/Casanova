"""Per-session call budgets."""

from __future__ import annotations

import pytest

from web_tools.budget import UsageBudget
from web_tools.cache import Cache
from web_tools.config import (
    BudgetConfig,
    CacheConfig,
    FetchConfig,
    ProvenanceConfig,
    RobotsConfig,
    SearchConfig,
)
from web_tools.search import SearchResult
from web_tools.tools import Toolset


# --- the counter itself ----------------------------------------------------

def test_zero_limit_means_unlimited():
    budget = UsageBudget()
    for _ in range(100):
        budget.consume("s1", "web_search")
    assert budget.check("s1", "web_search", 0) is None


def test_limit_refuses_once_exhausted():
    budget = UsageBudget()
    assert budget.check("s1", "web_search", 2) is None
    budget.consume("s1", "web_search")
    assert budget.check("s1", "web_search", 2) is None
    budget.consume("s1", "web_search")

    refusal = budget.check("s1", "web_search", 2)
    assert refusal is not None
    assert "2/2" in refusal


def test_tools_have_separate_budgets():
    budget = UsageBudget()
    budget.consume("s1", "web_search", 5)
    assert budget.check("s1", "web_fetch", 2) is None


def test_sessions_have_separate_budgets():
    budget = UsageBudget()
    budget.consume("s1", "web_search", 5)
    assert budget.check("s2", "web_search", 2) is None


def test_no_session_is_never_limited():
    """Without a session there is nothing to attribute usage to."""
    budget = UsageBudget()
    assert budget.check(None, "web_search", 1) is None
    assert budget.consume(None, "web_search") == 0


def test_expired_session_resets():
    budget = UsageBudget(ttl=0)
    budget.consume("s1", "web_search", 10)
    assert budget.check("s1", "web_search", 1) is None


def test_check_does_not_consume():
    budget = UsageBudget()
    for _ in range(5):
        budget.check("s1", "web_search", 1)
    assert budget.used("s1", "web_search") == 0


def test_reset_clears_a_session():
    budget = UsageBudget()
    budget.consume("s1", "web_search", 3)
    assert budget.reset("s1") is True
    assert budget.used("s1", "web_search") == 0


# --- enforcement through the toolset ---------------------------------------

def build(tmp_path, **budget_kwargs):
    cache_config = CacheConfig(path=str(tmp_path / "c.db"))
    return Toolset(
        fetch_config=FetchConfig(),
        search_config=SearchConfig(),
        cache_config=cache_config,
        cache=Cache(cache_config.path),
        provenance_config=ProvenanceConfig(policy="off"),
        robots_config=RobotsConfig(enabled=False),
        budget_config=BudgetConfig(**budget_kwargs),
    )


def stub_search(monkeypatch, counter):
    from web_tools import tools as tools_module

    async def fake_search(query, **kwargs):
        counter.append(query)
        return [SearchResult(title="T", url=f"https://x.example/{len(counter)}", snippet="s")]

    monkeypatch.setattr(tools_module, "web_search", fake_search)


async def test_search_budget_is_enforced(tmp_path, monkeypatch):
    calls: list[str] = []
    stub_search(monkeypatch, calls)
    toolset = build(tmp_path, max_searches=2)

    assert (await toolset.search("q1", session_id="s1"))["error"] is None
    assert (await toolset.search("q2", session_id="s1"))["error"] is None

    third = await toolset.search("q3", session_id="s1")
    assert "budget exhausted" in third["error"]
    assert third["results"] == []
    assert len(calls) == 2  # the third never reached the backend


async def test_cached_search_does_not_consume_budget(tmp_path, monkeypatch):
    """A cache hit costs nothing externally, so it must not burn budget."""
    calls: list[str] = []
    stub_search(monkeypatch, calls)
    toolset = build(tmp_path, max_searches=1)

    first = await toolset.search("same", session_id="s1")
    assert first["cached"] is False

    # Same query again: served from cache, and still allowed despite a limit of 1.
    for _ in range(5):
        repeat = await toolset.search("same", session_id="s1")
        assert repeat["cached"] is True
        assert repeat["error"] is None

    assert len(calls) == 1


async def test_normalized_queries_share_the_cache_entry(tmp_path, monkeypatch):
    calls: list[str] = []
    stub_search(monkeypatch, calls)
    toolset = build(tmp_path)

    await toolset.search("bitcoin price", session_id="s1")
    second = await toolset.search("  Bitcoin   PRICE?  ", session_id="s1")

    assert second["cached"] is True
    assert len(calls) == 1


async def test_budget_is_per_session(tmp_path, monkeypatch):
    calls: list[str] = []
    stub_search(monkeypatch, calls)
    toolset = build(tmp_path, max_searches=1)

    await toolset.search("q1", session_id="s1")
    assert "budget exhausted" in (await toolset.search("q2", session_id="s1"))["error"]
    # A different conversation gets its own allowance.
    assert (await toolset.search("q3", session_id="s2"))["error"] is None


async def test_unlimited_by_default(tmp_path, monkeypatch):
    calls: list[str] = []
    stub_search(monkeypatch, calls)
    toolset = build(tmp_path)

    for i in range(10):
        assert (await toolset.search(f"q{i}", session_id="s1"))["error"] is None
    assert len(calls) == 10


async def test_fetch_budget_is_enforced(tmp_path, monkeypatch):
    from web_tools import tools as tools_module
    from web_tools.fetch import FetchResult

    calls: list[str] = []

    async def fake_fetch(url, *, max_chars=None, config=None):
        calls.append(url)
        return FetchResult(
            url=url, final_url=url, status=200, content_type="text/html",
            title="T", content="body", truncated=False,
            bytes_downloaded=4, elapsed_ms=1,
        )

    monkeypatch.setattr(tools_module, "web_fetch", fake_fetch)
    toolset = build(tmp_path, max_fetches=1)

    assert (await toolset.fetch("https://a.example/", session_id="s1"))["error"] is None
    second = await toolset.fetch("https://b.example/", session_id="s1")
    assert "budget exhausted" in second["error"]
    assert len(calls) == 1
