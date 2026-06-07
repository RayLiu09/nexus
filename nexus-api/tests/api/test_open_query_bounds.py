"""Query-parameter bounds on `/open/v1/search` and `/open/v1/qa`.

Without limits, an upstream caller can DoS the platform by passing
`top_k=999999` — the RAGFlow adapter would attempt to load and serialize an
unbounded result set. We constrain `top_k` and the query length via Pydantic
`Query` validators at the route layer.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ── Shared headers ────────────────────────────────────────────────────────

# `app` fixture stubs require_api_caller, so any X-API-Key passes — we still
# attach it to keep traces deterministic.
_AUTH = {"X-API-Key": "test-stub"}


def _error_message(body: dict) -> str:
    return body.get("error", {}).get("message", "")


# ── /open/v1/search ───────────────────────────────────────────────────────


@pytest.mark.parametrize("top_k", [0, -1, 101, 999999])
def test_search_rejects_top_k_outside_range(app, top_k):
    with TestClient(app) as client:
        resp = client.get(f"/open/v1/search?q=hi&top_k={top_k}", headers=_AUTH)
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("threshold", [-0.1, 1.01, 2.0])
def test_search_rejects_similarity_threshold_outside_range(app, threshold):
    with TestClient(app) as client:
        resp = client.get(
            f"/open/v1/search?q=hi&similarity_threshold={threshold}",
            headers=_AUTH,
        )
    assert resp.status_code == 422, resp.text


def test_search_rejects_empty_query(app):
    with TestClient(app) as client:
        resp = client.get("/open/v1/search?q=", headers=_AUTH)
    assert resp.status_code == 422


def test_search_rejects_oversized_query(app):
    huge = "x" * 2000
    with TestClient(app) as client:
        resp = client.get(f"/open/v1/search?q={huge}", headers=_AUTH)
    assert resp.status_code == 422


# ── /open/v1/qa ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("top_k", [0, 51, 1000])
def test_qa_rejects_top_k_outside_range(app, top_k):
    with TestClient(app) as client:
        resp = client.get(f"/open/v1/qa?q=hi&top_k={top_k}", headers=_AUTH)
    assert resp.status_code == 422


def test_qa_rejects_oversized_question(app):
    huge = "x" * 3000
    with TestClient(app) as client:
        resp = client.get(f"/open/v1/qa?q={huge}", headers=_AUTH)
    assert resp.status_code == 422
