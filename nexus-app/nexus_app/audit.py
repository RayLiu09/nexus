from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import AssetAccessType, AuditEventType

if TYPE_CHECKING:  # pragma: no cover
    from nexus_app.retrieval.dag_orchestrator import DagExecutionResult
    from nexus_app.retrieval.domain_registry import QueryProfile
    from nexus_app.retrieval.schemas import RetrievalPlan, RetrievalSubQuery
    from nexus_app.retrieval.tag_filter_execution import TagFilterExecutionResult

# Keys (case-insensitive substrings) whose values are stripped from audit
# summaries before persistence. Compared after lower-casing the key.
SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    "api_key", "apikey",
    "api_secret", "secret",
    "password", "passwd",
    "bearer", "token",
    "private_key", "privatekey",
    "ragflow_api_key", "ragflow_endpoint",
    "litellm_api_key",
    "minio_access_key", "minio_secret_key",
    "authorization",
)

# Top-level keys whose string values can be very large and bloat the audit
# table. Replaced with a length-bound placeholder.
LARGE_BLOB_KEYS: tuple[str, ...] = (
    "raw_output", "raw_content", "content", "body_markdown",
    "ai_output", "ai_input", "messages",
)

_REDACTED = "***redacted***"
_MAX_STRING_LEN = 2000

# Patterns that look like inline secrets even inside otherwise-clean strings.
_INLINE_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|ragflow-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._\-]{16,})",
    re.IGNORECASE,
)


def _is_sensitive_key(key: str) -> bool:
    k = key.lower()
    return any(p in k for p in SENSITIVE_KEY_PATTERNS)


def _is_large_blob_key(key: str) -> bool:
    return key.lower() in LARGE_BLOB_KEYS


def _scrub_string(value: str) -> str:
    if len(value) > _MAX_STRING_LEN:
        value = value[: _MAX_STRING_LEN - 14] + "...[truncated]"
    return _INLINE_SECRET_PATTERN.sub(_REDACTED, value)


def sanitize_audit_summary(value: Any, _depth: int = 0) -> Any:
    """Return a copy of `value` with sensitive keys / large blobs redacted.

    Recursive: handles nested dicts and lists; depth-bounded to avoid blowing
    the stack on pathological payloads. Non-container scalars are scrubbed for
    inline secret patterns and length-capped.
    """
    if _depth >= 8:
        return _REDACTED  # bail out — recursion that deep is almost certainly
                          # a serialization mistake and not legitimate audit data
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if _is_sensitive_key(key):
                cleaned[key] = _REDACTED
            elif _is_large_blob_key(key) and isinstance(v, str):
                cleaned[key] = f"<{len(v)} chars omitted>"
            else:
                cleaned[key] = sanitize_audit_summary(v, _depth + 1)
        return cleaned
    if isinstance(value, list):
        return [sanitize_audit_summary(v, _depth + 1) for v in value]
    if isinstance(value, str):
        return _scrub_string(value)
    return value


def write_audit(
    session: Session,
    event_type: AuditEventType,
    target_type: str,
    target_id: str,
    trace_id: str | None,
    summary: dict[str, Any],
    *,
    actor_type: str | None = None,
    actor_id: str | None = None,
) -> models.AuditLog:
    """Persist an audit log row. The `summary` payload is sanitized before
    storage to prevent secret leaks and bound payload size."""
    sanitized = sanitize_audit_summary(summary)
    audit = models.AuditLog(
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        trace_id=trace_id,
        summary=sanitized,
    )
    session.add(audit)
    session.flush()
    return audit


# Stable mapping of access_type → audit target_type. Lets callers stay focused
# on the access verb while keeping audit `target_type` aligned with the
# resource being requested (`/open/v1/...` path leaf).
_ACCESS_TYPE_TARGET: dict[AssetAccessType, str] = {
    AssetAccessType.ASSET_DETAIL:      "asset",
    AssetAccessType.VERSION_LIST:      "asset",
    AssetAccessType.NORMALIZED_REF:    "normalized_asset_ref",
    AssetAccessType.GOVERNANCE_RESULT: "normalized_asset_ref",
    AssetAccessType.KNOWLEDGE_CHUNK:   "knowledge_chunk",
    AssetAccessType.CHUNK_LIST:        "normalized_asset_ref",
    AssetAccessType.RAW_DOWNLOAD:      "raw_object",
}


def write_asset_version_accessed_audit(
    session: Session,
    *,
    caller: models.ApiCaller,
    access_type: AssetAccessType,
    target_id: str,
    asset_id: str | None = None,
    version_id: str | None = None,
    version_ids: list[str] | None = None,
    normalized_ref_id: str | None = None,
    trace_id: str | None = None,
) -> models.AuditLog:
    """Emit `ASSET_VERSION_ACCESSED` for an `/open/v1` consumption read.

    The summary holds the minimal lineage triple — `asset_id`, `version_id`,
    `normalized_ref_id` — plus the `access_type` discriminator. Caller identity
    is recorded via `actor_type=api_caller` + `actor_id=caller.id`, not
    duplicated in the summary.

    `version_ids` is used by `version_list` accesses where the caller
    enumerated multiple available versions in a single request.
    """
    summary: dict[str, Any] = {"access_type": access_type.value}
    if asset_id is not None:
        summary["asset_id"] = asset_id
    if version_id is not None:
        summary["version_id"] = version_id
    if version_ids is not None:
        summary["version_ids"] = version_ids
    if normalized_ref_id is not None:
        summary["normalized_ref_id"] = normalized_ref_id

    return write_audit(
        session,
        AuditEventType.ASSET_VERSION_ACCESSED,
        target_type=_ACCESS_TYPE_TARGET[access_type],
        target_id=target_id,
        trace_id=trace_id,
        summary=summary,
        actor_type="api_caller",
        actor_id=caller.id,
    )


# ---------------------------------------------------------------------------
# v1.3 PR-12 — retrieval-side audits
# ---------------------------------------------------------------------------


def write_retrieval_tag_filter_audit(
    session: Session,
    *,
    sub_query: "RetrievalSubQuery",
    profile: "QueryProfile",
    phase_a: "TagFilterExecutionResult",
    trace_id: str | None = None,
) -> models.AuditLog | None:
    """Emit ``RETRIEVAL_TAG_FILTER_APPLIED`` when Phase A ran.

    Skipped when the sub_query declared no tag_filters — the audit only
    exists to explain *how* tag_filter narrowing behaved, so a pass-
    through sub_query needs no row.  Failure to write the audit never
    raises; retrieval must not be blocked by an audit-side problem.
    """
    if not sub_query.tag_filters:
        return None
    summary: dict[str, Any] = {
        "sub_query_id": sub_query.query_id,
        "channel": str(sub_query.channel),
        "domain": str(sub_query.domain),
        "profile_key": profile.key,
        "tag_target_type": (
            str(profile.tag_target_type) if profile.tag_target_type else None
        ),
        "combine": sub_query.combine,
        "bucket_hit_counts": dict(phase_a.bucket_hit_counts),
        "match_layer_counts": dict(phase_a.match_layer_counts),
        "dropped_optional_buckets": list(phase_a.dropped_optional_buckets),
        "skipped_bucket_out_of_domain": list(
            phase_a.skipped_bucket_out_of_domain
        ),
        "target_ids_count": (
            len(phase_a.target_ids) if phase_a.target_ids is not None else None
        ),
        "applied": phase_a.applied,
        "warnings": list(phase_a.warnings),
        # Which buckets were declared (values kept — tag values are
        # published taxonomy strings, not user PII).
        "declared_buckets": sorted(sub_query.tag_filters.keys()),
    }
    try:
        return write_audit(
            session,
            AuditEventType.RETRIEVAL_TAG_FILTER_APPLIED,
            target_type="retrieval_sub_query",
            target_id=sub_query.query_id,
            trace_id=trace_id,
            summary=summary,
        )
    except Exception:  # noqa: BLE001 - never fail retrieval on audit error
        return None


def write_retrieval_dag_audit(
    session: Session,
    *,
    plan: "RetrievalPlan",
    dag_result: "DagExecutionResult",
    trace_id: str | None = None,
) -> models.AuditLog | None:
    """Emit ``RETRIEVAL_DAG_EXECUTED`` once per plan run.

    Records the DAG layer structure + summary counts.  Original query
    text is NOT persisted — it can carry user PII; the sub_query ids
    together with the layer sequence are enough to reconstruct the plan
    from ``retrieval_plan`` on disk.
    """
    summary: dict[str, Any] = {
        "sub_query_count": len(plan.sub_queries),
        "layer_count": len(dag_result.layers),
        "max_dag_depth_declared": plan.max_dag_depth,
        "layers": [
            {
                "depth": layer.depth,
                "sub_query_ids": list(layer.sub_query_ids),
            }
            for layer in dag_result.layers
        ],
        "shared_constraints_present": plan.shared_constraints is not None,
        "warnings": list(dag_result.warnings),
        # Per-sub_query outcome recap so a single audit row explains
        # both order and status without joining another table.
        "sub_query_outcomes": [
            {
                "sub_query_id": r.query_id,
                "status": str(r.status),
                "result_shape": r.result_shape,
                "warning_count": len(r.warnings),
            }
            for r in dag_result.results
        ],
    }
    try:
        # Plan-level id: pick the first sub_query.query_id as a stable
        # anchor (plans don't carry their own persistent id).
        target_id = (
            plan.sub_queries[0].query_id if plan.sub_queries else "plan"
        )
        return write_audit(
            session,
            AuditEventType.RETRIEVAL_DAG_EXECUTED,
            target_type="retrieval_plan",
            target_id=target_id,
            trace_id=trace_id,
            summary=summary,
        )
    except Exception:  # noqa: BLE001
        return None
