"""Locator helpers for Task Outline nodes."""

from __future__ import annotations

from typing import Any

from nexus_app.knowledge.chunk_builder import _aggregate_locator


def aggregate_locator(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Aggregate normalized document blocks into the shared locator shape."""
    source_blocks = [block for block in blocks if block.get("block_id")]
    if not source_blocks:
        return None
    return _aggregate_locator(source_blocks)


def block_ids(blocks: list[dict[str, Any]]) -> list[str]:
    return [str(block["block_id"]) for block in blocks if block.get("block_id")]

