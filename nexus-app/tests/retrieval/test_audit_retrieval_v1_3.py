"""PR-12 guards for retrieval-side audit events.

Verifies that:

* ``RETRIEVAL_TAG_FILTER_APPLIED`` fires per sub_query with declared
  tag_filters and carries the expected summary shape.
* Pass-through sub_queries (no tag_filters) produce no Phase A audit.
* ``RETRIEVAL_DAG_EXECUTED`` fires once per plan and captures the
  layer structure.
* Audit write failures don't abort retrieval (best-effort contract).
"""

from __future__ import annotations

from typing import Any

import pytest

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)
from nexus_app.retrieval.executors.job_demand import JobDemandRetrievalExecutor
from nexus_app.retrieval.executors.major_distribution import (
    MajorDistributionRetrievalExecutor,
)
from nexus_app.retrieval.executors.unstructured import UnstructuredRetrievalExecutor
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalChannel,
    RetrievalPlan,
    RetrievalSubQuery,
    StepStatus,
    StructuredPlan,
    UnstructuredPlan,
)
from nexus_app.retrieval.tag_schemas import TagFilter


# ---------------------------------------------------------------------------
# Seed helpers (small variants of PR-9/PR-10 fixtures)
# ---------------------------------------------------------------------------


def _seed_major_distribution_min(session) -> dict[str, str]:
    ds = models.DataSource(
        id="ds-md-a", code="ds-md-a", name="md",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-md-a", data_source_id=ds.id, idempotency_key="idem-md-a",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-md-a", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://x/md.xlsx", checksum="raw-md-a",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="asset-md-a", data_source_id=ds.id, source_object_key="md.xlsx",
        title="md", asset_kind=AssetKind.RECORD,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="version-md-a", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id="ref-md-a", version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://x/md.json", schema_version="normalized-record.v2",
        checksum="ref-md-a", status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload", content_type="table_sheet",
        title="md", language="zh-CN",
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": "major_distribution.v1"},
    )
    dataset = models.MajorDistributionDataset(
        id="dataset-md-a", normalized_ref_id=ref.id,
        asset_version_id=version.id, dataset_name="md-ds",
        source_channel="xlsx", major_scope="single_major",
        major_name="电子商务", major_code="530701", education_level="高职",
        year_min=2024, year_max=2026, province_count=1, record_count=1,
        schema_version="major_distribution.v1", quality_summary={},
    )
    record = models.MajorDistributionRecord(
        id="record-md-a", dataset_id=dataset.id, normalized_ref_id=ref.id,
        source_record_key="2024-zj", source_row_no="2", year=2024,
        year_text="2024", province_name="浙江", region_scope="province",
        major_name="电子商务", major_code="530701", education_level="高职",
        distribution_count=3, quality_flags={}, trace={},
    )
    session.add_all([ds, batch, raw, asset, version, ref, dataset, record])
    session.commit()
    return {"version_id": version.id, "record_id": record.id}


def _seed_tag_index(
    session,
    *,
    target_type: TagAssetIndexTargetType,
    target_id: str,
    asset_version_id: str,
    tag_type: str,
    tag_value: str,
) -> None:
    session.add(models.TagAssetIndex(
        tag_type=tag_type,
        tag_value=tag_value,
        tag_value_normalized=tag_value,
        target_type=target_type,
        target_id=target_id,
        asset_version_id=asset_version_id,
        source=TagAssetIndexSource.FIELD_PROJECTION,
        tag_embedding=None,
    ))
    session.commit()


def _audit_rows(session, event_type: AuditEventType) -> list[models.AuditLog]:
    return (
        session.query(models.AuditLog)
        .filter(models.AuditLog.event_type == event_type)
        .order_by(models.AuditLog.created_at.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# TagFilterAudit — structured executor
# ---------------------------------------------------------------------------


class TestTagFilterAuditStructured:
    def test_tag_filter_audit_written_for_narrowed_query(self, session):
        seeded = _seed_major_distribution_min(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_id"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="浙江",
        )
        executor = MajorDistributionRetrievalExecutor()
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "major_distribution", "purpose": "test",
            "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags=["浙江"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
        })
        result = executor.execute(session, sub_query)
        assert result.status == StepStatus.COMPLETED

        rows = _audit_rows(session, AuditEventType.RETRIEVAL_TAG_FILTER_APPLIED)
        assert len(rows) == 1
        row = rows[0]
        assert row.target_type == "retrieval_sub_query"
        assert row.target_id == "q1"
        summary = row.summary
        assert summary["sub_query_id"] == "q1"
        assert summary["profile_key"] == "major_distribution.record_list"
        assert summary["tag_target_type"] == "major_distribution_record"
        assert summary["target_ids_count"] == 1
        assert summary["bucket_hit_counts"] == {"regions": 1}
        assert summary["applied"] is True
        assert summary["declared_buckets"] == ["regions"]

    def test_no_audit_when_no_tag_filters(self, session):
        _seed_major_distribution_min(session)
        executor = MajorDistributionRetrievalExecutor()
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "major_distribution", "purpose": "test",
            "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
            },
        })
        executor.execute(session, sub_query)
        assert _audit_rows(session, AuditEventType.RETRIEVAL_TAG_FILTER_APPLIED) == []

    def test_tag_filter_audit_captures_empty_intersection(self, session):
        seeded = _seed_major_distribution_min(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_id"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="浙江",
        )
        executor = MajorDistributionRetrievalExecutor()
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q_empty", "channel": "structured",
            "domain": "major_distribution", "purpose": "test",
            "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(tags=["浙江"], match_strategy="l1|l1.5").model_dump(),
                "majors": TagFilter(tags=["不存在"], match_strategy="l1|l1.5").model_dump(),
            },
        })
        result = executor.execute(session, sub_query)
        assert result.records == []
        rows = _audit_rows(session, AuditEventType.RETRIEVAL_TAG_FILTER_APPLIED)
        assert len(rows) == 1
        summary = rows[0].summary
        assert summary["target_ids_count"] == 0
        assert "tag_filters_empty_intersection" in summary["warnings"]


# ---------------------------------------------------------------------------
# TagFilterAudit — unstructured executor
# ---------------------------------------------------------------------------


class _FakeSearchAdapter:
    def __init__(self, hits: list[dict[str, Any]]):
        self._hits = hits
        self.calls: list[dict[str, Any]] = []

    def search(
        self, session, *, query, knowledge_type_code=None,
        top_k=10, similarity_threshold=0.7, normalized_ref_ids=None,
        chunk_ids=None,
    ):
        self.calls.append({
            "normalized_ref_ids": (
                sorted(normalized_ref_ids)
                if normalized_ref_ids is not None else None
            ),
            "chunk_ids": (
                sorted(chunk_ids) if chunk_ids is not None else None
            ),
        })
        if normalized_ref_ids is not None and not normalized_ref_ids:
            return []
        if chunk_ids is not None and not chunk_ids:
            return []
        return self._hits[:top_k]


class TestTagFilterAuditUnstructured:
    def test_unstructured_tag_filter_writes_audit(self, session):
        # Seed a normalized_ref so the tag_index has a valid asset_version_id.
        # Use PR-10's minimal course_textbook fixture inline.
        ds = models.DataSource(
            id="ds-us", code="ds-us", name="ds",
            source_type=DataSourceType.FILE_UPLOAD,
        )
        batch = models.IngestBatch(
            id="batch-us", data_source_id=ds.id, idempotency_key="idem-us",
            source_type=DataSourceType.FILE_UPLOAD,
            status=IngestBatchStatus.COMPLETED,
        )
        raw = models.RawObject(
            id="raw-us", batch_id=batch.id, data_source_id=ds.id,
            source_type=DataSourceType.FILE_UPLOAD,
            object_uri="s3://x/us.md", checksum="raw-us",
            status=RawObjectStatus.RAW_PERSISTED,
        )
        asset = models.Asset(
            id="asset-us", data_source_id=ds.id, source_object_key="us.md",
            title="教材", asset_kind=AssetKind.DOCUMENT,
            status=AssetVersionStatus.AVAILABLE,
        )
        version = models.AssetVersion(
            id="version-us", asset_id=asset.id, raw_object_id=raw.id,
            version_no=1, source_checksum=raw.checksum,
            version_status=AssetVersionStatus.AVAILABLE,
        )
        ref = models.NormalizedAssetRef(
            id="ref-us", version_id=version.id,
            normalized_type=NormalizedType.DOCUMENT,
            object_uri="s3://x/us.json",
            schema_version="normalized-document.v2",
            checksum="ref-us", status=NormalizedAssetRefStatus.GENERATED,
            source_type="file_upload", content_type="markdown",
            title="教材", language="zh-CN",
            governance={}, quality={}, lineage={},
            metadata_summary={"domain_profile": "course_textbook.v1"},
        )
        session.add_all([ds, batch, raw, asset, version, ref])
        session.commit()
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id="ref-us", asset_version_id="version-us",
            tag_type="major", tag_value="电子商务",
        )

        adapter = _FakeSearchAdapter([{
            "nexus_chunk_id": "chunk-1", "normalized_ref_id": "ref-us",
            "score": 0.9, "content": "c", "snippet": "c",
            "metadata": {}, "knowledge_type_code": "course_textbook",
            "collection_key": "course_textbook.document.bge.v1",
        }])
        executor = UnstructuredRetrievalExecutor(search_adapter=adapter)
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q_us", "channel": "unstructured",
            "domain": "course_textbook", "purpose": "test",
            "query_text": "test",
            "unstructured_plan": UnstructuredPlan(top_k=5).model_dump(),
            "tag_filters": {
                "majors": TagFilter(
                    tags=["电子商务"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
        })
        executor.execute(session, sub_query)

        rows = _audit_rows(session, AuditEventType.RETRIEVAL_TAG_FILTER_APPLIED)
        assert len(rows) == 1
        summary = rows[0].summary
        assert summary["sub_query_id"] == "q_us"
        assert summary["channel"] == "unstructured"
        assert summary["tag_target_type"] == "normalized_asset_ref"


# ---------------------------------------------------------------------------
# DagAudit — orchestrator plan execution
# ---------------------------------------------------------------------------


class TestDagAudit:
    def test_dag_audit_written_after_execution(self, session):
        from nexus_app.audit import write_retrieval_dag_audit
        from nexus_app.retrieval.dag_orchestrator import (
            DagExecutionResult,
            DagLayer,
        )
        from nexus_app.retrieval.schemas import RetrievalResult

        plan = RetrievalPlan(
            original_query="test",
            sub_queries=[
                RetrievalSubQuery.model_validate({
                    "query_id": "q1", "channel": "structured",
                    "domain": "job_demand", "purpose": "p",
                    "query_text": "t",
                    "structured_plan": StructuredPlan(
                        table_profile="job_demand.v1",
                        query_profile="job_demand.record_list",
                    ).model_dump(),
                }),
                RetrievalSubQuery.model_validate({
                    "query_id": "q2", "channel": "structured",
                    "domain": "job_demand", "purpose": "p",
                    "query_text": "t",
                    "structured_plan": StructuredPlan(
                        table_profile="job_demand.v1",
                        query_profile="job_demand.record_list",
                    ).model_dump(),
                    "depends_on": ["q1"],
                }),
            ],
        )
        dag_result = DagExecutionResult(
            results=[
                RetrievalResult(
                    query_id="q1", channel="structured",
                    domain="job_demand", status=StepStatus.COMPLETED,
                    result_shape="record_list",
                ),
                RetrievalResult(
                    query_id="q2", channel="structured",
                    domain="job_demand", status=StepStatus.COMPLETED,
                    result_shape="record_list",
                ),
            ],
            layers=(
                DagLayer(depth=0, sub_query_ids=("q1",)),
                DagLayer(depth=1, sub_query_ids=("q2",)),
            ),
            warnings=[],
        )
        write_retrieval_dag_audit(session, plan=plan, dag_result=dag_result)
        session.flush()

        rows = _audit_rows(session, AuditEventType.RETRIEVAL_DAG_EXECUTED)
        assert len(rows) == 1
        summary = rows[0].summary
        assert summary["sub_query_count"] == 2
        assert summary["layer_count"] == 2
        assert summary["layers"] == [
            {"depth": 0, "sub_query_ids": ["q1"]},
            {"depth": 1, "sub_query_ids": ["q2"]},
        ]
        assert summary["shared_constraints_present"] is False
        assert [o["sub_query_id"] for o in summary["sub_query_outcomes"]] == ["q1", "q2"]


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


class TestAuditFailureIsolation:
    def test_audit_write_error_does_not_abort_retrieval(
        self, session, monkeypatch,
    ):
        seeded = _seed_major_distribution_min(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_id"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="浙江",
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("audit backend unavailable")

        # Patch the low-level writer so the wrapper's try/except is
        # exercised.
        monkeypatch.setattr("nexus_app.audit.write_audit", _boom)

        executor = MajorDistributionRetrievalExecutor()
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "major_distribution", "purpose": "test",
            "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags=["浙江"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
        })
        # Retrieval should still succeed.
        result = executor.execute(session, sub_query)
        assert result.status == StepStatus.COMPLETED
        assert len(result.records) == 1
