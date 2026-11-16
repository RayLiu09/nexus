"""Bounded in-process cache for deterministic query embeddings."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class _EmbeddingEntry:
    vector: tuple[float, ...]
    expires_at: float


class QueryEmbeddingCache:
    """Thread-safe TTL cache keyed by model, dimension, and exact query text."""

    def __init__(self, *, ttl_seconds: float = 60.0, max_entries: int = 512) -> None:
        if ttl_seconds <= 0 or max_entries < 1:
            raise ValueError("ttl_seconds and max_entries must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, int, str], _EmbeddingEntry] = {}

    def get(self, key: tuple[str, int, str]) -> list[float] | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._entries.pop(key, None)
                return None
            return list(entry.vector)

    def put(self, key: tuple[str, int, str], vector: list[float]) -> None:
        with self._lock:
            if len(self._entries) >= self._max_entries:
                oldest_key = min(self._entries, key=lambda item: self._entries[item].expires_at)
                self._entries.pop(oldest_key, None)
            self._entries[key] = _EmbeddingEntry(
                vector=tuple(float(value) for value in vector),
                expires_at=time.monotonic() + self._ttl_seconds,
            )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_DEFAULT_CACHE = QueryEmbeddingCache()


def get_default_query_embedding_cache() -> QueryEmbeddingCache:
    return _DEFAULT_CACHE


__all__ = ["QueryEmbeddingCache", "get_default_query_embedding_cache"]
