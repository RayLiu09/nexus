"""Query-shape regression tests for the Console governance-review queue."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    GovernanceResultStatus,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)


def _seed_pending_review(session, *, suffix: str) -> dict[str, str]:
    source = models.DataSource(
        id=f"review-source-{suffix}",
        code=f"review-source-{suffix}",
        name=f"Review source {suffix}",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id=f"review-batch-{suffix}",
        data_source_id=source.id,
        idempotency_key=f"review-batch-{suffix}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"review-raw-{suffix}",
        batch_id=batch.id,
        data_source_id=source.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"raw/review-{suffix}.pdf",
        checksum=f"review-raw-{suffix}",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"review-asset-{suffix}",
        data_source_id=source.id,
        source_object_key=f"review-{suffix}.pdf",
        title=f"Review asset {suffix}",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.REVIEW_REQUIRED,
    )
    version = models.AssetVersion(
        id=f"review-version-{suffix}",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.REVIEW_REQUIRED,
    )
    ref = models.NormalizedAssetRef(
        id=f"review-ref-{suffix}",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri=f"normalized/review-{suffix}.json",
        schema_version="1.0",
        checksum=f"review-ref-{suffix}",
        status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload",
        content_type="document",
        title=asset.title,
        language="zh-CN",
        governance={},
        quality={},
        lineage={},
        metadata_summary={},
    )
    result = models.GovernanceResult(
        id=f"review-result-{suffix}",
        normalized_ref_id=ref.id,
        classification="industry_report",
        level="L1",
        tags=[],
        org_scope="all",
        index_admission=False,
        quality_summary={"quality_level": "warning"},
        decision_trail=[],
        rules_schema_version="1.0",
        rules_content_hash=f"review-rules-{suffix}",
        status=GovernanceResultStatus.REVIEW_REQUIRED,
    )
    session.add_all([source, batch, raw, asset, version, ref, result])
    session.commit()
    return {"ref_id": ref.id}


def test_pending_review_queue_uses_sql_pagination_and_bounded_query_count(app, session):
    for number in range(6):
        _seed_pending_review(session, suffix=str(number))
    statements: list[str] = []

    def count_statement(conn, cursor, statement, parameters, context, executemany):
        del conn, cursor, parameters, context, executemany
        statements.append(statement)

    event.listen(session.bind, "before_cursor_execute", count_statement)
    try:
        response = TestClient(app).get(
            "/internal/v1/governance-reviews/pending?page=2&pageSize=2"
        )
    finally:
        event.remove(session.bind, "before_cursor_execute", count_statement)

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 6
    assert len(payload["data"]) == 2
    # Count, page IDs, and one joined queue-row query.
    assert len(statements) <= 3


def test_pending_review_count_is_lightweight(app, session):
    for number in range(3):
        _seed_pending_review(session, suffix=f"count-{number}")

    response = TestClient(app).get("/internal/v1/governance-reviews/pending/count")

    assert response.status_code == 200
    assert response.json()["data"] == {"total": 3}


def test_pending_queue_hides_review_snapshot_superseded_by_newer_result(app, session):
    seeded = _seed_pending_review(session, suffix="superseded")
    session.add(
        models.GovernanceResult(
            id="review-result-superseded-available",
            normalized_ref_id=seeded["ref_id"],
            classification="industry_report",
            level="L1",
            tags=[],
            org_scope="all",
            index_admission=True,
            quality_summary={"quality_level": "pass"},
            decision_trail=[],
            rules_schema_version="1.0",
            rules_content_hash="review-rules-superseded-available",
            status=GovernanceResultStatus.AVAILABLE,
            created_at=datetime.now(timezone.utc) + timedelta(seconds=1),
        )
    )
    session.commit()

    response = TestClient(app).get("/internal/v1/governance-reviews/pending")

    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 0
    assert response.json()["data"] == []
