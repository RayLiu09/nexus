"""Pydantic models for governance decision trail and context."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AdoptionStatus = Literal["auto_adopted", "review_required", "rejected"]


# Read-side visibility tiers for governance_result.decision_trail (Review §4.3).
# `full`     : AI suggestion + confidence + threshold internals exposed
#              (platform_data_admin / business_expert)
# `operator` : final values + adoption_status + review_reason only — used by
#              ops dashboards that need to know what was decided and why,
#              without seeing AI reasoning details
# `public`   : decision_trail is replaced with an empty list — for api_callers
#              that only need the outcome fields on GovernanceResult itself
DecisionTrailView = Literal["full", "operator", "public"]


class DecisionTrailEntry(BaseModel):
    """One field's decision record in governance_result.decision_trail."""

    field_name: Literal["classification", "level", "tags", "quality"]
    ai_suggestion: Any
    ai_confidence: float = Field(ge=0, le=1)
    threshold_check: dict[str, Any]
    final_value: Any
    adoption_status: AdoptionStatus
    review_reason: str | None = None


class GovernanceDecisionContext(BaseModel):
    """Input context for GovernanceDecisionService.execute_governance()."""

    normalized_ref_id: str
    ai_run_id: str
    ai_output: dict[str, Any]
    quality_summary: dict[str, Any]
    rules_schema_version: str
    rules_content_hash: str
