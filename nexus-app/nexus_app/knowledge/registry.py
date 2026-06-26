"""ChunkingStrategy protocol and STRATEGY_REGISTRY."""

from __future__ import annotations

from typing import Any, Protocol

from nexus_app.models import KnowledgeChunk


class ChunkingStrategy(Protocol):
    """Interface that all nexus_extract chunking strategies must implement.

    ``record_body`` is the parsed ``payload.record_body`` for record-pipeline
    refs (None for document pipelines). row-oriented strategies use it
    directly so they don't have to re-parse ``content`` (which, for record
    refs, may be the body_markdown rendering instead of the JSON).
    Document-oriented strategies that don't need it accept it as ``**kwargs``.
    """

    def chunk(
        self,
        content: str,
        emission: dict[str, Any],
        kt_config: Any,
        normalized_ref_id: str,
        content_blocks: list[dict[str, Any]] | None = None,
        *,
        record_body: dict[str, Any] | list[Any] | None = None,
    ) -> list[KnowledgeChunk]: ...


STRATEGY_REGISTRY: dict[str, type[ChunkingStrategy]] = {}


def register_strategy(strategy_name: str):
    """Decorator to register a strategy class into STRATEGY_REGISTRY."""
    def decorator(cls: type[ChunkingStrategy]):
        STRATEGY_REGISTRY[strategy_name] = cls
        return cls
    return decorator
