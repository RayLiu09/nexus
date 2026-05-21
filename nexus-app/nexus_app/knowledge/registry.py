"""ChunkingStrategy protocol and STRATEGY_REGISTRY."""

from __future__ import annotations

from typing import Any, Protocol

from nexus_app.models import KnowledgeChunk


class ChunkingStrategy(Protocol):
    """Interface that all nexus_extract chunking strategies must implement."""

    def chunk(
        self,
        content: str,
        emission: dict[str, Any],
        kt_config: Any,
        normalized_ref_id: str,
    ) -> list[KnowledgeChunk]: ...


STRATEGY_REGISTRY: dict[str, type[ChunkingStrategy]] = {}


def register_strategy(strategy_name: str):
    """Decorator to register a strategy class into STRATEGY_REGISTRY."""
    def decorator(cls: type[ChunkingStrategy]):
        STRATEGY_REGISTRY[strategy_name] = cls
        return cls
    return decorator
