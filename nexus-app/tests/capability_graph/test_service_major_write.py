"""A1f-3 (§10 阶段 A + §1.13 §5) — build_capability_staging major columns.

Verifies that the write path (`build_capability_staging`) captures
`major_name` + `major_code` for the two eligible build_types and
leaves them NULL for the others.

We patch `_collect_specs` to a deterministic mini-graph so the tests
focus on the identity-capture behaviour, not on the domain-specific
extractor logic (which owns its own tests).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from nexus_app import models
from nexus_app.capability_graph import build_capability_staging
from nexus_app.capability_graph.schemas import EdgeSpec, NodeSpec
from nexus_app.capability_graph.whitelists import BuildType, EdgeType, NodeType
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)


def _seed_ref(session, *, ref_id: str, title: str,
              normalized_type=NormalizedType.DOCUMENT):
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="cg-write",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id=f"b-{ref_id}", data_source_id=ds.id,
        idempotency_key=f"i-{ref_id}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"r-{ref_id}", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://x/{ref_id}", checksum=f"c-{ref_id}",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"a-{ref_id}", data_source_id=ds.id,
        source_object_key=f"{ref_id}.pdf",
        title=title, asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    ver = models.AssetVersion(
        id=f"v-{ref_id}", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=ver.id,
        normalized_type=normalized_type,
        object_uri=f"s3://x/{ref_id}.json", schema_version="v1",
        checksum=f"nrm-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={}, quality={}, lineage={}, metadata_summary={},
        title=title,
    )
    session.add_all([ds, batch, raw, asset, ver, ref])
    session.commit()
    return ref


def _fake_specs() -> tuple[list[NodeSpec], list[EdgeSpec]]:
    """Return a minimal but valid (nodes, edges) pair.

    We need at least one node so `build_capability_staging` doesn't
    early-return with `skipped=no_domain_data`, but the specific
    node/edge types are irrelevant to the major-column capture path.
    """
    node = NodeSpec(
        node_type=NodeType.MAJOR,
        node_key="major-key",
        display_name="X",
        source_table="test",
        source_id=None,
        properties={},
        confidence=None,
        canonical_name=None,
    )
    return [node], []


# ---------------------------------------------------------------------------
# teaching_standard build — extractor pulls major from title
# ---------------------------------------------------------------------------


def test_teaching_standard_build_populates_normalized_major_columns(session):
    ref = _seed_ref(
        session,
        ref_id="ref-ts",
        title="电子商务（530701）专业教学标准",
    )
    with patch(
        "nexus_app.capability_graph.service._collect_specs",
        return_value=_fake_specs(),
    ):
        result = build_capability_staging(
            session, ref,
            build_type=BuildType.TEACHING_STANDARD,
            teaching_standard_payload={"blocks": []},
        )
    session.commit()

    build = session.get(models.CapabilityGraphStagingBuild, result.build_id)
    assert build.major_name == "电子商务"      # normalizer stripped 专业教学标准
    assert build.major_code == "530701"


def test_teaching_standard_build_falls_back_to_null_when_extractor_fails(session):
    """If `_major_identity` throws, the build still lands with NULL
    columns — the graph construction must never abort on identity
    extraction (§1.13 交付物 ④ CI 断言 covers the reverse case)."""
    ref = _seed_ref(session, ref_id="ref-ts-bad", title="")
    with patch(
        "nexus_app.capability_graph.service._collect_specs",
        return_value=_fake_specs(),
    ):
        result = build_capability_staging(
            session, ref,
            build_type=BuildType.TEACHING_STANDARD,
            teaching_standard_payload={"blocks": []},
        )
    session.commit()

    build = session.get(models.CapabilityGraphStagingBuild, result.build_id)
    assert build.major_name is None
    assert build.major_code is None


# ---------------------------------------------------------------------------
# ability_analysis build — extractor uses title only (no payload arg)
# ---------------------------------------------------------------------------


def test_ability_analysis_build_populates_normalized_major_columns(session):
    # `major_profile._extract_identity` expects "code name" ordering
    # (see extractor.py:201 regex); this title matches that shape and
    # is representative of the "5307 电子商务类" filename convention
    # used in tests/test_major_profile.py:68.
    ref = _seed_ref(
        session,
        ref_id="ref-aa",
        title="5307 电子商务类职业能力分析表",
    )
    with patch(
        "nexus_app.capability_graph.service._collect_specs",
        return_value=_fake_specs(),
    ):
        result = build_capability_staging(
            session, ref,
            build_type=BuildType.ABILITY_ANALYSIS,
        )
    session.commit()

    build = session.get(models.CapabilityGraphStagingBuild, result.build_id)
    # 类 stripped + 职业能力分析表 stripped → "电子商务"
    assert build.major_name == "电子商务"
    assert build.major_code == "5307"


# ---------------------------------------------------------------------------
# job_demand + combined builds — must NOT populate the columns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("build_type", [
    BuildType.JOB_DEMAND,
    BuildType.COMBINED,
])
def test_ineligible_build_types_leave_major_columns_null(session, build_type):
    ref = _seed_ref(
        session,
        ref_id=f"ref-{build_type}",
        # A parseable title so we'd get non-null values IF the code path
        # were run — but §1.12 决策 #4 says it isn't.
        title="电子商务（530701）岗位需求数据",
        normalized_type=NormalizedType.RECORD,
    )
    with patch(
        "nexus_app.capability_graph.service._collect_specs",
        return_value=_fake_specs(),
    ):
        result = build_capability_staging(
            session, ref, build_type=build_type,
        )
    session.commit()

    build = session.get(models.CapabilityGraphStagingBuild, result.build_id)
    assert build.major_name is None
    assert build.major_code is None
