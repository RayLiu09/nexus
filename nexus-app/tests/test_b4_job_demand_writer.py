"""Unit + integration tests for the B4 job_demand writer.

Covers the contract surface in `docs/pipeline_b_b4_b6_contract_freeze.md`:

  - §二.1 field mapping (every record_body field → DB column)
  - §三.1 fingerprint dedup (in-dataset only)
  - §三.3 dataset-level idempotency via delete+reinsert
  - §四 quality_flags vocabulary (closed set, only the six B4 keys)
  - §六 placeholder cleanup (5 rules)
  - §七 audit events (JOB_DEMAND_DATASET_PERSISTED + JOB_DEMAND_RECORDS_PERSISTED)

Tests run against the sqlite in-memory fixture (`session`) — the writer
itself never reaches for Postgres-only types, and JSON columns degrade
to TEXT for SQLite, so the assertions stay portable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.domain_normalize import dispatch_domain_normalize
from nexus_app.domain_normalize.fingerprint import (
    compute_job_demand_record_fingerprint,
)
from nexus_app.domain_normalize.job_demand_writer import (
    DOMAIN_PROFILE,
    QUALITY_FLAG_KEYS,
    write,
)
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)
from nexus_app.storage import InMemoryObjectStorage


# ---------------------------------------------------------------------------
# Fixtures — minimal asset graph anchoring a B4-shaped normalized_ref.
# ---------------------------------------------------------------------------


def _seed_normalized_ref(
    session,
    *,
    ref_id: str = "ref-b4",
    version_id: str = "ver-b4",
    asset_id: str = "asset-b4",
    domain_profile: str | None = "job_demand.v1",
    object_uri: str = "s3://bucket/normalized/ref-b4.json",
) -> models.NormalizedAssetRef:
    """Build the minimum graph (data_source → batch → raw → asset → version → ref)
    so writer FKs validate even on the sqlite fixture."""
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="b4",
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
        object_uri=f"s3://bucket/raw/{ref_id}.xlsx",
        checksum=f"cs-{ref_id}", mime_type="application/xlsx",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=asset_id, data_source_id=ds.id,
        source_object_key=f"{ref_id}.xlsx",
        title="t", asset_kind=AssetKind.RECORD,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id=version_id, asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri=object_uri,
        schema_version="normalized-record.v2",
        checksum="cs-ref",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": domain_profile} if domain_profile else {},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return ref


def _record_body(
    *,
    records: list[dict[str, Any]] | None = None,
    dataset_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dataset = {
        "major_name": "电子商务",
        "industry_name": "互联网",
        "source_channel": "excel_upload",
        "record_count": len(records or []),
        "invalid_count": 0,
        "duplicate_count": 0,
    }
    if dataset_overrides:
        dataset.update(dataset_overrides)
    return {"dataset": dataset, "records": records or []}


def _sample_record(
    *,
    title: str = "数据分析师",
    company: str = "ACME",
    city: str = "上海",
    key: str = "Sheet1#row2",
    **overrides: Any,
) -> dict[str, Any]:
    record = {
        "source_record_key": key,
        "job_title": title,
        "employment_type": "全职",
        "job_function_category": "运营",
        "job_count": 2,
        "city": city,
        "region": "黄浦区",
        "salary_min": 4000,
        "salary_max": 7000,
        "salary_text": "4千-7千",
        "experience_requirement": "1年以上",
        "education_requirement": "本科",
        "company_name": company,
        "company_address": "上海市黄浦区...",
        "enterprise_size": "20-99人",
        "industry_name": "互联网",
        "job_skill_text": "SQL/Excel",
        "job_description": "处理日常数据需求",
        "responsibility_text": "出具周报",
        "requirement_text": "本科以上",
        "source_url": "https://x.example/jobs/1",
        "source_platform": "boss",
        "source_published_at": "2024-12-12T01:12:59+08:00",
        "trace": {"sheet": "Sheet1", "row": 2},
    }
    record.update(overrides)
    return record


# ---------------------------------------------------------------------------
# Field mapping (§二.1)
# ---------------------------------------------------------------------------


class TestFieldMapping:
    def test_dataset_columns_populated_from_record_body(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(records=[_sample_record()])
        result = write(session, ref, body)
        session.commit()

        dataset = session.scalar(
            select(models.JobDemandDataset).where(
                models.JobDemandDataset.id == result.dataset_id
            )
        )
        assert dataset is not None
        assert dataset.major_name == "电子商务"
        assert dataset.industry_name == "互联网"
        assert dataset.source_channel == "excel_upload"
        assert dataset.schema_version == "normalized-record.v2"
        assert dataset.normalized_ref_id == ref.id
        assert dataset.asset_version_id == ref.version_id
        # record_count must equal len(records_payload) regardless of invalid /
        # duplicate filtering — caller uses it to derive valid_count externally.
        assert dataset.record_count == 1

    def test_record_columns_populated_verbatim(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(records=[_sample_record()])
        write(session, ref, body)
        session.commit()

        record = session.scalar(select(models.JobDemandRecord))
        assert record is not None
        assert record.job_title == "数据分析师"
        assert record.company_name == "ACME"
        assert record.city == "上海"
        assert record.region == "黄浦区"
        assert record.salary_min == 4000
        assert record.salary_max == 7000
        assert record.salary_text == "4千-7千"
        assert record.employment_type == "全职"
        assert record.job_count == 2
        assert record.industry_name == "互联网"
        # `enterprise_size` MUST be the raw text (§二.1 / decision 7).
        assert record.enterprise_size == "20-99人"
        # `trace` is stored as-is (JSONB-compatible JSON).
        assert record.trace == {"sheet": "Sheet1", "row": 2}

    def test_source_published_at_parsed_to_datetime(self, session):
        ref = _seed_normalized_ref(session)
        write(session, ref, _record_body(records=[_sample_record()]))
        session.commit()

        record = session.scalar(select(models.JobDemandRecord))
        assert record.source_published_at is not None
        # tz-aware after parsing.
        assert record.source_published_at.tzinfo is not None

    def test_published_at_unparseable_keeps_null_and_flags(self, session):
        ref = _seed_normalized_ref(session)
        write(
            session,
            ref,
            _record_body(records=[_sample_record(source_published_at="not-a-date")]),
        )
        session.commit()
        record = session.scalar(select(models.JobDemandRecord))
        assert record.source_published_at is None
        assert record.quality_flags.get("published_at_unparsed") is True

    def test_source_record_key_required_and_synthesised_when_missing(self, session):
        ref = _seed_normalized_ref(session)
        write(
            session,
            ref,
            _record_body(records=[_sample_record(source_record_key=None)]),
        )
        session.commit()
        record = session.scalar(select(models.JobDemandRecord))
        # The writer synthesises from trace so the fingerprint stays unique.
        assert record.source_record_key.startswith("Sheet1#row")

    def test_enterprise_size_not_normalised(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(
            records=[
                _sample_record(key="row-a", enterprise_size="20-99人"),
                _sample_record(
                    key="row-b", title="开发", enterprise_size="100-499 人",
                ),
                _sample_record(key="row-c", title="测试", enterprise_size="未知"),
            ]
        )
        write(session, ref, body)
        session.commit()
        rows = list(session.scalars(select(models.JobDemandRecord)).all())
        sizes = {r.source_record_key: r.enterprise_size for r in rows}
        assert sizes["row-a"] == "20-99人"
        assert sizes["row-b"] == "100-499 人"
        assert sizes["row-c"] == "未知"

    def test_region_missing_flags_location_unparsed(self, session):
        ref = _seed_normalized_ref(session)
        rec = _sample_record(region=None)  # explicitly NULL but key present
        write(session, ref, _record_body(records=[rec]))
        session.commit()
        record = session.scalar(select(models.JobDemandRecord))
        assert record.region is None
        assert record.quality_flags.get("location_unparsed") is True

    def test_region_present_does_not_flag_location_unparsed(self, session):
        ref = _seed_normalized_ref(session)
        write(session, ref, _record_body(records=[_sample_record()]))  # region="黄浦区"
        session.commit()
        record = session.scalar(select(models.JobDemandRecord))
        assert "location_unparsed" not in record.quality_flags


# ---------------------------------------------------------------------------
# Fingerprint dedup (§三.1)
# ---------------------------------------------------------------------------


class TestFingerprintDedup:
    def test_duplicate_records_drop_after_first(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(
            records=[
                _sample_record(key="row-1"),
                # Same company + title + city + key → duplicate fingerprint.
                _sample_record(key="row-1"),
            ]
        )
        result = write(session, ref, body)
        session.commit()

        rows = list(session.scalars(select(models.JobDemandRecord)).all())
        assert len(rows) == 1
        dataset = session.get(models.JobDemandDataset, result.dataset_id)
        assert dataset.duplicate_count == 1
        # Per §四, duplicate rows write the `duplicate_fingerprint` flag into
        # the dataset's quality_summary aggregation.
        assert dataset.quality_summary.get("duplicate_fingerprint") == 1

    def test_fingerprint_is_written_correctly(self, session):
        ref = _seed_normalized_ref(session)
        write(session, ref, _record_body(records=[_sample_record()]))
        session.commit()
        record = session.scalar(select(models.JobDemandRecord))
        expected = compute_job_demand_record_fingerprint(
            {
                "company_name": "ACME",
                "job_title": "数据分析师",
                "city": "上海",
                "source_record_key": "Sheet1#row2",
            }
        )
        assert record.record_fingerprint == expected

    def test_different_keys_keep_both_records(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(
            records=[
                _sample_record(key="row-1"),
                _sample_record(key="row-2"),
            ]
        )
        write(session, ref, body)
        session.commit()
        rows = list(session.scalars(select(models.JobDemandRecord)).all())
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# Placeholder cleanup (§六)
# ---------------------------------------------------------------------------


class TestPlaceholderRules:
    def test_empty_row_dropped(self, session):
        ref = _seed_normalized_ref(session)
        empty = {"trace": {"sheet": "s", "row": 1}}
        body = _record_body(records=[empty])
        result = write(session, ref, body)
        session.commit()
        dataset = session.get(models.JobDemandDataset, result.dataset_id)
        assert dataset.invalid_count == 1
        assert session.scalar(select(models.JobDemandRecord)) is None
        assert dataset.quality_summary.get("placeholder_row_dropped") == 1

    def test_placeholder_text_in_title_dropped(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(records=[_sample_record(title="...")])
        result = write(session, ref, body)
        session.commit()
        dataset = session.get(models.JobDemandDataset, result.dataset_id)
        assert dataset.invalid_count == 1
        assert session.scalar(select(models.JobDemandRecord)) is None
        assert dataset.quality_summary.get("placeholder_row_dropped") == 1

    def test_placeholder_text_in_description_dropped(self, session):
        ref = _seed_normalized_ref(session)
        # Title is valid, but description is purely placeholder.
        body = _record_body(records=[_sample_record(job_description="无")])
        result = write(session, ref, body)
        session.commit()
        dataset = session.get(models.JobDemandDataset, result.dataset_id)
        assert dataset.invalid_count == 1
        assert session.scalar(select(models.JobDemandRecord)) is None

    @pytest.mark.parametrize("bogus_title", ["1", "1.", "序号 2", "#3"])
    def test_pure_index_title_dropped(self, session, bogus_title):
        ref = _seed_normalized_ref(
            session,
            ref_id=f"ref-pure-{bogus_title}".replace(".", "d").replace("#", "h").replace(" ", "_"),
            version_id=f"ver-pure-{bogus_title}".replace(".", "d").replace("#", "h").replace(" ", "_"),
            asset_id=f"asset-pure-{bogus_title}".replace(".", "d").replace("#", "h").replace(" ", "_"),
        )
        body = _record_body(records=[_sample_record(title=bogus_title)])
        result = write(session, ref, body)
        session.commit()
        dataset = session.get(models.JobDemandDataset, result.dataset_id)
        assert dataset.invalid_count == 1
        assert (
            session.scalar(
                select(models.JobDemandRecord).where(
                    models.JobDemandRecord.dataset_id == dataset.id
                )
            )
            is None
        )

    def test_example_keyword_title_dropped(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(records=[_sample_record(title="example: data 分析师")])
        result = write(session, ref, body)
        session.commit()
        dataset = session.get(models.JobDemandDataset, result.dataset_id)
        assert dataset.invalid_count == 1
        assert session.scalar(select(models.JobDemandRecord)) is None

    def test_missing_title_with_other_fields_dropped(self, session):
        ref = _seed_normalized_ref(session)
        rec = _sample_record(title=None)
        body = _record_body(records=[rec])
        result = write(session, ref, body)
        session.commit()
        dataset = session.get(models.JobDemandDataset, result.dataset_id)
        assert dataset.invalid_count == 1
        # `missing_required_field` flag must appear in addition to
        # `placeholder_row_dropped`.
        assert dataset.quality_summary.get("placeholder_row_dropped") == 1
        assert dataset.quality_summary.get("missing_required_field") == 1
        # But the invalid count is still 1 (not double-counted).
        assert dataset.invalid_count == 1

    def test_valid_rows_pass_through_alongside_placeholders(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(
            records=[
                _sample_record(key="row-a"),
                {"trace": {"sheet": "s", "row": 99}},  # empty
                _sample_record(key="row-b", title="后端工程师"),
            ]
        )
        result = write(session, ref, body)
        session.commit()
        dataset = session.get(models.JobDemandDataset, result.dataset_id)
        assert dataset.record_count == 3
        assert dataset.invalid_count == 1
        rows = list(session.scalars(select(models.JobDemandRecord)).all())
        assert len(rows) == 2
        assert {r.source_record_key for r in rows} == {"row-a", "row-b"}


# ---------------------------------------------------------------------------
# Dataset-level idempotency (§三.3)
# ---------------------------------------------------------------------------


class TestDatasetIdempotency:
    def test_rerun_replaces_existing_dataset(self, session):
        ref = _seed_normalized_ref(session)
        first = write(session, ref, _record_body(records=[_sample_record()]))
        session.commit()
        first_id = first.dataset_id

        # Re-run with different content; old dataset+records should be gone.
        second = write(
            session, ref,
            _record_body(records=[_sample_record(key="row-replaced", title="新岗位")]),
        )
        session.commit()
        assert second.dataset_id != first_id
        assert session.get(models.JobDemandDataset, first_id) is None
        rows = list(session.scalars(select(models.JobDemandRecord)).all())
        assert len(rows) == 1
        assert rows[0].job_title == "新岗位"

    def test_only_one_dataset_per_normalized_ref(self, session):
        ref = _seed_normalized_ref(session)
        write(session, ref, _record_body(records=[_sample_record()]))
        session.commit()
        write(session, ref, _record_body(records=[_sample_record(key="row-x")]))
        session.commit()
        rows = list(session.scalars(select(models.JobDemandDataset)).all())
        assert len(rows) == 1

    def test_cascade_drops_records_on_rerun(self, session):
        ref = _seed_normalized_ref(session)
        write(
            session, ref,
            _record_body(records=[_sample_record(key=f"k-{i}") for i in range(3)]),
        )
        session.commit()
        assert session.scalar(select(models.JobDemandRecord)) is not None

        write(session, ref, _record_body(records=[_sample_record(key="k-only")]))
        session.commit()
        rows = list(session.scalars(select(models.JobDemandRecord)).all())
        assert len(rows) == 1
        assert rows[0].source_record_key == "k-only"


# ---------------------------------------------------------------------------
# quality_flags vocabulary + aggregation (§四)
# ---------------------------------------------------------------------------


class TestQualityFlags:
    def test_vocabulary_matches_freeze(self):
        # Closed set per §四 — any code change to the B4 keys must trip this.
        assert QUALITY_FLAG_KEYS == frozenset({
            "location_unparsed",
            "published_at_unparsed",
            "placeholder_row_dropped",
            "duplicate_fingerprint",
            "missing_required_field",
            "unknown_source_channel",
        })

    def test_unknown_source_channel_writes_dataset_flag(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(
            records=[_sample_record()],
            dataset_overrides={"source_channel": "unknown_channel"},
        )
        result = write(session, ref, body)
        session.commit()
        dataset = session.get(models.JobDemandDataset, result.dataset_id)
        assert dataset.source_channel == "unknown_channel"
        assert dataset.quality_summary.get("unknown_source_channel") == 1

    def test_known_source_channel_does_not_flag(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(records=[_sample_record()])
        result = write(session, ref, body)
        session.commit()
        dataset = session.get(models.JobDemandDataset, result.dataset_id)
        assert "unknown_source_channel" not in dataset.quality_summary

    def test_blank_source_channel_falls_back_to_excel_upload(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(
            records=[_sample_record()],
            dataset_overrides={"source_channel": ""},
        )
        result = write(session, ref, body)
        session.commit()
        dataset = session.get(models.JobDemandDataset, result.dataset_id)
        assert dataset.source_channel == "excel_upload"
        assert "unknown_source_channel" not in dataset.quality_summary

    def test_quality_summary_aggregates_per_record_flags(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(
            records=[
                _sample_record(key="r1", source_published_at="bad-date"),
                _sample_record(key="r2", source_published_at="also-bad"),
                _sample_record(key="r3"),
            ]
        )
        result = write(session, ref, body)
        session.commit()
        dataset = session.get(models.JobDemandDataset, result.dataset_id)
        assert dataset.quality_summary.get("published_at_unparsed") == 2


# ---------------------------------------------------------------------------
# Audit (§七)
# ---------------------------------------------------------------------------


class TestAuditEvents:
    def test_two_audit_events_emitted_on_success(self, session):
        ref = _seed_normalized_ref(session)
        write(session, ref, _record_body(records=[_sample_record()]))
        session.commit()
        events = list(
            session.scalars(
                select(models.AuditLog).where(
                    models.AuditLog.event_type.in_([
                        AuditEventType.JOB_DEMAND_DATASET_PERSISTED,
                        AuditEventType.JOB_DEMAND_RECORDS_PERSISTED,
                    ])
                )
            ).all()
        )
        assert len(events) == 2
        types = {e.event_type for e in events}
        assert types == {
            AuditEventType.JOB_DEMAND_DATASET_PERSISTED,
            AuditEventType.JOB_DEMAND_RECORDS_PERSISTED,
        }

    def test_dataset_audit_targets_dataset_row(self, session):
        ref = _seed_normalized_ref(session)
        result = write(session, ref, _record_body(records=[_sample_record()]))
        session.commit()
        event = session.scalar(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.JOB_DEMAND_DATASET_PERSISTED
            )
        )
        assert event.target_type == "job_demand_dataset"
        assert event.target_id == result.dataset_id
        assert event.summary["normalized_ref_id"] == ref.id
        assert event.summary["source_channel"] == "excel_upload"

    def test_records_audit_carries_inserted_count(self, session):
        ref = _seed_normalized_ref(session)
        body = _record_body(
            records=[
                _sample_record(key="a"),
                _sample_record(key="b"),
                _sample_record(key="a"),  # duplicate
                {"trace": {}},  # empty / placeholder
            ]
        )
        write(session, ref, body)
        session.commit()
        event = session.scalar(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.JOB_DEMAND_RECORDS_PERSISTED
            )
        )
        assert event.summary["records_inserted"] == 2
        assert event.summary["duplicate_count"] == 1
        assert event.summary["invalid_count"] == 1


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------


class TestResult:
    def test_returns_domain_normalize_result(self, session):
        ref = _seed_normalized_ref(session)
        result = write(session, ref, _record_body(records=[_sample_record()]))
        assert result.domain_profile == DOMAIN_PROFILE
        assert result.skipped is False
        assert result.dataset_id is not None
        assert result.records_written == 1
        assert isinstance(result.quality_summary, dict)

    def test_skips_when_record_body_lacks_dataset_records(self, session):
        ref = _seed_normalized_ref(session)
        result = write(session, ref, {"some_other_shape": []})
        assert result.skipped is True
        assert result.reason == "record_body_shape_invalid"
        assert result.dataset_id is None

    def test_skips_when_record_body_not_dict(self, session):
        ref = _seed_normalized_ref(session)
        result = write(session, ref, [])  # type: ignore[arg-type]
        assert result.skipped is True
        assert result.reason == "record_body_not_a_dict"


# ---------------------------------------------------------------------------
# Dispatcher integration — writer wired into dispatch_domain_normalize
# ---------------------------------------------------------------------------


class TestDispatcherIntegration:
    def test_dispatcher_routes_job_demand_profile_to_writer(self, session):
        import json
        ref = _seed_normalized_ref(session)
        storage = InMemoryObjectStorage()
        key = "normalized/ref-b4.json"
        storage.put_bytes(
            key,
            json.dumps({
                "schema_version": "normalized-record.v2",
                "domain_profile": "job_demand.v1",
                "record_body": _record_body(records=[_sample_record()]),
            }).encode("utf-8"),
            "application/json",
        )
        # Set object_uri so dispatcher locates the payload via storage.
        ref.object_uri = f"s3://bucket/{key}"
        session.flush()

        result = dispatch_domain_normalize(session, ref, storage=storage)
        session.commit()

        assert result.skipped is False
        assert result.domain_profile == "job_demand.v1"
        assert result.dataset_id is not None
        assert result.records_written == 1
        dataset = session.scalar(select(models.JobDemandDataset))
        assert dataset is not None
        assert dataset.normalized_ref_id == ref.id

    def test_dispatcher_skips_when_payload_missing(self, session):
        ref = _seed_normalized_ref(session)
        # Storage carries no key matching the ref's object_uri.
        result = dispatch_domain_normalize(session, ref, storage=InMemoryObjectStorage())
        assert result.skipped is True
        assert result.reason == "empty_record_body"

    def test_dispatcher_skips_when_record_body_wrong_shape(self, session):
        import json
        # When B1 dumps ParsedWorkbook directly into record_body (no
        # `{dataset, records}` wrapper), the writer skips gracefully so
        # governance can still act on the normalized_ref.
        ref = _seed_normalized_ref(session)
        storage = InMemoryObjectStorage()
        key = "normalized/ref-b4.json"
        storage.put_bytes(
            key,
            json.dumps({
                "record_body": {"sheets": [{"name": "Sheet1"}], "parser_version": "x"},
            }).encode("utf-8"),
            "application/json",
        )
        ref.object_uri = f"s3://bucket/{key}"
        session.flush()

        result = dispatch_domain_normalize(session, ref, storage=storage)
        assert result.skipped is True
        assert result.reason == "record_body_shape_invalid"


# ---------------------------------------------------------------------------
# Unique index — DB enforces (dataset_id, fingerprint)
# ---------------------------------------------------------------------------


class TestUniqueConstraint:
    def test_unique_constraint_in_metadata(self):
        """Schema-level check (no DB round-trip). Tests in
        `tests/test_b4_job_demand_migration.py` exercise the live DB."""
        constraints = {
            c.name for c in models.JobDemandRecord.__table__.constraints
            if hasattr(c, "name") and c.name
        }
        assert "uq_jdr_dataset_fingerprint" in constraints
