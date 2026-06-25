"""In-process TTL cache for rendered body_markdown.

Keyed by `(rule_set_code, version, prompt_template_id, prompt_version,
record_body_hash)` per contract §5.0.3, so the same record_body re-rendered
under the same prompt + rule set hits the cache and skips the LLM round-trip.

CLAUDE.md explicitly forbids Redis at P0 — this is the in-process TTL cache
the architecture allows until the scale-up triggers documented there are
met. The cache is module-global (single shared dict per worker process) so
that the worker's own re-runs of the same payload benefit; cross-worker
sharing waits for the Redis upgrade.

The cache is **only** consulted on the LLM-assisted path. The deterministic
fallback is already fast and the result depends on no external state, so
caching adds nothing.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

# 1 hour default — long enough to absorb worker re-runs from retries /
# duplicate ingestion, short enough that operator prompt edits aren't
# silently masked by stale cache entries.
_DEFAULT_TTL_SECONDS = 3600


@dataclass(frozen=True)
class CacheKey:
    """Composite key required by contract §5.0.3."""
    rule_set_code: str
    rule_set_version: str
    prompt_template_id: str
    prompt_version: str
    record_body_hash: str


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class RenderCache(Generic[T]):
    """Tiny thread-safe TTL cache.

    Intentionally NOT using `functools.lru_cache` — we need wall-clock TTL,
    not call-count eviction, and we need the cache instance to be testable
    / clearable from outside (unit tests reach in and reset rather than
    waiting for a real hour to pass).
    """

    def __init__(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store: dict[CacheKey, _Entry[T]] = {}

    def get(self, key: CacheKey) -> T | None:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at < now:
                del self._store[key]
                return None
            return entry.value

    def put(self, key: CacheKey, value: T) -> None:
        with self._lock:
            self._store[key] = _Entry(
                value=value, expires_at=time.monotonic() + self._ttl
            )

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# Module-singleton — accessed via `get_default_cache()`. Tests reset via
# `.clear()` so the cache doesn't leak between cases.
_DEFAULT_CACHE: RenderCache[tuple] = RenderCache()


def get_default_cache() -> RenderCache[tuple]:
    return _DEFAULT_CACHE


__all__ = ["CacheKey", "RenderCache", "get_default_cache"]
