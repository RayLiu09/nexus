"""Asset catalog/detail read contract tests."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from nexus_api.api.internal.assets import get_catalog_tag_embedding_client
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
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)
from nexus_app.index.embedding_client import EmbeddingResult


_SEMANTIC_VECTOR = [1.0] + [0.0] * 511


class _SemanticEmbeddingClient:
    def embed_texts(self, texts, *, model_alias=None, expected_dimension=None):
        assert expected_dimension == 512
        return EmbeddingResult(
            vectors=[_SEMANTIC_VECTOR for _ in texts],
            model_alias="test-semantic",
            dimension=512,
            request_id="test-semantic-request",
            latency_ms=0.0,
            input_hashes=[],
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


def _seed_processing_asset(session: Session):
    ds = models.DataSource(
        code="catalog-test-processing-ds",
        name="Catalog Processing DS",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(ds)
    session.flush()

    batch = models.IngestBatch(
        data_source_id=ds.id,
        idempotency_key="catalog-batch-processing",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    session.add(batch)
    session.flush()

    raw = models.RawObject(
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        source_uri="file://catalog-processing.pdf",
        object_uri="raw/catalog-processing.pdf",
        checksum="catalog-processing-raw-sha256",
        mime_type="application/pdf",
        size_bytes=1024,
        status=RawObjectStatus.RAW_PERSISTED,
    )
    session.add(raw)
    session.flush()

    asset = models.Asset(
        data_source_id=ds.id,
        source_object_key="catalog-processing.pdf",
        title="Catalog Processing Asset",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    session.add(asset)
    session.flush()

    version = models.AssetVersion(
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum="catalog-processing-raw-sha256",
        version_status=AssetVersionStatus.PROCESSING,
    )
    session.add(version)
    session.commit()
    return {"asset": asset, "version": version}


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


def test_asset_catalog_uses_effective_version_status_when_asset_projection_is_stale(
    app, session
):
    seeded = _seed_review_required_asset(session)
    seeded["version"].version_status = AssetVersionStatus.AVAILABLE
    # Simulate a legacy review completion that updated only the version.
    seeded["asset"].status = AssetVersionStatus.REVIEW_REQUIRED
    seeded["result"].status = GovernanceResultStatus.AVAILABLE
    seeded["result"].index_admission = True
    seeded["result"].quality_summary = {"quality_level": "pass"}
    session.commit()

    with TestClient(app) as client:
        resp = client.get("/internal/v1/assets")

    assert resp.status_code == 200
    row = next(item for item in resp.json()["data"] if item["id"] == seeded["asset"].id)
    assert row["status"] == "available"


def test_asset_catalog_canonicalizes_deprecated_program_profile_domain(app, session):
    seeded = _seed_review_required_asset(session)
    seeded["result"].classification = "program_profile"
    session.commit()
    client = TestClient(app)

    resp = client.get("/internal/v1/assets")

    assert resp.status_code == 200
    rows = resp.json()["data"]
    row = next(item for item in rows if item["id"] == seeded["asset"].id)
    assert row["domain"] == "major_profile"
    assert row["domain_name"] == "专业简介"


def test_asset_catalog_labels_course_textbook_domain(app, session):
    seeded = _seed_review_required_asset(session)
    seeded["result"].classification = "course_textbook"
    session.commit()

    with TestClient(app) as client:
        resp = client.get("/internal/v1/assets")

    assert resp.status_code == 200
    row = resp.json()["data"][0]
    assert row["domain"] == "course_textbook"
    assert row["domain_name"] == "教材"


def test_asset_catalog_filters_by_domain_level_and_status(app, session):
    seeded = _seed_review_required_asset(session)
    _seed_processing_asset(session)
    client = TestClient(app)

    resp = client.get("/internal/v1/assets?domain=industry_report&level=L1&status=visible")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["meta"]["total"] == 1
    assert [row["id"] for row in payload["data"]] == [seeded["asset"].id]

    resp = client.get("/internal/v1/assets?domain=industry_report&level=L3&status=visible")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["meta"]["total"] == 0
    assert payload["data"] == []


def test_disabled_asset_is_hidden_by_default_but_available_to_explicit_audit_filter(app, session):
    seeded = _seed_review_required_asset(session)
    seeded["asset"].status = AssetVersionStatus.DISABLED
    seeded["version"].version_status = AssetVersionStatus.DISABLED
    seeded["result"].status = GovernanceResultStatus.DISABLED
    session.commit()
    client = TestClient(app)

    default_response = client.get("/internal/v1/assets")
    assert default_response.status_code == 200
    assert default_response.json()["meta"]["total"] == 0

    audit_response = client.get("/internal/v1/assets?status=disabled")
    assert audit_response.status_code == 200
    assert audit_response.json()["meta"]["total"] == 1
    assert audit_response.json()["data"][0]["id"] == seeded["asset"].id


def test_asset_catalog_filters_by_normalized_asset_tags(app, session):
    seeded = _seed_review_required_asset(session)
    session.add(models.TagAssetIndex(
        tag_type="topic",
        tag_value="跨境电子商务",
        tag_value_normalized="跨境电子商务",
        target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        target_id=seeded["ref"].id,
        asset_version_id=seeded["version"].id,
        source=TagAssetIndexSource.GOVERNANCE_TAG,
    ))
    session.commit()
    client = TestClient(app)

    resp = client.get("/internal/v1/assets?status=visible&tags=跨境电子商务")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["meta"]["total"] == 1
    assert [row["id"] for row in payload["data"]] == [seeded["asset"].id]

    resp = client.get("/internal/v1/assets?status=visible&tags=无关标签")

    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] == 0


def test_asset_catalog_filters_by_semantic_tags(app, session):
    seeded = _seed_review_required_asset(session)
    session.add(models.TagAssetIndex(
        tag_type="topic",
        tag_value="跨境电子商务",
        tag_value_normalized="跨境电子商务",
        target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        target_id=seeded["ref"].id,
        asset_version_id=seeded["version"].id,
        source=TagAssetIndexSource.GOVERNANCE_TAG,
        tag_embedding=_SEMANTIC_VECTOR,
    ))
    session.commit()
    app.dependency_overrides[get_catalog_tag_embedding_client] = lambda: _SemanticEmbeddingClient
    client = TestClient(app)

    response = client.get("/internal/v1/assets?status=visible&tags=跨境电商")

    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 1
    assert response.json()["data"][0]["id"] == seeded["asset"].id


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
