"""Tests for search/qa endpoints: permission hook + audit events + source citation."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
    DataSourceType,
    IngestBatchStatus,
    RawObjectStatus,
)


def _seed_fake_chain(session, n: int = 3) -> None:
    """Seed DataSource / IngestBatch / RawObject / Asset / AssetVersion rows
    matching FakeRAGFlowAdapter ids (fake_ds_{i}, fake_raw_{i}, fake_asset_{i},
    fake_version_{i}) so fake hits survive _filter_hits_to_available and so
    enrichment via raw.data_source_id can resolve.

    The fake adapter populates `nexus_chunk_id` directly on hits, which causes
    _enrich_with_nexus_refs to skip DB lookup; but _filter_hits_to_available
    still requires the AssetVersion row to exist and be AVAILABLE.
    """
    for i in range(1, n + 1):
        ds = models.DataSource(
            id=f"fake_ds_{i}",
            code=f"fake_ds_code_{i}",
            name=f"Fake Source {i}",
            source_type=DataSourceType.FILE_UPLOAD,
        )
        batch = models.IngestBatch(
            id=f"fake_batch_{i}",
            data_source_id=f"fake_ds_{i}",
            idempotency_key=f"idem_{i}",
            source_type=DataSourceType.FILE_UPLOAD,
            status=IngestBatchStatus.COMPLETED,
        )
        raw = models.RawObject(
            id=f"fake_raw_{i}",
            batch_id=f"fake_batch_{i}",
            data_source_id=f"fake_ds_{i}",
            source_type=DataSourceType.FILE_UPLOAD,
            object_uri=f"s3://nexus-raw/fake/{i}/source.pdf",
            checksum=f"sha256:fake_checksum_{i}",
            status=RawObjectStatus.RAW_PERSISTED,
        )
        asset = models.Asset(
            id=f"fake_asset_{i}",
            data_source_id=f"fake_ds_{i}",
            source_object_key=f"fake/key/{i}",
            title=f"Fake Asset {i}",
            asset_kind=AssetKind.DOCUMENT,
            status=AssetVersionStatus.AVAILABLE,
        )
        version = models.AssetVersion(
            id=f"fake_version_{i}",
            asset_id=f"fake_asset_{i}",
            raw_object_id=f"fake_raw_{i}",
            version_no=1,
            source_checksum=f"sha256:fake_checksum_{i}",
            version_status=AssetVersionStatus.AVAILABLE,
        )
        session.add_all([ds, batch, raw, asset, version])
    session.commit()


@pytest.fixture(autouse=True)
def use_fake_ragflow(monkeypatch):
    """Force FakeRAGFlowAdapter for these tests so we don't hit a real RAGFlow.

    Two patches are needed: kb_registry pulls `get_ragflow_adapter` via
    `from ... import ...`, so the name inside `kb_registry`'s module
    globals is a frozen copy of the original. Patching `ra.get_ragflow_adapter`
    alone does NOT redirect `KbRegistry.__init__`'s lookup."""
    from nexus_app.index import kb_registry as kr
    from nexus_app.index import ragflow_adapter as ra
    fake = ra.FakeRAGFlowAdapter()
    monkeypatch.setattr(ra, "get_ragflow_adapter", lambda settings=None: fake)
    monkeypatch.setattr(kr, "get_ragflow_adapter", lambda settings=None: fake)
    kr._default_registry = None
    yield fake
    kr._default_registry = None


def _seed_caller(session) -> models.ApiCaller:
    caller = models.ApiCaller(
        caller_key="search-test-caller",
        name="Search Test",
        org_scope=["org-1"],
        permission_scope=[],
    )
    session.add(caller)
    session.commit()
    return caller


def _audits(session, event_type: AuditEventType) -> list[models.AuditLog]:
    return list(
        session.scalars(
            select(models.AuditLog).where(models.AuditLog.event_type == event_type)
        )
    )


def _auth_headers(caller_client_id: str) -> dict:
    # Auth middleware verifies by hashed key; for tests we mock by passing client_id
    # via the convention X-Api-Caller-Id (consult require_api_caller for actual scheme).
    return {"X-Api-Caller-Id": caller_client_id}


class TestSearchEndpoint:
    def test_search_returns_results_with_source_citation(self, app, session, monkeypatch):
        from nexus_api.api import internal as v1
        caller = _seed_caller(session)

        async def _override_caller():
            return caller

        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        resp = client.get("/open/v1/search?q=test+query&kb=textbook_kb&top_k=2")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "results" in data
        # Fake adapter populates nexus_* fields directly
        for hit in data["results"]:
            assert "normalized_ref_id" in hit
            assert "version_id" in hit
            assert "asset_id" in hit

    def test_search_writes_audit_event(self, app, session):
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        client.get("/open/v1/search?q=hello&kb=textbook_kb")
        events = _audits(session, AuditEventType.SEARCH_QUERY_EXECUTED)
        assert events
        last = events[-1]
        assert last.actor_id == caller.id
        assert last.summary["kb"] == "textbook_kb"
        assert "query_hash" in last.summary
        assert isinstance(last.summary.get("hit_normalized_ref_ids"), list)

    def test_search_audit_carries_data_source_ids(self, app, session):
        """Fake adapter emits distinct fake_ds_{i} per hit; audit must
        aggregate them distinct + sorted."""
        _seed_fake_chain(session, n=3)
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        client.get("/open/v1/search?q=ds-check&kb=textbook_kb&top_k=3")
        events = _audits(session, AuditEventType.SEARCH_QUERY_EXECUTED)
        last = events[-1]
        ds_ids = last.summary.get("data_source_ids")
        assert isinstance(ds_ids, list)
        assert ds_ids == sorted(ds_ids)
        # Fake adapter yields min(top_k,3) hits with distinct data_source_id
        assert ds_ids and len(set(ds_ids)) == len(ds_ids)


class TestQAEndpoint:
    def test_qa_returns_sources_with_citation(self, app, session):
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        resp = client.get("/open/v1/qa?q=what+is+x&kb=textbook_kb")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "answer" in data
        assert "sources" in data
        for src in data["sources"]:
            assert "normalized_ref_id" in src

    def test_qa_writes_audit_event(self, app, session):
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        client.get("/open/v1/qa?q=what+is+nexus&kb=textbook_kb")
        events = _audits(session, AuditEventType.QA_ANSWER_GENERATED)
        assert events
        last = events[-1]
        assert last.actor_id == caller.id
        assert "question_hash" in last.summary
        assert "cited_normalized_ref_ids" in last.summary

    def test_qa_audit_carries_answer_confidence(self, app, session):
        """Fake qa sources carry scores 0.8/0.7/0.6; derived confidence = max."""
        _seed_fake_chain(session, n=3)
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        resp = client.get("/open/v1/qa?q=conf-check&kb=textbook_kb&top_k=3")
        data = resp.json()["data"]
        assert data.get("answer_confidence") == pytest.approx(0.8)

        events = _audits(session, AuditEventType.QA_ANSWER_GENERATED)
        last = events[-1]
        assert last.summary.get("answer_confidence") == pytest.approx(0.8)
        ds_ids = last.summary.get("data_source_ids")
        assert isinstance(ds_ids, list) and ds_ids == sorted(ds_ids)

    def test_qa_no_sources_no_confidence(self, app, session, use_fake_ragflow):
        """When the adapter returns no sources, answer_confidence must be null."""
        def empty_qa(kb_id, question, top_k=5):
            return {"answer": "no sources", "sources": []}
        use_fake_ragflow.qa = empty_qa

        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        resp = client.get("/open/v1/qa?q=empty&kb=textbook_kb")
        data = resp.json()["data"]
        assert data.get("answer_confidence") is None

        events = _audits(session, AuditEventType.QA_ANSWER_GENERATED)
        last = events[-1]
        assert last.summary.get("answer_confidence") is None
        assert last.summary.get("data_source_ids") == []


class TestPermissionHookNoop:
    def test_filter_passes_hits_through_unchanged(self):
        from nexus_api.permissions import apply_permission_filter
        caller = type("C", (), {"id": "c1", "org_scope": ["org-1"]})()
        hits = [{"chunk_id": "x", "normalized_ref_id": "r1"}, {"chunk_id": "y"}]
        out = apply_permission_filter(caller, hits)
        assert len(out) == 2
        assert out is hits  # identity in P0 noop
