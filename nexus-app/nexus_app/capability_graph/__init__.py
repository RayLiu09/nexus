"""Pipeline B B8 — CapabilityGraphStaging materialization.

Reads from B4 + B5 + B6 domain tables; writes one
`capability_graph_staging_build` row plus its nodes + edges. Triggered
from `worker/runner.py:_run_capability_graph_staging` after B7
governance succeeds.

Module layout:
- `whitelists.py`  — node_type / edge_type whitelists + status / build_type
                    constants (single source of truth shared with B9 UI)
- `schemas.py`     — BuildResult / NodeSpec / EdgeSpec dataclasses
- `builders.py`    — per-build_type pure-logic materializers (no DB IO)
- `service.py`     — orchestrator that loads domain rows, runs the
                    relevant builder, and persists the build envelope
"""
from __future__ import annotations

from nexus_app.capability_graph.schemas import (
    BuildResult,
    EdgeSpec,
    NodeSpec,
)
from nexus_app.capability_graph.service import build_capability_staging
from nexus_app.capability_graph.whitelists import (
    BUILD_TYPES,
    EDGE_TYPES,
    NODE_TYPES,
    STAGING_SCHEMA_VERSION,
    STAGING_STATUSES,
)

__all__ = [
    "BUILD_TYPES",
    "BuildResult",
    "EDGE_TYPES",
    "EdgeSpec",
    "NODE_TYPES",
    "NodeSpec",
    "STAGING_SCHEMA_VERSION",
    "STAGING_STATUSES",
    "build_capability_staging",
]
