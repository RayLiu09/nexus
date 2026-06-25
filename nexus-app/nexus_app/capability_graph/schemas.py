"""Dataclasses for the staging build/node/edge specifications.

`NodeSpec` / `EdgeSpec` are the **pure-data** intermediates the builders
return. The service then materialises them into PG rows under a single
build envelope.

Why separate from `models.CapabilityGraphStaging*`:
- Builders stay testable without a DB (no flush / no session).
- The whitelist enforcement lives on the Spec types (`__post_init__`) so
  a bad node_type / edge_type fails fast in the builder rather than at
  INSERT time.
- `node_key` is computed at Spec construction so deduplication can use
  `(node_type, node_key)` tuples in plain Python before persistence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from nexus_app.capability_graph.whitelists import EDGE_TYPES, NODE_TYPES


@dataclass(frozen=True)
class NodeSpec:
    """One staging node candidate.

    `node_key` MUST be stable across rebuilds — `(node_type, node_key)`
    pairs determine cross-build identity (today via uq_cgsn within the
    build; tomorrow when a `promoted` formal graph reads this layer).
    """
    node_type: str
    node_key: str
    display_name: str
    canonical_name: str | None = None
    source_table: str | None = None
    source_id: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: Decimal | None = None

    def __post_init__(self):
        if self.node_type not in NODE_TYPES:
            raise ValueError(
                f"NodeSpec.node_type {self.node_type!r} is not in NODE_TYPES "
                f"whitelist (design §7.3)"
            )
        if not self.node_key:
            raise ValueError("NodeSpec.node_key must be non-empty")
        if not self.display_name:
            raise ValueError("NodeSpec.display_name must be non-empty")


@dataclass(frozen=True)
class EdgeSpec:
    """One staging edge candidate.

    Refers to nodes via `(node_type, node_key)` pairs rather than DB IDs
    because the builder runs before any nodes are persisted. The service
    resolves these to real `source_node_id` / `target_node_id` after the
    nodes get DB IDs.
    """
    edge_type: str
    source_node_key: tuple[str, str]   # (node_type, node_key)
    target_node_key: tuple[str, str]   # (node_type, node_key)
    source_table: str | None = None
    source_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: Decimal | None = None

    def __post_init__(self):
        if self.edge_type not in EDGE_TYPES:
            raise ValueError(
                f"EdgeSpec.edge_type {self.edge_type!r} is not in EDGE_TYPES "
                f"whitelist (design §7.4)"
            )
        for label, key in (
            ("source_node_key", self.source_node_key),
            ("target_node_key", self.target_node_key),
        ):
            if not (
                isinstance(key, tuple)
                and len(key) == 2
                and all(isinstance(p, str) and p for p in key)
            ):
                raise ValueError(
                    f"EdgeSpec.{label} must be (node_type, node_key) tuple "
                    f"of non-empty strings"
                )


@dataclass(frozen=True)
class BuildResult:
    """Service-level summary returned to the worker stage.

    `skipped` lets the worker emit a clean audit when there's literally no
    domain data to graph (e.g. an ability_analysis with zero abilities).
    """
    build_id: str
    build_type: str
    nodes_written: int = 0
    edges_written: int = 0
    quality_summary: dict[str, int | str] = field(default_factory=dict)
    skipped: bool = False
    skipped_reason: str | None = None


__all__ = ["BuildResult", "EdgeSpec", "NodeSpec"]
