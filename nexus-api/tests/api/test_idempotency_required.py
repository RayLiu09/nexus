"""Idempotency-Key header enforcement on `/internal/v1` mutating endpoints.

CLAUDE.md mandates idempotency on every mutating API. Service-layer dedupe
(`ingest/gateway.py`) covers business reality; this dependency hardens the
HTTP contract so accidental retries without a key are rejected at the
boundary instead of slipping past the dedup window.

These tests pin the contract by issuing minimal POSTs and asserting that
the absence of the header returns 428 *before* any handler logic runs.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Set of `(METHOD, PATH, body_kind)` entries that must require `Idempotency-Key`.
# `body_kind` selects the synthetic payload helper. Endpoint handlers should
# reject before validating the payload, so any well-typed stub is fine.
_PROTECTED_ENDPOINTS = [
    ("POST", "/internal/v1/ingest/batches", "json"),
    ("POST", "/internal/v1/ingest/batches/test-batch/files", "json"),
    ("POST", "/internal/v1/ingest/files", "json"),
    ("POST", "/internal/v1/ingest/files/multi", "json"),
    ("POST", "/internal/v1/ingest/crawler-packages", "json"),
    ("POST", "/internal/v1/ai/prompt-profiles", "json"),
    ("POST", "/internal/v1/ai/governance-runs", "json"),
]


def _post(client: TestClient, path: str, body_kind: str, **kwargs):
    if body_kind == "json":
        return client.post(path, json={}, **kwargs)
    if body_kind == "form":
        return client.post(path, data={}, **kwargs)
    raise ValueError(f"unknown body kind: {body_kind}")


def _error_message(resp_json: dict) -> str:
    return resp_json.get("error", {}).get("message", "")


@pytest.mark.parametrize("method,path,body_kind", _PROTECTED_ENDPOINTS)
def test_missing_header_returns_428(app, method, path, body_kind):
    with TestClient(app) as client:
        resp = _post(client, path, body_kind)
    assert resp.status_code == 428, (
        f"expected 428 from {method} {path} without Idempotency-Key, "
        f"got {resp.status_code}: {resp.text[:200]}"
    )
    assert "Idempotency-Key" in _error_message(resp.json())


@pytest.mark.parametrize("method,path,body_kind", _PROTECTED_ENDPOINTS)
def test_empty_header_returns_400(app, method, path, body_kind):
    with TestClient(app) as client:
        resp = _post(
            client,
            path,
            body_kind,
            headers={"Idempotency-Key": "   "},
        )
    assert resp.status_code == 400


def test_oversized_header_returns_400(app):
    with TestClient(app) as client:
        resp = client.post(
            "/internal/v1/ingest/files",
            headers={"Idempotency-Key": "x" * 300},
            json={},
        )
    assert resp.status_code == 400
    assert "maximum length" in _error_message(resp.json())


def test_present_header_does_not_short_circuit_to_428(app):
    """A valid header should let the handler run (and fail on the empty body —
    typically 422 from Pydantic validation). The point is: no 428."""
    with TestClient(app) as client:
        resp = client.post(
            "/internal/v1/ingest/files",
            headers={"Idempotency-Key": "test-idem-1"},
            json={},
        )
    assert resp.status_code != 428


def test_upload_endpoint_also_requires_header(app):
    """Multipart upload follows the same contract."""
    with TestClient(app) as client:
        resp = client.post(
            "/internal/v1/ingest/files/upload",
            data={"data_source_id": "x", "idempotency_key": "y"},
            files={"file": ("a.bin", b"x", "application/octet-stream")},
        )
    assert resp.status_code == 428
