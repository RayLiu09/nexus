"""PR-8 guards for the governance-side tag projection writer + the
metadata_projections engine extension + evidence_span carriage.
"""

from __future__ import annotations

import pytest

from nexus_app import models
from nexus_app.ai_governance.governance_tag_projection import (
    BUCKET_TO_TAG_TYPE,
    project_governance_tag_bag,
)
from nexus_app.ai_governance.tag_projection import (
    _resolve_dotted_path,
    project_metadata_projections,
    project_record_to_tag_rows,
    persist_tag_rows,
)
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_ref(session, ref_id: str = "ref-gt") -> models.NormalizedAssetRef:
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="src",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id=f"batch-{ref_id}", data_source_id=ds.id,
        idempotency_key=f"idem-{ref_id}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"raw-{ref_id}", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://b/{ref_id}.pdf", checksum=f"cs-{ref_id}",
        mime_type="application/pdf", status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"asset-{ref_id}", data_source_id=ds.id,
        source_object_key=f"{ref_id}.pdf",
        title="教材", asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id=f"ver-{ref_id}", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri=f"s3://b/norm/{ref_id}.json",
        schema_version="normalized-document-v1",
        checksum=f"nrm-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=0, record_count=0,
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.flush()
    return ref


def _tag_rows_for(session, target_id: str, source: TagAssetIndexSource | None = None):
    query = session.query(models.TagAssetIndex).filter(
        models.TagAssetIndex.target_id == target_id,
    )
    if source is not None:
        query = query.filter(models.TagAssetIndex.source == source)
    return query.order_by(models.TagAssetIndex.tag_type.asc(),
                          models.TagAssetIndex.tag_value_normalized.asc()).all()


# ---------------------------------------------------------------------------
# _resolve_dotted_path
# ---------------------------------------------------------------------------


class TestResolveDottedPath:
    def test_walks_two_levels(self):
        record = {"node_metadata": {"keywords": ["a", "b"]}}
        assert _resolve_dotted_path(record, "node_metadata.keywords") == ["a", "b"]

    def test_returns_none_on_missing_segment(self):
        record = {"node_metadata": {}}
        assert _resolve_dotted_path(record, "node_metadata.keywords") is None

    def test_returns_none_when_intermediate_not_mapping(self):
        record = {"node_metadata": "not-a-dict"}
        assert _resolve_dotted_path(record, "node_metadata.keywords") is None

    def test_single_segment_shortcut(self):
        record = {"title": "章节"}
        assert _resolve_dotted_path(record, "title") == "章节"


# ---------------------------------------------------------------------------
# project_metadata_projections
# ---------------------------------------------------------------------------


class TestMetadataProjections:
    def test_knowledge_outline_keywords_projected_to_topic(self):
        payloads = project_metadata_projections(
            table_name="knowledge_outline_node",
            record={
                "title": "unused-here",
                "node_metadata": {"keywords": ["数据合规", "隐私保护"]},
            },
            target_type=TagAssetIndexTargetType.OUTLINE_NODE,
            target_id="node-a",
            asset_version_id="ver-x",
            source=TagAssetIndexSource.OUTLINE_PROJECTION,
        )
        assert {p.tag_value for p in payloads} == {"数据合规", "隐私保护"}
        assert all(p.tag_type == "topic" for p in payloads)

    def test_missing_metadata_yields_no_rows(self):
        payloads = project_metadata_projections(
            table_name="knowledge_outline_node",
            record={"title": "t"},
            target_type=TagAssetIndexTargetType.OUTLINE_NODE,
            target_id="node-a",
            asset_version_id="ver-x",
            source=TagAssetIndexSource.OUTLINE_PROJECTION,
        )
        assert payloads == []

    def test_table_without_metadata_config_yields_empty(self):
        # task_outline_node has no metadata_projections declared.
        payloads = project_metadata_projections(
            table_name="task_outline_node",
            record={"title": "t", "node_metadata": {"whatever": ["x"]}},
            target_type=TagAssetIndexTargetType.OUTLINE_NODE,
            target_id="node-a",
            asset_version_id="ver-x",
            source=TagAssetIndexSource.OUTLINE_PROJECTION,
        )
        assert payloads == []


# ---------------------------------------------------------------------------
# project_record_to_tag_rows — combined field + metadata projections
# ---------------------------------------------------------------------------


class TestRecordProjectionWithMetadata:
    def test_outline_title_plus_keywords_dedupes(self):
        payloads = project_record_to_tag_rows(
            table_name="knowledge_outline_node",
            record={
                "title": "数据合规",
                "node_metadata": {"keywords": ["数据合规", "隐私保护"]},
            },
            target_id="node-a",
            asset_version_id="ver-x",
            source=TagAssetIndexSource.OUTLINE_PROJECTION,
            target_type=TagAssetIndexTargetType.OUTLINE_NODE,
        )
        # title and keyword[0] normalise to the same value → dedup
        values = [p.tag_value_normalized for p in payloads]
        assert values.count("数据合规") == 1
        assert "隐私保护" in values


# ---------------------------------------------------------------------------
# evidence_span carriage
# ---------------------------------------------------------------------------


class TestEvidenceSpanCarriage:
    def test_evidence_span_persists_end_to_end(self, session):
        ref = _seed_ref(session, "ref-ev")
        result = project_governance_tag_bag(
            session,
            normalized_ref_id=ref.id,
            asset_version_id=ref.version_id,
            tag_bag={
                "regions": [
                    {"value": "北京市", "confidence": 0.9,
                     "evidence_span": "总部位于北京市朝阳区"},
                ],
            },
            extraction_run_id="run-1",
            confidence_threshold=0.5,
        )
        assert result.rows_persisted == 1
        row = _tag_rows_for(session, ref.id)[0]
        assert row.evidence_span == "总部位于北京市朝阳区"
        assert row.confidence == pytest.approx(0.9)
        assert row.extraction_run_id == "run-1"
        assert row.source == TagAssetIndexSource.GOVERNANCE_TAG


# ---------------------------------------------------------------------------
# project_governance_tag_bag — thresholding, dedup, idempotency
# ---------------------------------------------------------------------------


class TestGovernanceTagBagProjection:
    def test_multiple_buckets_flatten_to_ref(self, session):
        ref = _seed_ref(session, "ref-multi")
        result = project_governance_tag_bag(
            session,
            normalized_ref_id=ref.id,
            asset_version_id=ref.version_id,
            tag_bag={
                "regions": [{"value": "北京市", "confidence": 0.9,
                             "evidence_span": "总部位于北京"}],
                "industries": [{"value": "直播电商", "confidence": 0.85,
                                "evidence_span": "主营直播电商"}],
                "occupations": [{"value": "电商运营", "confidence": 0.8,
                                 "evidence_span": "招聘电商运营岗位"}],
            },
            extraction_run_id="run-multi",
            confidence_threshold=0.5,
        )
        assert result.rows_persisted == 3
        rows = _tag_rows_for(session, ref.id)
        assert {(r.tag_type, r.tag_value) for r in rows} == {
            ("region", "北京市"),
            ("industry", "直播电商"),
            ("occupation", "电商运营"),
        }
        assert all(
            r.target_type == TagAssetIndexTargetType.NORMALIZED_ASSET_REF
            for r in rows
        )

    def test_sub_threshold_tags_dropped(self, session):
        ref = _seed_ref(session, "ref-thres")
        result = project_governance_tag_bag(
            session,
            normalized_ref_id=ref.id,
            asset_version_id=ref.version_id,
            tag_bag={
                "regions": [
                    {"value": "北京市", "confidence": 0.9,
                     "evidence_span": "总部位于北京"},
                    {"value": "上海市", "confidence": 0.6,
                     "evidence_span": "有分公司"},
                ],
            },
            extraction_run_id="run-thres",
            confidence_threshold=0.85,
        )
        assert result.rows_persisted == 1
        assert result.dropped_below_threshold == 1
        rows = _tag_rows_for(session, ref.id)
        assert [r.tag_value for r in rows] == ["北京市"]

    def test_reprojection_replaces_prior_run(self, session):
        ref = _seed_ref(session, "ref-idem")
        # Run 1 — three tags.
        project_governance_tag_bag(
            session,
            normalized_ref_id=ref.id,
            asset_version_id=ref.version_id,
            tag_bag={
                "regions": [
                    {"value": "北京市", "confidence": 0.9,
                     "evidence_span": "e1"},
                    {"value": "上海市", "confidence": 0.9,
                     "evidence_span": "e2"},
                ],
                "industries": [{"value": "生鲜", "confidence": 0.9,
                                "evidence_span": "e3"}],
            },
            extraction_run_id="run-1",
            confidence_threshold=0.5,
        )
        assert len(_tag_rows_for(session, ref.id)) == 3
        # Run 2 — different tag set; must replace not append.
        project_governance_tag_bag(
            session,
            normalized_ref_id=ref.id,
            asset_version_id=ref.version_id,
            tag_bag={
                "regions": [{"value": "北京市", "confidence": 0.9,
                             "evidence_span": "e-new"}],
            },
            extraction_run_id="run-2",
            confidence_threshold=0.5,
        )
        rows = _tag_rows_for(session, ref.id)
        assert len(rows) == 1
        assert rows[0].tag_value == "北京市"
        assert rows[0].evidence_span == "e-new"
        assert rows[0].extraction_run_id == "run-2"

    def test_bare_string_entry_supported(self, session):
        ref = _seed_ref(session, "ref-bare")
        result = project_governance_tag_bag(
            session,
            normalized_ref_id=ref.id,
            asset_version_id=ref.version_id,
            tag_bag={"topics": ["数据合规", "  隐私保护  ", ""]},
            extraction_run_id="run-bare",
            confidence_threshold=0.0,  # threshold disabled for bare strings
        )
        assert result.rows_persisted == 2
        rows = _tag_rows_for(session, ref.id)
        assert {r.tag_value for r in rows} == {"数据合规", "隐私保护"}
        assert all(r.confidence is None for r in rows)

    def test_malformed_entries_dropped(self, session):
        ref = _seed_ref(session, "ref-malformed")
        result = project_governance_tag_bag(
            session,
            normalized_ref_id=ref.id,
            asset_version_id=ref.version_id,
            tag_bag={
                "regions": [
                    {"value": "北京市", "confidence": 0.9,
                     "evidence_span": "e1"},
                    {"confidence": 0.8},  # missing value
                    42,  # not a dict/str
                    "",  # empty string
                    {"value": "  ", "confidence": 0.8},  # whitespace-only
                ],
            },
            extraction_run_id="run-mf",
            confidence_threshold=0.5,
        )
        assert result.rows_persisted == 1
        assert result.dropped_malformed >= 3

    def test_dedup_across_buckets(self, session):
        ref = _seed_ref(session, "ref-dedup")
        # Same value emitted in two buckets — but different tag_type, so
        # both survive (dedup key is (tag_type, normalised_value)).
        result = project_governance_tag_bag(
            session,
            normalized_ref_id=ref.id,
            asset_version_id=ref.version_id,
            tag_bag={
                "occupations": [{"value": "电商运营", "confidence": 0.9,
                                 "evidence_span": "e1"}],
                "abilities": [{"value": "电商运营", "confidence": 0.9,
                               "evidence_span": "e2"}],
            },
            extraction_run_id="run-dd",
            confidence_threshold=0.5,
        )
        assert result.rows_persisted == 2
        rows = _tag_rows_for(session, ref.id)
        assert {r.tag_type for r in rows} == {"occupation", "ability"}

    def test_time_range_projection(self, session):
        ref = _seed_ref(session, "ref-tr")
        result = project_governance_tag_bag(
            session,
            normalized_ref_id=ref.id,
            asset_version_id=ref.version_id,
            tag_bag={
                "time_ranges": [
                    {"kind": "year_range", "start": 2022, "end": 2024,
                     "confidence": 0.9, "evidence_span": "近三年"},
                    {"kind": "point_in_time", "year": 2024,
                     "confidence": 0.9, "evidence_span": "截至2024"},
                ],
            },
            extraction_run_id="run-tr",
            confidence_threshold=0.5,
        )
        assert result.rows_persisted == 2
        rows = _tag_rows_for(session, ref.id)
        assert {r.tag_value for r in rows} == {"2022-2024", "2024"}

    def test_unknown_bucket_ignored(self, session):
        ref = _seed_ref(session, "ref-unk")
        result = project_governance_tag_bag(
            session,
            normalized_ref_id=ref.id,
            asset_version_id=ref.version_id,
            tag_bag={
                "regions": [{"value": "北京市", "confidence": 0.9,
                             "evidence_span": "e"}],
                "not_a_bucket": [{"value": "ignored", "confidence": 0.9}],
            },
            extraction_run_id="run-unk",
            confidence_threshold=0.5,
        )
        assert result.rows_persisted == 1

    def test_bucket_mapping_matches_canonical(self):
        # I-3 sanity: mapping matches the singular tag_type codes the
        # projection engine + Resolver expect.
        assert BUCKET_TO_TAG_TYPE == {
            "regions": "region",
            "industries": "industry",
            "occupations": "occupation",
            "majors": "major",
            "abilities": "ability",
            "topics": "topic",
            "time_ranges": "time_range",
        }
