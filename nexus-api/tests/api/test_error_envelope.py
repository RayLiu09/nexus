"""Error envelope consistency across the handled and unhandled paths.

Every error response must conform to `ErrorResponse`:

    {
      "error": {"code": str, "message": str, "details": list},
      "meta":  {"trace_id": str, ...}
    }

The four registered handlers (HTTPException, RequestValidationError,
IntegrityError, catch-all Exception) all funnel through `error_response`
in `nexus_api/errors.py` — these tests pin that contract so a new handler
or accidental FastAPI default response can't degrade it silently.
"""
from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from nexus_api.api.internal import router as internal_router  # noqa: F401  # ensures registered


# A throwaway endpoint that raises an unhandled exception — used to exercise
# the catch-all path without bolting onto a real handler.
_DEBUG_ROUTER = APIRouter()


@_DEBUG_ROUTER.get("/__boom__")
def boom():
    raise RuntimeError("synthetic explosion for envelope coverage")


@pytest.fixture()
def app_with_boom(app_no_auth_override):
    """`app_no_auth_override` so auth boundary doesn't intercept the boom path."""
    app_no_auth_override.include_router(_DEBUG_ROUTER)
    return app_no_auth_override


# ── Envelope shape helper ─────────────────────────────────────────────────


def _assert_envelope(body: dict, *, code: str, status: int, resp_status: int) -> None:
    assert resp_status == status, f"expected status {status}, got {resp_status}"
    assert "error" in body, f"missing 'error' key: {body}"
    assert "meta" in body, f"missing 'meta' key: {body}"
    err = body["error"]
    assert err["code"] == code, f"code mismatch: {err.get('code')!r} != {code!r}"
    assert isinstance(err.get("message"), str) and err["message"]
    assert isinstance(err.get("details"), list)
    meta = body["meta"]
    assert "trace_id" in meta


# ── HTTPException → handled by http_exception_handler ─────────────────────


def test_404_uses_envelope_with_not_found_code(app):
    """A 404 from an unknown resource — handled via HTTPException(404)."""
    with TestClient(app) as client:
        resp = client.get("/internal/v1/assets/does-not-exist")
    _assert_envelope(resp.json(), code="NOT_FOUND", status=404, resp_status=resp.status_code)


def test_400_uses_envelope_with_bad_request_code(app):
    """Idempotency-Key empty header is a 400 from require_idempotency_key —
    that goes through HTTPException, so envelope code is BAD_REQUEST."""
    with TestClient(app) as client:
        resp = client.post(
            "/internal/v1/ingest/files",
            headers={"Idempotency-Key": ""},
            json={},
        )
    _assert_envelope(resp.json(), code="BAD_REQUEST", status=400, resp_status=resp.status_code)


def test_428_uses_envelope_with_precondition_required_code(app):
    """428 is mapped to PRECONDITION_REQUIRED in `_HTTP_STATUS_CODES`."""
    with TestClient(app) as client:
        resp = client.post("/internal/v1/ingest/files", json={})
    _assert_envelope(
        resp.json(), code="PRECONDITION_REQUIRED", status=428, resp_status=resp.status_code
    )


# ── RequestValidationError → validation_exception_handler ─────────────────


def test_422_uses_envelope_with_validation_error_code(app):
    """An obviously bad payload triggers Pydantic ValidationError → 422."""
    with TestClient(app) as client:
        resp = client.post(
            "/internal/v1/ingest/files",
            headers={"Idempotency-Key": "test-validation"},
            json={"missing_required_fields": True},
        )
    body = resp.json()
    _assert_envelope(body, code="VALIDATION_ERROR", status=422, resp_status=resp.status_code)
    # Validation errors should surface field-level details for clients to display.
    assert body["error"]["details"], "validation errors should carry per-field details"


# ── Catch-all Exception → unhandled_exception_handler ─────────────────────


def test_unhandled_exception_returns_internal_error_envelope(app_with_boom):
    """A bare RuntimeError must be converted to the INTERNAL_ERROR envelope
    instead of FastAPI's default `{"detail": "Internal Server Error"}`."""
    with TestClient(app_with_boom, raise_server_exceptions=False) as client:
        resp = client.get("/__boom__")
    _assert_envelope(
        resp.json(),
        code="INTERNAL_ERROR",
        status=500,
        resp_status=resp.status_code,
    )


def test_unhandled_exception_does_not_leak_message_to_client(app_with_boom):
    """The handler logs the full exception but never echoes it back —
    operators correlate via trace_id, clients see the stable message."""
    with TestClient(app_with_boom, raise_server_exceptions=False) as client:
        resp = client.get("/__boom__")
    body = resp.json()
    # No exception class name, no traceback fragment in the message.
    assert "synthetic explosion" not in body["error"]["message"]
    assert "RuntimeError" not in body["error"]["message"]
