"""Model + migration guards for tag_asset_index (v1.3 §2.2).

Two layers of coverage:

1. **ORM CRUD** — exercised against the SQLite in-memory fixture so we
   know the model, enums, indexes, and default columns round-trip.
   Vector columns fall back to JSON in SQLite (see ``Vector`` type
   decorator) so we can still store and read back embedding lists.
2. **Migration static guards** — the migration is not executed here
   (pgvector's HNSW index and ALTER COLUMN TYPE vector(512) both need
   Postgres); instead we assert the file's shape, revision chain, and
   the enum values it declares match the ORM enums.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
from sqlalchemy import inspect, select

from nexus_app import models
from nexus_app.enums import TagAssetIndexSource, TagAssetIndexTargetType


MIGRATION_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260710_0070_create_tag_asset_index.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "alembic.versions._m0070_test", MIGRATION_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_target_type_covers_six_documented_targets(self) -> None:
        expected = {
            "normalized_asset_ref",
            "outline_node",
            "job_demand_record",
            "job_demand_requirement_item",
            "major_distribution_record",
            "occupational_ability_item",
        }
        assert {t.value for t in TagAssetIndexTargetType} == expected

    def test_source_covers_five_documented_provenances(self) -> None:
        expected = {
            "field_projection",
            "outline_projection",
            "governance_tag",
            "expert_manual",
            "dict_alias_hit",
        }
        assert {s.value for s in TagAssetIndexSource} == expected


# ---------------------------------------------------------------------------
# ORM shape
# ---------------------------------------------------------------------------


class TestOrmShape:
    def test_table_name(self) -> None:
        assert models.TagAssetIndex.__tablename__ == "tag_asset_index"

    def test_expected_columns_present(self) -> None:
        mapper = inspect(models.TagAssetIndex)
        column_names = {c.key for c in mapper.columns}
        expected = {
            "id",
            "tag_type",
            "tag_value",
            "tag_value_normalized",
            "standard_code",
            "tag_embedding",
            "target_type",
            "target_id",
            "asset_version_id",
            "source",
            "confidence",
            "extraction_run_id",
            "extracted_at",
            "trace_id",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(column_names)

    def test_five_indexes_declared(self) -> None:
        """v1.3 §2.2 spec: five composite/single indexes on the ORM.
        The HNSW pgvector index is created imperatively in migration
        0070 (not declared on __table_args__) so it stays PostgreSQL-only."""
        index_names = {
            ix.name for ix in models.TagAssetIndex.__table__.indexes
        }
        for expected in (
            "ix_tai_type_norm",
            "ix_tai_type_code",
            "ix_tai_target",
            "ix_tai_asset_version",
            "ix_tai_source",
        ):
            assert expected in index_names, f"missing index {expected}"


# ---------------------------------------------------------------------------
# CRUD against SQLite fixture
# ---------------------------------------------------------------------------


class TestCrud:
    def _make_row(self, **overrides) -> models.TagAssetIndex:
        base = dict(
            tag_type="region",
            tag_value="北京市",
            tag_value_normalized="北京",
            standard_code=None,
            tag_embedding=None,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id="ref-uuid-1",
            asset_version_id="ver-uuid-1",
            source=TagAssetIndexSource.GOVERNANCE_TAG,
            confidence=0.94,
            extraction_run_id="run-uuid-1",
        )
        base.update(overrides)
        return models.TagAssetIndex(**base)

    def test_round_trip_governance_tag(self, session) -> None:
        row = self._make_row()
        session.add(row)
        session.flush()

        loaded = session.scalars(
            select(models.TagAssetIndex).where(
                models.TagAssetIndex.target_id == "ref-uuid-1"
            )
        ).one()
        assert loaded.tag_type == "region"
        assert loaded.tag_value == "北京市"
        assert loaded.tag_value_normalized == "北京"
        assert loaded.source == TagAssetIndexSource.GOVERNANCE_TAG
        assert loaded.target_type == TagAssetIndexTargetType.NORMALIZED_ASSET_REF
        assert loaded.confidence == 0.94

    def test_field_projection_no_confidence(self, session) -> None:
        """v1.3 §2.3 field-projection rows have no confidence value."""
        row = self._make_row(
            source=TagAssetIndexSource.FIELD_PROJECTION,
            confidence=None,
            extraction_run_id=None,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        )
        session.add(row)
        session.flush()

        loaded = session.scalars(select(models.TagAssetIndex)).one()
        assert loaded.confidence is None
        assert loaded.extraction_run_id is None

    def test_standard_code_optional(self, session) -> None:
        """L3 rows carry a standard_code; other rows don't."""
        code_row = self._make_row(standard_code="11", source=TagAssetIndexSource.DICT_ALIAS_HIT)
        no_code_row = self._make_row(target_id="ref-uuid-2")
        session.add_all([code_row, no_code_row])
        session.flush()

        with_code = session.scalars(
            select(models.TagAssetIndex).where(
                models.TagAssetIndex.standard_code.is_not(None)
            )
        ).all()
        without_code = session.scalars(
            select(models.TagAssetIndex).where(
                models.TagAssetIndex.standard_code.is_(None)
            )
        ).all()
        assert len(with_code) == 1
        assert len(without_code) == 1

    def test_tag_embedding_json_roundtrip_on_sqlite(self, session) -> None:
        """Vector fallback stores/reads a list[float] on SQLite so the
        L4 pipeline can be exercised without pgvector installed."""
        row = self._make_row(
            tag_embedding=[0.1, -0.2, 0.3, 0.4, 0.5],
        )
        session.add(row)
        session.flush()

        loaded = session.scalars(select(models.TagAssetIndex)).one()
        assert loaded.tag_embedding == [0.1, -0.2, 0.3, 0.4, 0.5]

    def test_lookup_by_normalized_value_uses_l1_index(self, session) -> None:
        """Simulate the L1 read path: (tag_type, tag_value_normalized)."""
        session.add_all([
            self._make_row(tag_type="region", tag_value="北京市", tag_value_normalized="北京"),
            self._make_row(tag_type="industry", tag_value="直播电商",
                           tag_value_normalized="直播电商", target_id="ref-uuid-99"),
        ])
        session.flush()

        hits = session.scalars(
            select(models.TagAssetIndex).where(
                models.TagAssetIndex.tag_type == "region",
                models.TagAssetIndex.tag_value_normalized == "北京",
            )
        ).all()
        assert len(hits) == 1
        assert hits[0].tag_value == "北京市"


# ---------------------------------------------------------------------------
# Migration static guards
# ---------------------------------------------------------------------------


class TestMigration0070:
    def test_revision_chain(self) -> None:
        m = _load_migration_module()
        assert m.revision == "20260710_0070"
        assert m.down_revision == "20260710_0069"

    def test_migration_declares_matching_enum_values(self) -> None:
        """Migration DDL enum values must match the ORM enum members
        exactly.  A drift here would make Alembic ``upgrade`` deposit a
        different set of enum labels than the ORM expects."""
        m = _load_migration_module()
        assert set(m._TAG_ASSET_INDEX_TARGET_TYPE_VALUES) == {
            t.value for t in TagAssetIndexTargetType
        }
        assert set(m._TAG_ASSET_INDEX_SOURCE_VALUES) == {
            s.value for s in TagAssetIndexSource
        }

    def test_upgrade_and_downgrade_callable(self) -> None:
        m = _load_migration_module()
        assert callable(m.upgrade)
        assert callable(m.downgrade)
