"""Small per-process TTL cache for immutable normalized payloads.

Normalized refs are content-addressed by their checksum and object URI. The
public content endpoint is a high-frequency read path, so reusing a parsed
payload avoids both the object-store round trip and JSON decoding for repeated
reads of the same ref. The cache is deliberately bounded and local to one API
worker; cross-worker coordination remains outside the P0 contract.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class _CacheEntry:
    value: dict[str, Any]
    expires_at: float


class NormalizedPayloadCache:
    """Thread-safe bounded TTL cache for parsed normalized payload objects."""

    def __init__(self, *, ttl_seconds: float = 120.0, max_entries: int = 16) -> None:
        if ttl_seconds <= 0 or max_entries < 1:
            raise ValueError("ttl_seconds and max_entries must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str, str], _CacheEntry] = {}

    def get_or_load(
        self,
        key: tuple[str, str, str],
        loader: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at > now:
                return entry.value, True
            if entry is not None:
                self._entries.pop(key, None)

        value = loader()
        if not isinstance(value, dict):
            raise TypeError("normalized payload must be a JSON object")
        with self._lock:
            if len(self._entries) >= self._max_entries:
                oldest_key = min(self._entries, key=lambda item: self._entries[item].expires_at)
                self._entries.pop(oldest_key, None)
            self._entries[key] = _CacheEntry(
                value=value,
                expires_at=time.monotonic() + self._ttl_seconds,
            )
        return value, False

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


__all__ = ["NormalizedPayloadCache"]
