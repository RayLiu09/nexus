from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.sql.dml import Insert

from nexus_app import models
from scripts.backfill_raw_job_title_region import backfill


def test_backfill_dry_run_batched_replay_and_audit_preserve_originals(session):
    timestamp = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for job_id in ("a", "b", "c"):
        session.add(models.RawJob(id=job_id, title_raw="【急聘】高级运营（MJ12345）",
                                  address_raw="北京市", created_at=timestamp, updated_at=timestamp))
    session.add(models.RawJob(id="d", title_raw="原名", title_normalized="已确认名称", region="已确认地区"))
    session.add(models.RawJobProvenance(
        raw_job_id="a", provider_code="crawler", upstream_record_id="upstream-a",
        source_name="example", source_url="https://example.test/a", external_task_id="task",
        source_page=1, keyword="运营", query_region="杭州市", collected_at=timestamp,
        received_at=timestamp, raw_record_hash="original-hash", upstream_payload_hash="original-payload",
        raw_record={"region": "杭州市", "fields": {"title": "原始标题"}},
    ))
    session.commit()
    summary = backfill(session, batch_size=1)
    assert summary["scanned"] == 4 and summary["updated"] == 3
    assert (summary["title_updates"], summary["region_updates"]) == (3, 1)
    assert session.get(models.RawJob, "a").title_normalized is None
    assert session.scalar(select(func.count()).select_from(models.AuditLog)) == 0

    summary = backfill(session, apply=True, batch_size=1)
    session.expire_all()
    first = session.get(models.RawJob, "a")
    assert first.title_normalized == "高级运营" and first.region == "杭州市"
    assert first.title_raw == "【急聘】高级运营（MJ12345）" and first.address_raw == "北京市"
    assert first.created_at.replace(tzinfo=timezone.utc) == timestamp
    assert first.updated_at.replace(tzinfo=timezone.utc) == timestamp
    assert session.get(models.RawJob, "b").region is None
    assert session.get(models.RawJob, "d").title_normalized == "已确认名称"
    assert session.get(models.RawJob, "d").region == "已确认地区"
    provenance = session.get(models.RawJobProvenance, "a")
    assert provenance.raw_record_hash == "original-hash"
    assert provenance.received_at.replace(tzinfo=timezone.utc) == timestamp
    assert provenance.raw_record["fields"]["title"] == "原始标题"
    audits = session.scalars(select(models.AuditLog)).all()
    assert len(audits) == 3
    assert all(audit.actor_id == "backfill_raw_job_title_region" and audit.trace_id for audit in audits)
    assert "原始标题" not in str([audit.summary for audit in audits])
    assert backfill(session, apply=True, batch_size=2)["updated"] == 0
    assert session.scalar(select(func.count()).select_from(models.AuditLog)) == 3


def test_backfill_resume_only_visits_rows_after_cursor(session):
    session.add_all([models.RawJob(id=key, title_raw="【急聘】运营") for key in ("a", "b")])
    session.commit()
    assert backfill(session, apply=True, after_id="a", batch_size=1)["scanned"] == 1
    assert session.get(models.RawJob, "a").title_normalized is None
    assert session.get(models.RawJob, "b").title_normalized == "运营"


def test_reclean_titles_is_explicit_dry_run_audited_and_repeatable(session):
    session.add(models.RawJob(id="a", title_raw="广告标识设计师(周末双休+地铁直达)",
                              title_normalized="广告标识设计师(周末双休+地铁直达)",
                              region="杭州市", address_raw="北京"))
    session.commit()
    assert backfill(session)["updated"] == 0
    assert backfill(session, reclean_titles=True)["title_updates"] == 1
    assert session.get(models.RawJob, "a").title_normalized.endswith("地铁直达)")
    result = backfill(session, reclean_titles=True, apply=True)
    assert result["updated"] == result["title_updates"] == 1
    assert result["region_updates"] == 0
    session.expire_all()
    job = session.get(models.RawJob, "a")
    assert job.title_normalized == "广告标识设计师"
    assert job.region == "杭州市" and job.address_raw == "北京"
    audit = session.scalar(select(models.AuditLog))
    assert audit.summary["title_cleaning_version"] == "simple-v2"
    assert audit.summary["fields"] == ["title_normalized"]
    assert backfill(session, reclean_titles=True, apply=True)["updated"] == 0


def test_backfill_failed_audit_rolls_back_current_batch_and_keeps_prior_checkpoint(session, monkeypatch):
    session.add_all([models.RawJob(id=key, title_raw="【急聘】运营") for key in ("a", "b")])
    session.commit()
    execute = session.execute
    audit_batches = 0

    def fail_second_audit(statement, *args, **kwargs):
        nonlocal audit_batches
        if isinstance(statement, Insert) and statement.table.name == "audit_log":
            audit_batches += 1
            if audit_batches == 2:
                raise RuntimeError("simulated audit insert failure")
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", fail_second_audit)
    with pytest.raises(RuntimeError, match="simulated audit"):
        backfill(session, apply=True, batch_size=1)
    session.rollback()
    assert session.get(models.RawJob, "a").title_normalized == "运营"
    assert session.get(models.RawJob, "b").title_normalized is None
    assert session.scalar(select(func.count()).select_from(models.AuditLog)) == 1
