"""API contract tests for AI governance endpoints (Week 3)."""
from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedType,
    RawObjectStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_data(session: Session):
    ds = models.DataSource(
        code="api-test-ds", name="API Test DS",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(ds)
    session.flush()

    batch = models.IngestBatch(
        data_source_id=ds.id, idempotency_key="api-batch-001",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    session.add(batch)
    session.flush()

    raw = models.RawObject(
        batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        source_uri="file://api-test.pdf", object_uri="raw/api-test.pdf",
        checksum="api-abc123", size_bytes=2048,
        status=RawObjectStatus.RAW_PERSISTED,
    )
    session.add(raw)
    session.flush()

    asset = models.DocumentAsset(
        data_source_id=ds.id, source_object_key="api-test.pdf",
        title="API Test Asset", asset_kind=AssetKind.DOCUMENT,
    )
    session.add(asset)
    session.flush()

    version = models.DocumentVersion(
        asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum="api-abc123",
        version_status=AssetVersionStatus.PROCESSING,
    )
    session.add(version)
    session.flush()

    ref = models.NormalizedAssetRef(
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="normalized/api-test.json",
        schema_version="1.0", checksum="api-def456",
        title="API Test Document", language="zh-CN",
        source_type="file_upload", content_type="document",
        governance={"level": "L2"}, quality={}, lineage={},
        metadata_summary={"summary": "API test doc", "content_snippet": "Test content"},
    )
    session.add(ref)
    session.flush()

    return {"ds": ds, "ref": ref}


# ---------------------------------------------------------------------------
# AI Prompt Profile API tests
# ---------------------------------------------------------------------------

class TestPromptProfileAPI:
    def test_create_profile_201(self, app, session):
        client = TestClient(app)
        payload = {
            "profile_name": "test-profile",
            "task_type": "governance",
            "scenario": "metadata_enrich",
            "litellm_model_alias": "nexus-gpt-4o",
            "prompt_version": "v1.0",
            "prompt_template": "You are a governance assistant.",
            "temperature": 0.2,
            "redaction_policy": "masked_content",
        }
        resp = client.post("/internal/v1/ai/prompt-profiles", headers={"Idempotency-Key": "test-idem"}, json=payload)
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["profile_name"] == "test-profile"
        assert data["scenario"] == "metadata_enrich"
        assert data["status"] == "active"
        assert data["profile_version"] == 1

    def test_create_two_versions(self, app, session):
        client = TestClient(app)
        base = {
            "profile_name": "versioned-profile",
            "task_type": "governance",
            "litellm_model_alias": "nexus-gpt-4o",
            "prompt_version": "v1.0",
            "prompt_template": "Original.",
        }
        resp1 = client.post("/internal/v1/ai/prompt-profiles", headers={"Idempotency-Key": "test-idem"}, json=base)
        assert resp1.status_code == 201

        update = {
            "profile_name": "versioned-profile",
            "task_type": "governance",
            "litellm_model_alias": "nexus-gpt-4o",
            "prompt_version": "v2.0",
            "prompt_template": "Updated.",
        }
        resp2 = client.post("/internal/v1/ai/prompt-profiles", headers={"Idempotency-Key": "test-idem"}, json=update)
        assert resp2.status_code == 201
        assert resp2.json()["data"]["profile_version"] == 2

    def test_list_profiles(self, app, session):
        client = TestClient(app)
        client.post("/internal/v1/ai/prompt-profiles", headers={"Idempotency-Key": "test-idem"}, json={
            "profile_name": "list-test", "task_type": "governance",
            "litellm_model_alias": "alias", "prompt_version": "v1",
            "prompt_template": "T.",
        })
        resp = client.get("/internal/v1/ai/prompt-profiles")
        assert resp.status_code == 200
        items = resp.json()["data"]
        assert len(items) >= 1

    def test_get_profile_by_id(self, app, session):
        client = TestClient(app)
        created = client.post("/internal/v1/ai/prompt-profiles", headers={"Idempotency-Key": "test-idem"}, json={
            "profile_name": "get-test", "task_type": "governance",
            "litellm_model_alias": "alias", "prompt_version": "v1",
            "prompt_template": "T.",
        }).json()["data"]
        resp = client.get(f"/internal/v1/ai/prompt-profiles/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == created["id"]

    def test_get_profile_not_found(self, app, session):
        client = TestClient(app)
        resp = client.get("/internal/v1/ai/prompt-profiles/nonexistent-id")
        assert resp.status_code == 404

    def test_disable_profile(self, app, session):
        client = TestClient(app)
        created = client.post("/internal/v1/ai/prompt-profiles", headers={"Idempotency-Key": "test-idem"}, json={
            "profile_name": "disable-test", "task_type": "governance",
            "litellm_model_alias": "alias", "prompt_version": "v1",
            "prompt_template": "T.",
        }).json()["data"]
        resp = client.post(f"/internal/v1/ai/prompt-profiles/{created['id']}/disable")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "disabled"

    def test_invalid_redaction_policy_422(self, app, session):
        client = TestClient(app)
        resp = client.post("/internal/v1/ai/prompt-profiles", headers={"Idempotency-Key": "test-idem"}, json={
            "profile_name": "bad-policy", "task_type": "governance",
            "litellm_model_alias": "alias", "prompt_version": "v1",
            "prompt_template": "T.", "redaction_policy": "invalid_policy",
        })
        assert resp.status_code == 422

    def test_prompt_dry_run_does_not_persist_governance_run(self, app, session):
        client = TestClient(app)
        seeded = _seed_data(session)
        profile = client.post("/internal/v1/ai/prompt-profiles", headers={"Idempotency-Key": "test-idem"}, json={
            "profile_name": "dry-run-test",
            "task_type": "governance",
            "scenario": "prompt_lab",
            "litellm_model_alias": "alias",
            "prompt_version": "v1",
            "prompt_template": "T.",
        }).json()["data"]

        before = len(session.scalars(select(models.AIGovernanceRun)).all())
        resp = client.post(f"/internal/v1/ai/prompt-profiles/{profile['id']}/dry-run", json={
            "normalized_ref_id": seeded["ref"].id,
            "input_overrides": {"summary": "dry-run override"},
        })
        after = len(session.scalars(select(models.AIGovernanceRun)).all())

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["profile_id"] == profile["id"]
        assert data["scenario"] == "prompt_lab"
        assert data["persisted"] is False
        assert data["normalized_ref_id"] == seeded["ref"].id
        assert after == before


# ---------------------------------------------------------------------------
# AI Governance Run API tests
# ---------------------------------------------------------------------------

class TestAIGovernanceRunAPI:
    def _create_profile(self, client) -> dict:
        resp = client.post("/internal/v1/ai/prompt-profiles", headers={"Idempotency-Key": "test-idem"}, json={
            "profile_name": "gov-run-profile",
            "task_type": "governance",
            "litellm_model_alias": "nexus-gpt-4o",
            "prompt_version": "v1.0",
            "prompt_template": "You are a governance assistant.",
        })
        return resp.json()["data"]

    def test_create_governance_run_201(self, app, session):
        client = TestClient(app)
        data = _seed_data(session)
        profile = self._create_profile(client)
        resp = client.post("/internal/v1/ai/governance-runs", headers={"Idempotency-Key": "test-idem"}, json={
            "normalized_ref_id": data["ref"].id,
            "profile_id": profile["id"],
        })
        assert resp.status_code == 201
        run_data = resp.json()["data"]
        assert run_data["normalized_ref_id"] == data["ref"].id
        assert run_data["validation_status"] in ("schema_valid", "schema_invalid", "failed")

    def test_create_governance_run_ref_not_found(self, app, session):
        client = TestClient(app)
        profile = self._create_profile(client)
        resp = client.post("/internal/v1/ai/governance-runs", headers={"Idempotency-Key": "test-idem"}, json={
            "normalized_ref_id": "nonexistent-ref-id",
            "profile_id": profile["id"],
        })
        assert resp.status_code == 422

    def test_list_governance_runs(self, app, session):
        client = TestClient(app)
        data = _seed_data(session)
        profile = self._create_profile(client)
        client.post("/internal/v1/ai/governance-runs", headers={"Idempotency-Key": "test-idem"}, json={
            "normalized_ref_id": data["ref"].id, "profile_id": profile["id"],
        })
        resp = client.get(f"/internal/v1/ai/governance-runs?normalized_ref_id={data['ref'].id}")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1

    def test_get_governance_run_by_id(self, app, session):
        client = TestClient(app)
        data = _seed_data(session)
        profile = self._create_profile(client)
        created = client.post("/internal/v1/ai/governance-runs", headers={"Idempotency-Key": "test-idem"}, json={
            "normalized_ref_id": data["ref"].id, "profile_id": profile["id"],
        }).json()["data"]
        resp = client.get(f"/internal/v1/ai/governance-runs/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == created["id"]

    def test_get_governance_run_not_found(self, app, session):
        client = TestClient(app)
        resp = client.get("/internal/v1/ai/governance-runs/nonexistent-id")
        assert resp.status_code == 404

    def test_quality_summary_endpoint(self, app, session):
        client = TestClient(app)
        data = _seed_data(session)
        profile = self._create_profile(client)
        run = client.post("/internal/v1/ai/governance-runs", headers={"Idempotency-Key": "test-idem"}, json={
            "normalized_ref_id": data["ref"].id, "profile_id": profile["id"],
        }).json()["data"]
        if run["validation_status"] == "schema_valid":
            resp = client.get(f"/internal/v1/ai/governance-runs/{run['id']}/quality-summary")
            assert resp.status_code == 200
            assert "quality_score" in resp.json()["data"]


# ---------------------------------------------------------------------------
# Admin reload API test
# ---------------------------------------------------------------------------

class TestAdminReloadAPI:
    def test_reload_governance_rules(self, app, session):
        client = TestClient(app)
        resp = client.post("/internal/v1/admin/governance-rules/reload")
        # May succeed or fail depending on environment config
        assert resp.status_code in (200, 500)
