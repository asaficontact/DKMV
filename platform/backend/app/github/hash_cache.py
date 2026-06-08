"""A small self-hashing result cache for GraphQL board reads (PRD §8.1).

GitHub's **GraphQL** API has **no ETag / conditional-request support** (unlike the
REST API), so a poll-driven board read cannot lean on the transport to tell it
"nothing changed". The PRD's mitigation (§8.1, R-2) is to **cache results
ourselves keyed by a query+variables hash** so two identical reads inside a short
window reuse the previous response instead of spending GraphQL points again.

This module is the reusable cache primitive that backs that behavior. It is
deliberately tiny and dependency-free:

* :meth:`HashCache.key` derives a stable SHA-256 over the ``(query, variables)``
  pair (canonicalized so dict-ordering / whitespace never changes the key).
* :meth:`HashCache.get` / :meth:`HashCache.put` are TTL-bounded; an entry past
  its TTL is treated as a miss (and evicted on access).

It is shared with slice 1.3's rate-limit work (the write-queue consults the same
cache for reads to spend fewer points), so the surface is generic over the cached
value type — it caches *whatever* the caller stores under a query+variables hash,
not a GraphQL-specific shape.

This is an in-process, single-event-loop cache (no locking): the orchestrator and
the API handlers share one event loop, so reads/writes here are never concurrent
across threads. It bounds its own size with a simple FIFO cap so a long-running
process never grows it unboundedly.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: Default time-to-live for a cached board read, in seconds. Short by design: the
#: cache exists to coalesce a burst of identical polls (a manual Refresh racing
#: the next tick), not to serve stale board state for long. The orchestrator's
#: tick cadence (default 10 s, §8.2) is the natural upper bound.
DEFAULT_TTL_SECONDS = 30.0

#: Max number of distinct (query, variables) entries kept before the oldest is
#: evicted (FIFO). Bounds memory for a long-lived process; a handful of repos ×
#: a couple of paginated queries is the expected working set.
DEFAULT_MAX_ENTRIES = 256


def hash_query(query: str, variables: Mapping[str, Any] | None = None) -> str:
    """Return a stable SHA-256 hex digest over the ``(query, variables)`` pair.

    The variables mapping is JSON-serialized with **sorted keys** so two logically
    identical reads that happen to build the variables dict in a different order
    produce the *same* key (the cache must not miss on dict-ordering). The query
    string is hashed verbatim — callers pass a constant query template, so its
    whitespace is already stable.
    """
    canonical_vars = json.dumps(variables or {}, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256()
    digest.update(query.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(canonical_vars.encode("utf-8"))
    return digest.hexdigest()


@dataclass(slots=True)
class _Entry[T]:
    """A cached value plus the monotonic deadline after which it is stale."""

    value: T
    expires_at: float


class HashCache[T]:
    """A TTL-bounded, size-capped cache keyed by a query+variables hash (§8.1).

    Generic over the cached value type ``T`` so the same primitive serves the
    1.2 board-read cache (caching a parsed :class:`~app.github.graphql.BoardPage`)
    and 1.3's point-saving read cache. Not thread-safe by design: it lives on the
    single backend event loop.

    Args:
        ttl_seconds: how long an entry stays fresh (default
            :data:`DEFAULT_TTL_SECONDS`).
        max_entries: FIFO cap on distinct keys (default
            :data:`DEFAULT_MAX_ENTRIES`).
        time_source: injectable monotonic clock (tests pass a fake to advance
            time deterministically); defaults to :func:`time.monotonic`.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        time_source: Any = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max(1, max_entries)
        self._now = time_source
        self._store: OrderedDict[str, _Entry[T]] = OrderedDict()

    @staticmethod
    def key(query: str, variables: Mapping[str, Any] | None = None) -> str:
        """Public alias for :func:`hash_query` (the cache's keying function)."""
        return hash_query(query, variables)

    def get(self, query: str, variables: Mapping[str, Any] | None = None) -> T | None:
        """Return the fresh cached value for ``(query, variables)``, or ``None``.

        A past-TTL entry is treated as a **miss** and evicted on access, so a
        stale board read is never silently served and dead entries do not
        accumulate.
        """
        cache_key = hash_query(query, variables)
        entry = self._store.get(cache_key)
        if entry is None:
            return None
        if self._now() >= entry.expires_at:
            # Expired → evict and report a miss.
            del self._store[cache_key]
            return None
        # Mark as most-recently-used so the FIFO cap evicts genuinely cold keys.
        self._store.move_to_end(cache_key)
        return entry.value

    def put(self, query: str, variables: Mapping[str, Any] | None, value: T) -> str:
        """Cache ``value`` under the ``(query, variables)`` hash; return the key.

        Refreshes the TTL on an existing key and enforces the FIFO size cap,
        evicting the oldest entry when the cap is exceeded.
        """
        cache_key = hash_query(query, variables)
        self._store[cache_key] = _Entry(value=value, expires_at=self._now() + self._ttl)
        self._store.move_to_end(cache_key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)
        return cache_key

    def invalidate(self, query: str, variables: Mapping[str, Any] | None = None) -> None:
        """Drop the entry for ``(query, variables)`` if present (a no-op miss otherwise).

        Used by 1.3's write-queue after a mutating call so a subsequent read does
        not serve a board state that predates the write it just performed.
        """
        self._store.pop(hash_query(query, variables), None)

    def clear(self) -> None:
        """Empty the cache (e.g. on reconnect to a different repo/credential)."""
        self._store.clear()

    def __len__(self) -> int:
        """Number of entries currently held (fresh or not-yet-evicted)."""
        return len(self._store)
