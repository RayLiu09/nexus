"""Unit tests for scripts/e2e_readiness_check.py individual checks.

The LiteLLM HTTP probe skips these tests (it needs a network) —
covered by manual runs against dev. Everything DB-side runs against
the shared SQLite in-memory session fixture.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

# Every check in this module reads absolute row counts.  On SQLite that
# starts from an empty in-memory schema; on the opt-in dev Postgres the
# session sees the entire shared DB state (32 alias rows, 12 asset
# versions, etc.) — which breaks "warns when empty" style assertions.
# Skip the whole module on Postgres.  The check functions themselves
# still work there — see manual runs of the script itself for coverage.
pytestmark = pytest.mark.skipif(
    os.getenv("NEXUS_GOLDEN_USE_POSTGRES", "").lower()
    in ("1", "true", "yes", "on"),
    reason="check functions assert absolute counts; skip on shared dev Postgres",
)

from nexus_app import models
from nexus_app.config import get_settings
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    GovernancePromptTemplateStatus,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    PromptProfileStatus,
    RawObjectStatus,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)


def _load_module():
    """Load the script as a module without triggering its __main__."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "e2e_readiness_check.py"
    spec = importlib.util.spec_from_file_location("e2e_readiness_check", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["e2e_readiness_check"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CHK = _load_module()


# ---------------------------------------------------------------------------
# Seed helpers — kept intentionally minimal so each test can shape the
# state around a single check.
# ---------------------------------------------------------------------------


def _seed_prompt(session, task_type: str, status: str = "active") -> None:
    session.add(
        models.GovernancePromptTemplate(
            id=f"gpt-{task_type}",
            task_type=task_type,
            template_name=f"tpl-{task_type}",
            template_version=1,
            prompt_template="body",
            litellm_model_alias="gpt-4o-mini",
            status=GovernancePromptTemplateStatus(status),
        )
    )
    session.flush()


def _seed_asset_scaffold(
    session, *, ref_id: str, normalized_type: NormalizedType = NormalizedType.DOCUMENT
) -> dict[str, str]:
    ds = models.DataSource(
        id=f"ds-{ref_id}",
        code=f"ds-{ref_id}",
        name="src",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id=f"batch-{ref_id}",
        data_source_id=ds.id,
        idempotency_key=f"idem-{ref_id}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"raw-{ref_id}",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://x/{ref_id}",
        checksum=f"cs-{ref_id}",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"asset-{ref_id}",
        data_source_id=ds.id,
        source_object_key=ref_id,
        title="t",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id=f"ver-{ref_id}",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id,
        version_id=version.id,
        normalized_type=normalized_type,
        object_uri=f"s3://x/{ref_id}.json",
        schema_version="normalized-record.v2",
        checksum=f"nrm-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload",
        content_type="table_sheet",
        title="t",
        language="zh-CN",
        governance={},
        quality={},
        lineage={},
        metadata_summary={},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.flush()
    return {"version_id": version.id, "ref_id": ref.id}


def _seed_tag(
    session,
    *,
    target_type: TagAssetIndexTargetType,
    target_id: str,
    asset_version_id: str,
    source: TagAssetIndexSource = TagAssetIndexSource.FIELD_PROJECTION,
    tag_type: str = "region",
    tag_value: str = "北京",
    embedding: list[float] | None = None,
) -> None:
    session.add(
        models.TagAssetIndex(
            tag_type=tag_type,
            tag_value=tag_value,
            tag_value_normalized=tag_value,
            target_type=target_type,
            target_id=target_id,
            asset_version_id=asset_version_id,
            source=source,
            tag_embedding=embedding,
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# alembic_head
# ---------------------------------------------------------------------------


def test_alembic_head_passes_when_dim_tag_alias_reachable(session):
    result = CHK.check_alembic_head(session, get_settings())
    assert result.severity == CHK.SEV_PASS
    assert result.details["dim_tag_alias_rows"] == 0


# ---------------------------------------------------------------------------
# governance_prompts
# ---------------------------------------------------------------------------


def test_governance_prompts_blocks_when_any_missing(session):
    _seed_prompt(session, "classification")
    _seed_prompt(session, "level_assessment")
    # tagging + knowledge_type_inference missing
    result = CHK.check_governance_prompts(session, get_settings())
    assert result.severity == CHK.SEV_BLOCK
    assert "tagging" in result.message
    assert "knowledge_type_inference" in result.message


def test_governance_prompts_passes_when_all_four_active(session):
    for tt in ("classification", "level_assessment", "tagging", "knowledge_type_inference"):
        _seed_prompt(session, tt)
    result = CHK.check_governance_prompts(session, get_settings())
    assert result.severity == CHK.SEV_PASS


# ---------------------------------------------------------------------------
# ai_prompt_profiles
# ---------------------------------------------------------------------------


def test_ai_prompt_profiles_warns_when_empty(session):
    result = CHK.check_ai_prompt_profiles(session, get_settings())
    assert result.severity == CHK.SEV_WARN
    assert result.details["active_count"] == 0


def test_ai_prompt_profiles_passes_when_active_row_present(session):
    session.add(
        models.AIPromptProfile(
            id="app-1",
            profile_name="test",
            profile_version=1,
            task_type="test",
            scenario="test",
            litellm_model_alias="gpt-4o-mini",
            prompt_version="v1",
            prompt_template="t",
            status=PromptProfileStatus.ACTIVE,
        )
    )
    session.flush()
    result = CHK.check_ai_prompt_profiles(session, get_settings())
    assert result.severity == CHK.SEV_PASS


# ---------------------------------------------------------------------------
# tag_asset_index_coverage
# ---------------------------------------------------------------------------


def test_tag_asset_index_blocks_when_empty(session):
    result = CHK.check_tag_asset_index_coverage(session, get_settings())
    assert result.severity == CHK.SEV_BLOCK
    assert result.details["total"] == 0


def test_tag_asset_index_warns_when_only_structured_field_projection(session):
    """The dev DB the user is on right now: structured field_projection
    rows only, no governance_tag on refs.  Two gaps must surface."""
    scaffold = _seed_asset_scaffold(session, ref_id="ref-1")
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        target_id="jd-1",
        asset_version_id=scaffold["version_id"],
        source=TagAssetIndexSource.FIELD_PROJECTION,
    )
    result = CHK.check_tag_asset_index_coverage(session, get_settings())
    assert result.severity == CHK.SEV_WARN
    gaps_text = " ".join(result.details["gaps"])
    assert "normalized_asset_ref" in gaps_text
    assert "outline_node" in gaps_text


def test_tag_asset_index_passes_when_all_three_axes_present(session):
    scaffold = _seed_asset_scaffold(session, ref_id="ref-1")
    # Structured field projection
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        target_id="jd-1",
        asset_version_id=scaffold["version_id"],
        source=TagAssetIndexSource.FIELD_PROJECTION,
    )
    # Governance tag on a normalized_asset_ref
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        target_id=scaffold["ref_id"],
        asset_version_id=scaffold["version_id"],
        source=TagAssetIndexSource.GOVERNANCE_TAG,
    )
    # Outline projection on an outline_node
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.OUTLINE_NODE,
        target_id="outline-1",
        asset_version_id=scaffold["version_id"],
        source=TagAssetIndexSource.OUTLINE_PROJECTION,
    )
    result = CHK.check_tag_asset_index_coverage(session, get_settings())
    assert result.severity == CHK.SEV_PASS
    assert result.details["gaps"] == []


# ---------------------------------------------------------------------------
# tag_embedding_backfill
# ---------------------------------------------------------------------------


def test_tag_embedding_skips_on_sqlite_with_info(session):
    """``pgvector.sqlalchemy.Vector`` doesn't round-trip NULL on SQLite —
    the check bails out with INFO so operators know to re-run against
    real Postgres before trusting the L4 status."""
    scaffold = _seed_asset_scaffold(session, ref_id="ref-1")
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        target_id=scaffold["ref_id"],
        asset_version_id=scaffold["version_id"],
    )
    result = CHK.check_tag_embedding_backfill(session, get_settings())
    assert result.severity == CHK.SEV_INFO
    assert "pgvector" in result.message.lower() or "sqlite" in result.message.lower()


# ---------------------------------------------------------------------------
# governance_run_coverage
# ---------------------------------------------------------------------------


def test_governance_run_coverage_info_when_no_documents(session):
    """No document refs at all → INFO, not blocking."""
    result = CHK.check_governance_run_coverage(session, get_settings())
    assert result.severity == CHK.SEV_INFO


def test_governance_run_coverage_blocks_when_document_refs_but_no_success(session):
    _seed_asset_scaffold(session, ref_id="ref-1")
    # Seed a FAILED governance run — must not count as successful
    session.add(
        models.AIGovernanceRun(
            id="gr-1",
            normalized_ref_id="ref-1",
            profile_id=None,
            model_alias="gpt-4o-mini",
            prompt_version="v1",
            input_hash="h",
            input_summary={},
            validation_status=AIGovernanceRunValidationStatus.FAILED,
            adoption_status=AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED,
            created_at=datetime.now(UTC),
        )
    )
    session.flush()
    result = CHK.check_governance_run_coverage(session, get_settings())
    assert result.severity == CHK.SEV_BLOCK


def test_governance_run_coverage_passes_when_valid_auto_adopted(session):
    _seed_asset_scaffold(session, ref_id="ref-1")
    session.add(
        models.AIGovernanceRun(
            id="gr-1",
            normalized_ref_id="ref-1",
            profile_id=None,
            model_alias="gpt-4o-mini",
            prompt_version="v1",
            input_hash="h",
            input_summary={},
            validation_status=AIGovernanceRunValidationStatus.SCHEMA_VALID,
            adoption_status=AIGovernanceRunAdoptionStatus.AUTO_ADOPTED,
            created_at=datetime.now(UTC),
        )
    )
    session.flush()
    result = CHK.check_governance_run_coverage(session, get_settings())
    assert result.severity == CHK.SEV_PASS


# ---------------------------------------------------------------------------
# dim_tag_alias_populated
# ---------------------------------------------------------------------------


def test_dim_tag_alias_warns_when_empty(session):
    result = CHK.check_dim_tag_alias_populated(session, get_settings())
    assert result.severity == CHK.SEV_WARN


def test_dim_tag_alias_passes_when_rows_present(session):
    session.add(
        models.DimTagAlias(
            id="a-1",
            tag_type="industry",
            alias_value="直播电商",
            alias_value_normalized="直播电商",
            canonical_value="电子商务",
            canonical_value_normalized="电子商务",
        )
    )
    session.flush()
    result = CHK.check_dim_tag_alias_populated(session, get_settings())
    assert result.severity == CHK.SEV_PASS


# ---------------------------------------------------------------------------
# asset_version_available_count
# ---------------------------------------------------------------------------


def test_asset_version_blocks_when_zero(session):
    result = CHK.check_asset_version_available_count(session, get_settings())
    assert result.severity == CHK.SEV_BLOCK


def test_asset_version_passes_when_any_available(session):
    _seed_asset_scaffold(session, ref_id="ref-1")
    result = CHK.check_asset_version_available_count(session, get_settings())
    assert result.severity == CHK.SEV_PASS
    assert result.details["available_count"] == 1
