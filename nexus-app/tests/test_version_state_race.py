"""Concurrent `transition_to_available` race against the same asset.

`VersionStateManager.transition_to_available` has two layers of defense
against two workers racing to mark different versions of the same asset
AVAILABLE at once:

  1. An in-process `SELECT ... FOR UPDATE` row lock on the asset row
     (real lock on PostgreSQL; no-op on SQLite which serializes writers
     wholesale).
  2. The PostgreSQL-only partial unique index on
     `asset_version(asset_id) WHERE version_status = 'available'`
     (Alembic 0014) — the DB-level safety net.

The PG safety net cannot be exercised directly on the test fixture
(SQLite has no partial unique indexes), so this file pins the
**application-level invariant** the lock/archive path is supposed to
preserve under concurrent intent: regardless of arrival order, exactly
one AVAILABLE version remains for any asset, and the rest land in
ARCHIVED. A logic bug in the archive step would surface here even on
SQLite.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from nexus_app import models
from nexus_app.database import Base
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
from nexus_app.metadata.version_state import VersionStateManager


# ---------------------------------------------------------------------------
# Engine fixture — shared across threads on a single in-memory DB.
# ---------------------------------------------------------------------------


@pytest.fixture()
def shared_engine():
    """One in-memory SQLite shared between threads via StaticPool."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session_factory(shared_engine):
    return sessionmaker(
        bind=shared_engine, autoflush=False, autocommit=False, future=True
    )


# ---------------------------------------------------------------------------
# Domain graph seeding
# ---------------------------------------------------------------------------


def _seed_asset_with_versions(
    session: Session, version_count: int
) -> tuple[str, list[str]]:
    """Create one asset + N versions in PROCESSING state, return (asset_id, [version_ids])."""
    ds = models.DataSource(
        id="ds-race", code="ds-race", name="DS",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(ds)
    session.flush()
    batch = models.IngestBatch(
        id="batch-race", data_source_id=ds.id, idempotency_key="batch-race",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    session.add(batch)
    session.flush()
    asset = models.DocumentAsset(
        id="asset-race",
        data_source_id=ds.id,
        source_object_key="race-key",
        title="Race Asset",
        asset_kind=AssetKind.DOCUMENT,
    )
    session.add(asset)
    session.flush()

    version_ids: list[str] = []
    for i in range(1, version_count + 1):
        raw = models.RawObject(
            id=f"raw-race-{i}", batch_id=batch.id, data_source_id=ds.id,
            source_type=DataSourceType.FILE_UPLOAD,
            source_uri=f"file://race-{i}", object_uri=f"raw/race-{i}",
            checksum=f"race-checksum-{i}", size_bytes=1,
            status=RawObjectStatus.RAW_PERSISTED,
        )
        session.add(raw)
        session.flush()
        version = models.DocumentVersion(
            id=f"version-race-{i}",
            asset_id=asset.id, raw_object_id=raw.id, version_no=i,
            source_checksum=raw.checksum,
            version_status=AssetVersionStatus.PROCESSING,
        )
        session.add(version)
        session.flush()
        version_ids.append(version.id)
    session.commit()
    return asset.id, version_ids


def _seed_governance_result(session: Session, version_id: str) -> models.GovernanceResult:
    """Build a passing governance_result tied to `version_id` via a fresh ref."""
    ref = models.NormalizedAssetRef(
        id=f"ref-{version_id}",
        version_id=version_id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri=f"normalized/{version_id}.json",
        schema_version="1.0",
        checksum=f"{version_id}-checksum",
        title="t", language="en",
        source_type="file_upload", content_type="document",
        governance={"level": "L2"}, quality={}, lineage={},
        metadata_summary={},
        status=NormalizedAssetRefStatus.GENERATED,
    )
    session.add(ref)
    session.flush()
    result = models.GovernanceResult(
        id=f"gov-{version_id}",
        normalized_ref_id=ref.id,
        status=GovernanceResultStatus.AVAILABLE,
        rules_schema_version="1.0", rules_content_hash="hash",
        classification="D1", level="L2", tags=[],
        index_admission=True,
        quality_summary={
            "quality_score": 85.0,
            "quality_level": "pass",
            "confidence": 0.95,
        },
        decision_trail=[{"adoption_status": "auto_adopted"}],
    )
    session.add(result)
    session.commit()
    return result


def _count_available(session: Session, asset_id: str) -> int:
    return len(
        session.scalars(
            select(models.DocumentVersion).where(
                models.DocumentVersion.asset_id == asset_id,
                models.DocumentVersion.version_status == AssetVersionStatus.AVAILABLE,
            )
        ).all()
    )


def _statuses(session: Session, asset_id: str) -> dict[str, str]:
    rows = session.scalars(
        select(models.DocumentVersion)
        .where(models.DocumentVersion.asset_id == asset_id)
        .order_by(models.DocumentVersion.version_no.asc())
    ).all()
    return {v.id: v.version_status.value for v in rows}


# ---------------------------------------------------------------------------
# Sequential semantics — the baseline invariant the concurrent test
# ultimately checks for. Lives here too because the v0.2 pipeline-integration
# coverage requires httpx and is currently gated off.
# ---------------------------------------------------------------------------


def test_sequential_promotion_archives_predecessor(session_factory):
    """A → AVAILABLE, then B → AVAILABLE: A flips to ARCHIVED, exactly one
    AVAILABLE survives."""
    with session_factory() as session:
        asset_id, [v1, v2] = _seed_asset_with_versions(session, 2)
        result1 = _seed_governance_result(session, v1)
        result2 = _seed_governance_result(session, v2)

        mgr = VersionStateManager()
        mgr.transition_to_available(session, session.get(models.DocumentVersion, v1), result1)
        session.commit()
        assert _count_available(session, asset_id) == 1

        mgr.transition_to_available(session, session.get(models.DocumentVersion, v2), result2)
        session.commit()
        assert _count_available(session, asset_id) == 1

        statuses = _statuses(session, asset_id)
        assert statuses[v1] == AssetVersionStatus.ARCHIVED.value
        assert statuses[v2] == AssetVersionStatus.AVAILABLE.value


def test_repeated_promotion_of_same_version_is_idempotent(session_factory):
    """Calling transition_to_available twice on the same version must NOT
    archive it (it's still the current available)."""
    with session_factory() as session:
        asset_id, [v1] = _seed_asset_with_versions(session, 1)
        result1 = _seed_governance_result(session, v1)

        mgr = VersionStateManager()
        mgr.transition_to_available(session, session.get(models.DocumentVersion, v1), result1)
        session.commit()
        mgr.transition_to_available(session, session.get(models.DocumentVersion, v1), result1)
        session.commit()

        statuses = _statuses(session, asset_id)
        assert statuses[v1] == AssetVersionStatus.AVAILABLE.value
        assert _count_available(session, asset_id) == 1


# ---------------------------------------------------------------------------
# Concurrent race
# ---------------------------------------------------------------------------


def test_interleaved_transitions_converge_to_single_available(session_factory):
    """Same race-window simulation as above, but with the stronger
    assertion: exactly one AVAILABLE row at end.

    SQLite's StaticPool flattens both sessions onto the same connection,
    so session_b's `_archive_old_available` query observes session_a's
    flushed-but-uncommitted v1=AVAILABLE and archives it before
    promoting v2 — yielding the same single-AVAILABLE invariant the PG
    partial unique index enforces. The result holds on PG too (via the
    DB constraint instead of pool-induced serialization), so this test
    is a useful regression guard on both engines."""
    with session_factory() as bootstrap:
        asset_id, [v1, v2] = _seed_asset_with_versions(bootstrap, 2)
        _seed_governance_result(bootstrap, v1)
        _seed_governance_result(bootstrap, v2)

    session_a = session_factory()
    session_b = session_factory()
    try:
        mgr = VersionStateManager()
        try:
            mgr.transition_to_available(
                session_a,
                session_a.get(models.DocumentVersion, v1),
                session_a.get(models.GovernanceResult, f"gov-{v1}"),
            )
            mgr.transition_to_available(
                session_b,
                session_b.get(models.DocumentVersion, v2),
                session_b.get(models.GovernanceResult, f"gov-{v2}"),
            )
            session_a.commit()
            session_b.commit()
        except Exception:
            session_a.rollback()
            session_b.rollback()
    finally:
        session_a.close()
        session_b.close()

    with session_factory() as session:
        assert _count_available(session, asset_id) == 1
