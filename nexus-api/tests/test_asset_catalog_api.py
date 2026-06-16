"""Asset catalog/detail read contract tests."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    GovernanceResultStatus,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)


def _seed_review_required_asset(session: Session):
    ds = models.DataSource(
        code="catalog-test-ds",
        name="Catalog Test DS",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(ds)
    session.flush()

    batch = models.IngestBatch(
        data_source_id=ds.id,
        idempotency_key="catalog-batch-001",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    session.add(batch)
    session.flush()

    raw = models.RawObject(
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        source_uri="file://catalog-test.pdf",
        object_uri="raw/catalog-test.pdf",
        checksum="catalog-raw-sha256",
        mime_type="application/pdf",
        size_bytes=4096,
        status=RawObjectStatus.RAW_PERSISTED,
    )
    session.add(raw)
    session.flush()

    asset = models.Asset(
        data_source_id=ds.id,
        source_object_key="catalog-test.pdf",
        title="Catalog Review Required Asset",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.REVIEW_REQUIRED,
    )
    session.add(asset)
    session.flush()

    version = models.AssetVersion(
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=7,
        source_checksum="catalog-raw-sha256",
        version_status=AssetVersionStatus.REVIEW_REQUIRED,
    )
    session.add(version)
    session.flush()

    ref = models.NormalizedAssetRef(
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="normalized/catalog-test.json",
        schema_version="1.0",
        checksum="catalog-normalized-sha256",
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=3,
        record_count=0,
        source_type="file_upload",
        content_type="document",
        title="Catalog Review Required Asset",
        language="zh-CN",
        governance={"classification": "industry_report", "level": "L1"},
        quality={"quality_level": "warning"},
        lineage={"raw_object_id": raw.id},
        metadata_summary={"content_snippet": "review required content"},
    )
    session.add(ref)
    session.flush()

    run = models.AIGovernanceRun(
        normalized_ref_id=ref.id,
        profile_id=None,
        model_alias="doubao-seed-2-0-lite-260215",
        prompt_version="v1.0",
        input_hash="catalog-input-hash",
        input_summary={"normalized_ref_id": ref.id},
        raw_output="{}",
        ai_output={
            "classification": "industry_report",
            "classification_name": "产业报告",
            "level": "L1",
            "confidence": 0.83,
            "tags": ["report"],
        },
        quality_summary={
            "quality_score": 69.83,
            "quality_level": "warning",
            "confidence": 0.83,
            "blocking_reasons": ["Missing content"],
        },
        validation_status=AIGovernanceRunValidationStatus.SCHEMA_VALID,
        adoption_status=AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED,
    )
    session.add(run)
    session.flush()

    result = models.GovernanceResult(
        normalized_ref_id=ref.id,
        ai_run_id=run.id,
        classification="industry_report",
        level="L1",
        tags=["report"],
        org_scope="all",
        index_admission=False,
        quality_summary={
            "quality_score": 69.83,
            "quality_level": "warning",
            "confidence": 0.83,
            "blocking_reasons": ["Missing content"],
        },
        decision_trail=[{"decision": "review_required"}],
        rules_schema_version="1.0",
        rules_content_hash="rules-hash",
        status=GovernanceResultStatus.REVIEW_REQUIRED,
    )
    session.add(result)
    session.commit()

    return {"asset": asset, "version": version, "ref": ref, "run": run, "result": result}


def test_review_required_asset_detail_exposes_latest_read_models(app, session):
    seeded = _seed_review_required_asset(session)
    client = TestClient(app)

    resp = client.get(f"/internal/v1/assets/{seeded['asset'].id}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["current_version"] is None
    assert data["current_normalized_ref"] is None
    assert data["latest_version"]["id"] == seeded["version"].id
    assert data["latest_version"]["version_status"] == "review_required"
    assert data["latest_normalized_ref"]["id"] == seeded["ref"].id
    assert data["latest_governance_result"]["id"] == seeded["result"].id
    assert data["latest_governance_result"]["classification"] == "industry_report"
    assert data["latest_governance_result"]["quality_summary"]["quality_score"] == 69.83


def test_asset_catalog_uses_latest_review_required_ref_for_ui_metadata(app, session):
    seeded = _seed_review_required_asset(session)
    client = TestClient(app)

    resp = client.get("/internal/v1/assets")

    assert resp.status_code == 200
    rows = resp.json()["data"]
    row = next(item for item in rows if item["id"] == seeded["asset"].id)
    assert row["status"] == "review_required"
    assert row["current_version_no"] == 7
    assert row["current_normalized_ref_id"] == seeded["ref"].id
    assert row["latest_version_id"] == seeded["version"].id
    assert row["latest_normalized_ref_id"] == seeded["ref"].id
    assert row["domain"] == "industry_report"
    assert row["domain_name"] == "产业报告"
    assert row["level"] == "L1"
    assert row["quality_score"] == 69.83
    assert row["governance_status"] == "review_required"


def test_asset_summary_counts_review_required_assets_with_latest_refs(app, session):
    _seed_review_required_asset(session)
    client = TestClient(app)

    resp = client.get("/internal/v1/assets/summary")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["available"] == 0
    assert data["review_required"] == 1
    assert data["current_normalized_refs"] == 1
    assert data["domain_distribution"] == [
        {"domain": "industry_report", "name": "产业报告", "count": 1}
    ]


def test_latest_ref_can_fetch_ai_governance_runs(app, session):
    seeded = _seed_review_required_asset(session)
    client = TestClient(app)

    resp = client.get(
        f"/internal/v1/ai/governance-runs?normalized_ref_id={seeded['ref'].id}"
    )

    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == seeded["run"].id
    assert rows[0]["ai_output"]["classification"] == "industry_report"
    assert rows[0]["quality_summary"]["quality_score"] == 69.83
