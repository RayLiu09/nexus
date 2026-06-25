"""Dataclasses returned by the body_markdown rendering service.

Field naming mirrors `docs/pipeline_b_contract_freeze.md §5.0` exactly so
the dispatcher can dump `RenderMeta` to a dict and use it directly as
`payload.body_markdown_meta`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RenderStrategy(StrEnum):
    """How `body_markdown` was produced.

    Recorded on `payload.body_markdown_meta.render_strategy` so reviewers
    can disjoin on the source. The fallback strategy is NOT a failure
    indicator on its own — markdown rules with `fallback_strategy=
    deterministic_template` use it as the normal output path when LLM is
    unavailable / configured as fake.
    """
    LLM_ASSISTED = "llm_assisted"
    DETERMINISTIC_TEMPLATE_FALLBACK = "deterministic_template_fallback"


@dataclass(frozen=True)
class SkeletonValidation:
    """Result of validating rendered Markdown against `markdown_skeleton`."""
    passed: bool
    violations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TruncationSummary:
    """Counts populated when output exceeds skeleton.max_records_inline /
    max_abilities_per_work_content_inline. P0 just reports the counts;
    the actual overflow-notice rendering is the renderer's job."""
    truncated: bool = False
    records_inline: int = 0
    records_omitted: int = 0


@dataclass(frozen=True)
class RenderMeta:
    """Audit metadata persisted alongside body_markdown.

    Matches `payload.body_markdown_meta` keys from contract §5.0.1 exactly.
    `render_*` fields stay optional so the deterministic-only path can leave
    them None when no LLM / prompt was involved.
    """
    render_strategy: RenderStrategy
    render_scenario: str | None
    render_prompt_template_id: str | None
    render_rules_version_id: str | None
    render_confidence: float
    render_latency_ms: float
    record_body_hash: str
    skeleton_validation: SkeletonValidation
    truncation: TruncationSummary = field(default_factory=TruncationSummary)
    # Set when the LLM-assisted path was attempted but discarded. Captures
    # why we ended up on the deterministic template so reviewers don't have
    # to grep audit logs.
    fallback_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "render_strategy": self.render_strategy.value,
            "render_scenario": self.render_scenario,
            "render_prompt_template_id": self.render_prompt_template_id,
            "render_rules_version_id": self.render_rules_version_id,
            "render_confidence": self.render_confidence,
            "render_latency_ms": self.render_latency_ms,
            "record_body_hash": self.record_body_hash,
            "skeleton_validation": {
                "passed": self.skeleton_validation.passed,
                "violations": list(self.skeleton_validation.violations),
            },
            "truncation": {
                "truncated": self.truncation.truncated,
                "records_inline": self.truncation.records_inline,
                "records_omitted": self.truncation.records_omitted,
            },
            "fallback_reason": self.fallback_reason,
        }


@dataclass(frozen=True)
class RenderResult:
    """What the service hands back to `_run_domain_normalize`.

    `body_markdown` is the rendered string ready to write into
    `payload.body_markdown`; `meta` is the dict-ready audit envelope.
    `skipped` is True when no rule_set is seeded for the domain — in that
    case `body_markdown` is None and the caller leaves the payload alone.
    """
    body_markdown: str | None
    meta: RenderMeta | None
    skipped: bool = False
    skipped_reason: str | None = None


__all__ = [
    "RenderMeta",
    "RenderResult",
    "RenderStrategy",
    "SkeletonValidation",
    "TruncationSummary",
]
