"""Bounded freshness for the authenticated, global Asset Center aggregates."""

from collections.abc import Callable
from threading import Lock
from time import monotonic


class AssetCenterCountsCache:
    """One cache per app; serialize refreshes and cache only successful results.

    Counts have no user/org-specific fields today. Authentication must still run
    on every request, including hits. If count scope changes, partition this
    cache by the effective permission scope before adding scoped counts.
    """

    def __init__(self, ttl_seconds: float = 15.0) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = Lock()
        self._expires_at = 0.0
        self._counts: dict[str, int] | None = None

    def get_or_build(self, build: Callable[[], dict[str, int]]) -> dict[str, int]:
        with self._lock:
            if self._counts is None or monotonic() >= self._expires_at:
                counts = build()
                self._counts = dict(counts)
                self._expires_at = monotonic() + self._ttl_seconds
            return dict(self._counts)
