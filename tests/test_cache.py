from __future__ import annotations

import time

import pytest

from hiraraweb.cache import Cache, make_key


@pytest.fixture
def cache(tmp_path):
    return Cache(str(tmp_path / "cache.db"))


async def test_roundtrip(cache):
    await cache.set("k", {"a": 1}, ttl=60)
    assert await cache.get("k") == {"a": 1}


async def test_missing_key_returns_none(cache):
    assert await cache.get("nope") is None


async def test_expired_entry_is_not_served(cache):
    await cache.set("k", "v", ttl=1)
    # Write the expiry into the past rather than sleeping through it.
    cache._set_sync("k", "v", -1)
    assert await cache.get("k") is None


async def test_set_overwrites(cache):
    await cache.set("k", "first", ttl=60)
    await cache.set("k", "second", ttl=60)
    assert await cache.get("k") == "second"


async def test_zero_ttl_is_not_stored(cache):
    await cache.set("k", "v", ttl=0)
    assert await cache.get("k") is None


async def test_purge_removes_only_expired_rows(cache):
    await cache.set("live", "v", ttl=600)
    cache._set_sync("dead", "v", -1)
    assert await cache.purge_expired() == 1
    assert await cache.get("live") == "v"


async def test_disabled_cache_never_stores(tmp_path):
    disabled = Cache(str(tmp_path / "c.db"), enabled=False)
    await disabled.set("k", "v", ttl=60)
    assert await disabled.get("k") is None


def test_keys_are_stable_and_order_independent():
    assert make_key("ns", "a", 1) == make_key("ns", "a", 1)
    assert make_key("ns", {"x": 1, "y": 2}) == make_key("ns", {"y": 2, "x": 1})


def test_keys_separate_namespaces_and_arguments():
    assert make_key("search", "q") != make_key("fetch", "q")
    assert make_key("search", "a") != make_key("search", "b")
    # None and absent must not collide: filters vs. no filters.
    assert make_key("search", "q", None) != make_key("search", "q", [])
