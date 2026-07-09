"""Review queue API — list / detail / approve / override / dismiss."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)


def _seed_ref_and_items(session, ref_id: str = "ref-review-api"):
    ds = models.DataSource(id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="src",
                           source_type=DataSourceType.FILE_UPLOAD)
    batch = models.IngestBatch(id=f"b-{ref_id}", data_source_id=ds.id,
                               idempotency_key=f"idem-{ref_id}",
                               source_type=DataSourceType.FILE_UPLOAD,
                               status=IngestBatchStatus.COMPLETED)
    raw = models.RawObject(id=f"r-{ref_id}", batch_id=batch.id, data_source_id=ds.id,
                           source_type=DataSourceType.FILE_UPLOAD,
                           object_uri="s3://x/y.pdf", checksum=f"cs-{ref_id}",
                           mime_type="application/pdf",
                           status=RawObjectStatus.RAW_PERSISTED)
    asset = models.Asset(id=f"a-{ref_id}", data_source_id=ds.id,
                         source_object_key=f"{ref_id}.pdf", title="T",
                         asset_kind=AssetKind.DOCUMENT,
                         status=AssetVersionStatus.PROCESSING)
    version = models.AssetVersion(id=f"v-{ref_id}", asset_id=asset.id,
                                  raw_object_id=raw.id, version_no=1,
                                  source_checksum=raw.checksum,
                                  version_status=AssetVersionStatus.PROCESSING)
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri=f"s3://x/{ref_id}.json",
        schema_version="normalized-document-v1", checksum=f"nc-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=3, record_count=0,
    )
    run = models.AIGovernanceRun(
        id=f"run-{ref_id}", normalized_ref_id=ref.id,
        model_alias="fake", prompt_version="v1",
        input_hash="0" * 64, input_summary={}, ai_output={},
        validation_status=AIGovernanceRunValidationStatus.SCHEMA_VALID,
        adoption_status=AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED,
    )
    items = [
        models.KnowledgeOutlineReviewItem(
            id=f"it-{i}",
            normalized_ref_id=ref.id, ai_run_id=run.id,
            heading_block_id=f"b{i}", heading_text=f"标题 {i}",
            llm_label="knowledge_point",
            llm_confidence=Decimal("0.600"),
            llm_reason="mid confidence",
            confidence_bucket="mid",
            status="pending",
        )
        for i in range(3)
    ]
    session.add_all([ds, batch, raw, asset, version, ref, run, *items])
    session.commit()
    return ref, items


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_returns_pending_reviews(app, session):
    ref, _ = _seed_ref_and_items(session)
    with TestClient(app) as client:
        resp = client.get(
            f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline-reviews",
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ref_id"] == ref.id
    assert len(data["items"]) == 3
    labels = {i["llm_label"] for i in data["items"]}
    assert labels == {"knowledge_point"}


def test_list_404_when_ref_missing(app, session):
    with TestClient(app) as client:
        resp = client.get(
            "/internal/v1/normalized-refs/does-not-exist/knowledge-outline-reviews",
        )
    assert resp.status_code == 404


def test_list_400_when_status_invalid(app, session):
    ref, _ = _seed_ref_and_items(session, "ref-badstatus")
    with TestClient(app) as client:
        resp = client.get(
            f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline-reviews"
            "?status=made-up-status",
        )
    assert resp.status_code == 400


def test_list_all_returns_all_statuses(app, session):
    ref, items = _seed_ref_and_items(session, "ref-all")
    items[0].status = "approved"
    items[1].status = "overridden"
    session.commit()
    with TestClient(app) as client:
        resp = client.get(
            f"/internal/v1/normalized-refs/{ref.id}/knowledge-outline-reviews"
            "?status=all",
        )
    assert resp.status_code == 200
    statuses = {i["status"] for i in resp.json()["data"]["items"]}
    assert statuses == {"pending", "approved", "overridden"}


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


def test_detail_returns_item(app, session):
    _, items = _seed_ref_and_items(session, "ref-detail")
    with TestClient(app) as client:
        resp = client.get(
            f"/internal/v1/knowledge-outline-reviews/{items[0].id}",
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == items[0].id
    assert data["heading_block_id"] == "b0"


def test_detail_404_when_missing(app, session):
    with TestClient(app) as client:
        resp = client.get("/internal/v1/knowledge-outline-reviews/missing")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# SME actions
# ---------------------------------------------------------------------------


def test_approve_flips_status(app, session):
    _, items = _seed_ref_and_items(session, "ref-approve")
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/v1/knowledge-outline-reviews/{items[0].id}/approve",
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "approved"
    assert data["sme_override_by"]


def test_override_stores_label_and_reason(app, session):
    _, items = _seed_ref_and_items(session, "ref-override")
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/v1/knowledge-outline-reviews/{items[0].id}/override",
            json={"label": "chapter", "reason": "LLM 判定为知识点，实为章"},
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "overridden"
    assert data["sme_override_label"] == "chapter"
    assert data["sme_override_reason"] == "LLM 判定为知识点，实为章"


def test_override_rejects_invalid_label(app, session):
    _, items = _seed_ref_and_items(session, "ref-badlabel")
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/v1/knowledge-outline-reviews/{items[0].id}/override",
            json={"label": "not-a-taxonomy-label", "reason": None},
        )
    assert resp.status_code == 400


def test_dismiss_flips_status(app, session):
    _, items = _seed_ref_and_items(session, "ref-dismiss")
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/v1/knowledge-outline-reviews/{items[0].id}/dismiss",
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "dismissed"


def test_actions_404_when_item_missing(app, session):
    with TestClient(app) as client:
        for suffix in ("approve", "dismiss"):
            resp = client.post(
                f"/internal/v1/knowledge-outline-reviews/missing/{suffix}",
            )
            assert resp.status_code == 404
        resp = client.post(
            "/internal/v1/knowledge-outline-reviews/missing/override",
            json={"label": "chapter", "reason": None},
        )
        assert resp.status_code == 404
