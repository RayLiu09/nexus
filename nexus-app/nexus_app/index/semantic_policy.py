"""Explicit exclusions for assets whose retrieval is owned by domain tables.

Do not infer this from the mere existence of domain projections: textbooks,
standards, major profiles and training plans still have semantic complements.
"""
from __future__ import annotations

from nexus_app.models import NormalizedAssetRef

STRUCTURED_ONLY_ASSET_TYPES = frozenset({
    "structured_record_table",  # retired generic Pipeline B vector projection
    "job_demand",              # job_demand / market job SQL contracts
    "major_distribution",      # major_offering SQL contract
    "competency_analysis",     # occupational ability analysis SQL contract
    "enterprise",              # enterprise domain facts
    "industrial_park",         # industrial park domain facts
})


def supports_semantic_index(ref: NormalizedAssetRef) -> bool:
    if ref.normalized_type == "record":
        return False
    governance = ref.governance or {}
    summary = ref.metadata_summary or {}
    classification = governance.get("classification") or summary.get("classification")
    return classification not in STRUCTURED_ONLY_ASSET_TYPES
