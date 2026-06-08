"""Slice 1.2 — the GraphQL hash-cache (self-hashed, TTL-bounded) (PRD §8.1).

GraphQL has no ETag, so identical board reads inside a short window are coalesced
by hashing ``(query, variables)`` ourselves. These tests pin the keying (order-
independent), the TTL expiry, and the FIFO size cap.
"""

from __future__ import annotations

from app.github.hash_cache import HashCache, hash_query


def test_key_is_order_independent() -> None:
    """The same variables in a different dict order hash to the same key."""
    a = hash_query("Q", {"owner": "o", "name": "n"})
    b = hash_query("Q", {"name": "n", "owner": "o"})
    assert a == b


def test_key_changes_with_query_or_vars() -> None:
    """A different query or variable value yields a different key."""
    base = hash_query("Q", {"x": 1})
    assert hash_query("Q2", {"x": 1}) != base
    assert hash_query("Q", {"x": 2}) != base


def test_get_returns_put_value() -> None:
    cache: HashCache[str] = HashCache()
    cache.put("Q", {"x": 1}, "VALUE")
    assert cache.get("Q", {"x": 1}) == "VALUE"
    assert cache.get("Q", {"x": 2}) is None  # miss on different vars


def test_ttl_expiry_is_a_miss() -> None:
    """An entry past its TTL is evicted and reported as a miss."""
    clock = {"t": 0.0}

    cache: HashCache[str] = HashCache(ttl_seconds=10.0, time_source=lambda: clock["t"])
    cache.put("Q", {}, "V")
    clock["t"] = 5.0
    assert cache.get("Q", {}) == "V"  # still fresh
    clock["t"] = 10.0
    assert cache.get("Q", {}) is None  # expired → miss
    assert len(cache) == 0  # evicted on access


def test_fifo_size_cap_evicts_oldest() -> None:
    """The FIFO cap evicts the coldest key when exceeded."""
    cache: HashCache[int] = HashCache(max_entries=2)
    cache.put("Q", {"i": 1}, 1)
    cache.put("Q", {"i": 2}, 2)
    cache.put("Q", {"i": 3}, 3)  # evicts {"i": 1}
    assert cache.get("Q", {"i": 1}) is None
    assert cache.get("Q", {"i": 2}) == 2
    assert cache.get("Q", {"i": 3}) == 3


def test_invalidate_and_clear() -> None:
    cache: HashCache[int] = HashCache()
    cache.put("Q", {"i": 1}, 1)
    cache.invalidate("Q", {"i": 1})
    assert cache.get("Q", {"i": 1}) is None
    cache.put("Q", {"i": 2}, 2)
    cache.clear()
    assert len(cache) == 0
