from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import AuditEventType

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
