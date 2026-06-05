"""`Idempotency-Key` header enforcement for mutating endpoints.

CLAUDE.md mandates idempotency on all mutating APIs/jobs. The service layer
already dedupes on body-level idempotency keys (see
`nexus_app/ingest/gateway.py`), but the API surface previously accepted
mutation requests with no key at all — leaving room for accidental retries
to race past the dedup window.

This dependency makes the header a hard requirement on selected POST
endpoints: missing → 428 Precondition Required, blank → 400 Bad Request.

The header value is currently NOT cross-validated against body-level keys
(ingest endpoints carry their own `idempotency_key` fields). That alignment
is left for a follow-up so this PR stays focused on the API contract gap.
"""
from __future__ import annotations

from fastapi import Header, HTTPException

_MAX_KEY_LEN = 256


def require_idempotency_key(
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> str:
    """Resolve and validate the `Idempotency-Key` request header.

    Raises:
        HTTPException(428) — header missing entirely
        HTTPException(400) — header present but empty / whitespace
        HTTPException(400) — header longer than 256 chars (DoS guard)

    Returns:
        The trimmed key for handler-level use.
    """
    if idempotency_key is None:
        raise HTTPException(
            status_code=428,
            detail="Idempotency-Key header is required for this mutation",
        )
    trimmed = idempotency_key.strip()
    if not trimmed:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key header must not be empty",
        )
    if len(trimmed) > _MAX_KEY_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Idempotency-Key header exceeds maximum length of {_MAX_KEY_LEN}",
        )
    return trimmed
