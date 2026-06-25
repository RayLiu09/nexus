"""Pipeline B `body_markdown` rendering module (B5.3).

Owns the LLM-driven derivative-Markdown view of a `normalized_record.payload`
(per `docs/pipeline_b_contract_freeze.md §5.0.3`). The result is written
back into `payload.body_markdown` + `payload.body_markdown_meta` so the
existing AI-governance LLM input chain (`_derive_body_text` in
`normalize/service.py`) consumes it without modification.

Triggered from `worker/runner.py:_run_domain_normalize` after the per-domain
writer (B4 / B6) succeeds. Failures always fall back to a code-side
deterministic template — rendering NEVER blocks the writer's success, since
领域表 already has the canonical data (`record_body` JSON).

Two domains supported in B5.3:
- `job_demand.v1`             — see `deterministic.render_job_demand`
- `ability_analysis.pgsd.v1`  — see `deterministic.render_ability_analysis`
"""
from __future__ import annotations

from nexus_app.body_markdown.cache import RenderCache
from nexus_app.body_markdown.schemas import (
    RenderMeta,
    RenderResult,
    RenderStrategy,
    SkeletonValidation,
    TruncationSummary,
)
from nexus_app.body_markdown.service import (
    SUPPORTED_DOMAIN_PROFILES,
    render_body_markdown,
)

__all__ = [
    "RenderCache",
    "RenderMeta",
    "RenderResult",
    "RenderStrategy",
    "SUPPORTED_DOMAIN_PROFILES",
    "SkeletonValidation",
    "TruncationSummary",
    "render_body_markdown",
]
