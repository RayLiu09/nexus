"""Schema constants for normalized_record payload (B3).

Centralised so callers don't re-spell version strings. Bumping the constant
forces every reader / writer to update together; B4 / B6 / B7 (governance,
domain normalize) all import from here.

See `docs/pipeline_b_contract_freeze.md` §5.0 for the canonical payload
contract — this module pins the version string used in
`normalized_record.payload.schema_version` and the matching
`NormalizedAssetRef.schema_version` for record-typed assets.
"""
from __future__ import annotations

# Bumped from "normalized-record-v1" to "normalized-record.v2" in B3 when
# we added top-level `domain_profile` + `body_markdown` / `body_markdown_meta`
# placeholders. The dot-prefixed minor version mirrors the style used for
# domain_profile values (e.g. "ability_analysis.pgsd.v1") so downstream
# parsers can split on `.` uniformly.
NORMALIZED_RECORD_SCHEMA_VERSION: str = "normalized-record.v2"

# Pipeline A document payload schema — unchanged in B3. Tracked here so the
# schema-version comparison call sites in B7 governance / B9 console can
# import a single source instead of hardcoding the string.
NORMALIZED_DOCUMENT_SCHEMA_VERSION: str = "normalized-document-v1"


__all__ = [
    "NORMALIZED_RECORD_SCHEMA_VERSION",
    "NORMALIZED_DOCUMENT_SCHEMA_VERSION",
]
