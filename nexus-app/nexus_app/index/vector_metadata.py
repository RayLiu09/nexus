"""Compact vector projections with canonical normalized-asset hydration."""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from nexus_app.models import NormalizedAssetRef

STORAGE_KEY = "_normalized_ref_fields"
CANONICAL_FIELDS = ("governance", "quality", "lineage")


def same_json_value(left: Any, right: Any) -> bool:
    # Python treats True == 1; JSON clients do not. Compare JSON values with
    # types preserved before deciding that a canonical copy is interchangeable.
    options = {"ensure_ascii": False, "sort_keys": True, "separators": (",", ":")}
    return json.dumps(left, **options) == json.dumps(right, **options)


def compact_metadata(
    metadata: dict[str, Any], ref: NormalizedAssetRef,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Replace redundant snapshots with current normalized-asset references.

    Normalized assets own governance, quality and lineage. The user explicitly
    approved discarding stale vector snapshots in favor of these current values.
    Unknown projection fields stay intact; unavailable canonical fields cannot
    be removed. The marker records exactly which fields readers batch hydrate.
    """
    result = deepcopy(metadata)
    parent = result.get("normalized_ref")
    if not isinstance(parent, dict) or parent.get("normalized_ref_id") != ref.id:
        return result, ()
    omitted = result.get(STORAGE_KEY, [])
    if not isinstance(omitted, list) or any(field not in CANONICAL_FIELDS for field in omitted):
        raise ValueError("invalid compact vector metadata marker")
    omitted = list(omitted)
    changed = []
    for field in CANONICAL_FIELDS:
        canonical = getattr(ref, field)
        if field in parent and canonical is not None:
            del parent[field]
            if field not in omitted:
                omitted.append(field)
            changed.append(field)
    if omitted:
        result[STORAGE_KEY] = omitted
    return result, tuple(changed)


def hydrate_metadata(
    metadata: dict[str, Any], ref: NormalizedAssetRef | None,
    *, include_lineage: bool = True,
) -> dict[str, Any]:
    """Reconstruct the existing response shape without mutating stored JSON."""
    source = metadata
    if not include_lineage and isinstance(metadata.get("normalized_ref"), dict):
        # Drop lineage before copying, including pre-compaction snapshots.
        # Governance/quality must still be restored for permission consumers.
        source = {**metadata, "normalized_ref": {
            key: value for key, value in metadata["normalized_ref"].items()
            if key != "lineage"
        }}
    result = deepcopy(source)
    omitted = result.pop(STORAGE_KEY, None)
    if omitted is None:
        return result
    if (
        not isinstance(omitted, list)
        or any(field not in CANONICAL_FIELDS for field in omitted)
        or not isinstance(result.get("normalized_ref"), dict)
        or ref is None
    ):
        raise ValueError("compact vector metadata has no valid normalized-asset source")
    if result["normalized_ref"].get("normalized_ref_id") != ref.id:
        raise ValueError("compact vector metadata normalized-ref identity mismatch")
    for field in omitted:
        if field == "lineage" and not include_lineage:
            continue
        value = getattr(ref, field)
        if value is None:
            raise ValueError("compact vector metadata canonical field is missing")
        result["normalized_ref"][field] = deepcopy(value)
    if "governance" in omitted and isinstance(result.get("asset"), dict):
        governance = ref.governance
        if isinstance(governance, dict):
            # These small asset fields mirror normalized governance. Readers
            # must not expose an old classification/level next to the current
            # hydrated governance. Asset/version identity stays unchanged.
            for field in ("classification", "level", "tags", "org_scope"):
                if field in result["asset"] and field in governance:
                    result["asset"][field] = deepcopy(governance[field])
    return result
