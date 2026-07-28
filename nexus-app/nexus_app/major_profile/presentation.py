"""Reconcile derived major-profile presentation metadata with governance."""

from __future__ import annotations

from typing import Any

from nexus_app import models

DOMAIN_PROFILE = "major_profile.v1"
MAJOR_PROFILE_CLASSIFICATIONS = frozenset({"major_profile", "program_profile"})
_PRESENTATION_KEYS = frozenset({
    "domain_profile",
    "domain_profiles",
    "major_profile_count",
})


def reconcile_presentation(
    ref: models.NormalizedAssetRef,
    classification: str | None,
) -> dict[str, Any] | None:
    """Suppress a stale major-profile presentation after official governance.

    The normalized payload and historical domain rows remain traceable. Only
    the metadata that activates the Console's specialized presentation is
    removed when the authoritative classification says this is not a
    professional-introduction asset.
    """
    summary = dict(ref.metadata_summary or {})
    if summary.get("domain_profile") != DOMAIN_PROFILE:
        return None
    if classification in MAJOR_PROFILE_CLASSIFICATIONS:
        return None

    removed_keys = sorted(key for key in _PRESENTATION_KEYS if key in summary)
    if not removed_keys:
        return None
    for key in removed_keys:
        summary.pop(key, None)
    ref.metadata_summary = summary
    return {
        "domain_profile": DOMAIN_PROFILE,
        "official_classification": classification,
        "removed_metadata_keys": removed_keys,
        "reason": "official_classification_incompatible",
    }
