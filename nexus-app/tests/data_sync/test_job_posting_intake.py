from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker

from nexus_app import models
from nexus_app.data_sync.job_posting_intake import JobPostingResultHandler
from nexus_app.data_sync.job_posting_fields import JobPostingMetrics
from nexus_app.data_sync.plans import create_plan
from nexus_app.data_sync.runs import create_manual_run
from nexus_app.data_sync.runtime import DataSyncExecutor, SyncRuntimeError


def _record(record_id, *, title="数据化运营助理", source_job_id="source-1"):
    return {
        "recordId": record_id,
        "taskId": "7e834516-20f9-4051-9946-158411265ef5",
        "source": "zhaopin",
        "sourceJobId": source_job_id,
        "sourceUrl": "https://example.test/jobs/1",
        "keyword": "数据化运营助理",
        "region": "杭州市",
        "page": 1,
        "fields": {
            "title": title,
            "companyName": "测试企业",
            "salaryText": "1-1.5万",
            "description": None,
            "jobResponsibilitiesText": "负责数据分析",
            "jobRequirementsText": "熟悉 SQL",
            "qualificationsText": None,
            "otherMattersText": "优先考虑相关经验",
            "skillsText": "SQL, Python",
            "companyFinancingText": None,
            "newField": {"retained": True},
        },
        "collectedAt": "2026-10-08T06:10:00Z",
        "createdAt": "2026-10-08T06:10:01Z",
        "payloadHash": "sha256:" + "a" * 64,
    }


def _run(session, suffix):
    plan = create_plan(
        session, name=f"Raw job plan {suffix}", provider_code="mock",
        frequency="1_month", query_config={"keyword": "jobs"},
        actor_id="admin", idempotency_key=f"raw-plan-{suffix}", trace_id="raw-plan",
    )
    return create_manual_run(
        session, plan_id=plan.id, actor_id="admin",
        idempotency_key=f"raw-run-{suffix}", trace_id="raw-run",
    )


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_raw_job_fields_are_separate_from_provenance_and_replay_is_idempotent(session):
    handler = JobPostingResultHandler()
    first_run = _run(session, "one")
    record = _record("8a21b482-39da-48cc-a462-8d5880ee182d")
    assert handler.accept_page(session, first_run, [record]).accepted == 1
    assert handler.accept_page(session, first_run, [record]).duplicate == 1
    session.commit()

    second_run = _run(session, "two")
    assert handler.accept_page(session, second_run, [record]).duplicate == 1
    later = deepcopy(record)
    later["recordId"] = "1925ba72-61b8-46c9-82c9-b5c6ff0040bd"
    later["fields"]["salaryText"] = "2-3万"
    assert handler.accept_page(session, second_run, [later]).accepted == 1
    session.commit()

    assert _count(session, models.RawJob) == 2
    assert _count(session, models.RawJobProvenance) == 2
    jobs = list(session.scalars(select(models.RawJob).order_by(models.RawJob.salary_raw)))
    assert [job.salary_raw for job in jobs] == ["1-1.5万", "2-3万"]
    assert jobs[0].responsibilities_raw == "负责数据分析"
    assert jobs[0].requirements_raw == "熟悉 SQL"
    assert jobs[0].description_raw is None
    assert jobs[0].title_normalized == "数据化运营助理"
    assert jobs[0].region == "杭州市"
    provenance = session.scalar(select(models.RawJobProvenance).where(
        models.RawJobProvenance.upstream_record_id == record["recordId"]
    ))
    assert provenance.raw_record == record
    assert provenance.raw_record["fields"]["newField"] == {"retained": True}
    assert provenance.source_job_id == "source-1"


def test_intake_cleans_title_and_copies_collection_region_without_address_inference(session):
    record = _record("cleaned", title="【急聘】高级电商运营（MJ000966）")
    record["fields"]["addressText"] = "北京市海淀区"
    handler = JobPostingResultHandler()
    run = _run(session, "cleaned")
    assert handler.accept_page(session, run, [record]).accepted == 1
    job = session.scalar(select(models.RawJob))
    assert job.title_raw == record["fields"]["title"]
    assert job.title_normalized == "高级电商运营"
    assert job.region == "杭州市"
    assert job.address_raw == "北京市海淀区"
    assert handler.accept_page(session, run, [record]).duplicate == 1
    provenance = session.scalar(select(models.RawJobProvenance))
    assert provenance.query_region == job.region
    assert provenance.raw_record == record


def test_intake_missing_region_does_not_fall_back_to_address(session):
    record = _record("no-region")
    record.pop("region")
    record["fields"]["addressText"] = "杭州市"
    JobPostingResultHandler().accept_page(session, _run(session, "no-region"), [record])
    assert session.scalar(select(models.RawJob)).region is None


def test_optional_metrics_are_typed_and_separate_from_address_and_collection_scope(session):
    record = _record("metrics")
    record["region"] = "广东省"
    record["fields"].update({
        "addressText": "湛江市霞山区人民大道1号",
        "locationText": "湛江·霞山区", "hiringText": "招聘3人", "hiringCount": 3,
        "publishTimeText": "2026-11-19 09:30发布", "publishedDate": "2026-11-19",
        "publishedAt": "2026-11-19T09:30:00+08:00",
    })
    original = deepcopy(record)
    run = _run(session, "metrics")
    handler = JobPostingResultHandler()
    assert handler.accept_page(session, run, [record]).accepted == 1
    session.commit()
    job = session.scalar(select(models.RawJob))
    assert job.location_text == "湛江·霞山区"
    assert job.address_raw == "湛江市霞山区人民大道1号"
    assert job.region == "广东省"
    assert job.hiring_raw == "招聘3人"
    assert job.hiring_count == 3
    assert job.publish_time_text == "2026-11-19 09:30发布"
    assert job.published_date == date(2026, 11, 19)
    # SQLite lacks timezone storage; PostgreSQL DDL is verified separately.
    assert job.published_at.replace(tzinfo=None) == datetime(2026, 11, 19, 9, 30)
    typed = JobPostingMetrics.model_validate(record["fields"])
    assert typed.publishedAt.utcoffset() == timedelta(hours=8)
    assert session.scalar(select(models.RawJobProvenance)).raw_record == original
    assert record == original
    assert handler.accept_page(session, run, [record]).duplicate == 1
    changed = deepcopy(record)
    changed["fields"]["hiringCount"] = 4
    with pytest.raises(SyncRuntimeError) as caught:
        handler.accept_page(session, run, [changed])
    assert caught.value.code == "raw_record_conflict"


@pytest.mark.parametrize("metrics", [
    {},
    dict.fromkeys(("locationText", "hiringCount", "publishTimeText", "publishedDate", "publishedAt")),
    {"hiringCount": 0},
    {"publishTimeText": "昨日发布", "publishedDate": "2026-11-19"},
])
def test_partial_or_missing_metrics_are_not_inferred(session, metrics):
    record = _record("partial-metrics")
    record["fields"].update({"addressText": "杭州市", "hiringText": "招聘若干人", **metrics})
    run = _run(session, "partial-metrics")
    handler = JobPostingResultHandler()
    handler.accept_page(session, run, [record])
    session.commit()
    job = session.scalar(select(models.RawJob))
    assert job.hiring_count == metrics.get("hiringCount")
    assert job.location_text is None
    assert job.publish_time_text == metrics.get("publishTimeText")
    expected_date = date.fromisoformat(metrics["publishedDate"]) if metrics.get("publishedDate") else None
    assert job.published_date == expected_date
    assert job.published_at is None
    assert session.scalar(select(models.RawJobProvenance)).raw_record == record
    assert handler.accept_page(session, run, [record]).duplicate == 1


@pytest.mark.parametrize("metrics", [
    {"hiringCount": -1}, {"hiringCount": True}, {"hiringCount": "3"},
    {"hiringCount": 1.5}, {"publishedDate": "2026-02-30"},
    {"publishedAt": "2026-11-19T09:30:00"}, {"locationText": 1},
])
def test_direct_intake_rejects_invalid_metrics_without_persisting(session, metrics):
    record = _record("invalid-metrics")
    record["fields"].update(metrics)
    with pytest.raises(SyncRuntimeError) as caught:
        JobPostingResultHandler().accept_page(session, _run(session, "invalid-metrics"), [record])
    assert caught.value.code == "invalid_job_record"
    assert "负责数据分析" not in str(caught.value)
    assert _count(session, models.RawJob) == 0
    assert _count(session, models.RawJobProvenance) == 0


def test_changed_payload_for_same_upstream_id_rolls_back_page(session):
    handler = JobPostingResultHandler()
    run = _run(session, "conflict")
    record = _record("8a21b482-39da-48cc-a462-8d5880ee182d")
    handler.accept_page(session, run, [record])
    session.commit()
    changed = deepcopy(record)
    changed["fields"]["title"] = "different content"
    from nexus_app.data_sync.runtime import SyncRuntimeError
    import pytest
    with pytest.raises(SyncRuntimeError) as caught:
        handler.accept_page(session, run, [changed])
    session.rollback()
    assert caught.value.code == "raw_record_conflict"
    assert _count(session, models.RawJob) == 1
    assert _count(session, models.RawJobProvenance) == 1


def test_runtime_commits_rows_and_cursor_together(session, monkeypatch):
    run = _run(session, "runtime")
    first = _record("8a21b482-39da-48cc-a462-8d5880ee182d")
    second = _record("1925ba72-61b8-46c9-82c9-b5c6ff0040bd", source_job_id="source-2")

    class Adapter:
        result_handler = JobPostingResultHandler()

        def submit(self, *_):
            return {"external_task_id": "external-job"}

        def get_status(self, *_):
            return {"state": "succeeded", "processed_count": 2}

        def fetch_page(self, _provider, _task_id, cursor, _token):
            if cursor is None:
                return {"records": [first], "next_cursor": "page-two"}
            return {"records": [second, first], "next_cursor": None}

    monkeypatch.setattr("nexus_app.data_sync.runtime._provider_code", lambda _: (object(), Adapter()))
    executor = DataSyncExecutor(sessionmaker(bind=session.get_bind(), expire_on_commit=False), worker_id="raw-worker")
    monkeypatch.setattr(executor._tokens, "get_token", lambda *_: "token")
    assert executor.run_once()
    executor.close()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "succeeded"
    assert (refreshed.processed_count, refreshed.success_count, refreshed.skipped_count) == (3, 2, 1)
    assert _count(session, models.RawJob) == 2
    assert _count(session, models.RawJobProvenance) == 2


def test_second_page_conflict_keeps_first_checkpoint(session, monkeypatch):
    run = _run(session, "rollback")
    first = _record("8a21b482-39da-48cc-a462-8d5880ee182d")
    changed = deepcopy(first)
    changed["fields"]["title"] = "conflicting content"

    class Adapter:
        result_handler = JobPostingResultHandler()

        def submit(self, *_):
            return {"external_task_id": "external-job"}

        def get_status(self, *_):
            return {"state": "succeeded"}

        def fetch_page(self, _provider, _task_id, cursor, _token):
            if cursor is None:
                return {"records": [first], "next_cursor": "page-two"}
            return {"records": [changed], "next_cursor": None}

    monkeypatch.setattr("nexus_app.data_sync.runtime._provider_code", lambda _: (object(), Adapter()))
    executor = DataSyncExecutor(sessionmaker(bind=session.get_bind(), expire_on_commit=False), worker_id="raw-worker")
    monkeypatch.setattr(executor._tokens, "get_token", lambda *_: "token")
    assert executor.run_once()
    executor.close()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "failed"
    assert refreshed.failure_summary == "raw_record_conflict"
    assert refreshed.last_cursor == "page-two"
    assert refreshed.processed_count == 1
    assert _count(session, models.RawJob) == 1
    assert _count(session, models.RawJobProvenance) == 1


def test_invalid_metrics_roll_back_whole_page_and_keep_previous_checkpoint(session, monkeypatch, request):
    run = _run(session, "metrics-rollback")
    engine = session.get_bind()
    if engine.dialect.name == "sqlite":
        # sqlite3 legacy mode otherwise RELEASEs a first savepoint as a commit
        # when a transaction has only SELECTs. Match PostgreSQL transactions.
        def begin_transaction(connection):
            connection.exec_driver_sql("BEGIN")

        event.listen(engine, "begin", begin_transaction)
        request.addfinalizer(lambda: event.remove(engine, "begin", begin_transaction))
    first = _record("first-page")
    second = _record("second-page-valid")
    invalid = _record("second-page-invalid")
    invalid["fields"]["hiringCount"] = -1

    class Adapter:
        result_handler = JobPostingResultHandler()

        def submit(self, *_):
            return {"external_task_id": "external-job"}

        def get_status(self, *_):
            return {"state": "succeeded"}

        def fetch_page(self, _provider, _task_id, cursor, _token):
            if cursor is None:
                return {"records": [first], "next_cursor": "page-two"}
            return {"records": [second, invalid], "next_cursor": None}

    monkeypatch.setattr("nexus_app.data_sync.runtime._provider_code", lambda _: (object(), Adapter()))
    executor = DataSyncExecutor(sessionmaker(bind=session.get_bind(), expire_on_commit=False), worker_id="raw-worker")
    monkeypatch.setattr(executor._tokens, "get_token", lambda *_: "token")
    assert executor.run_once()
    executor.close()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "failed"
    assert refreshed.failure_summary == "invalid_job_record"
    assert refreshed.last_cursor == "page-two"
    assert (refreshed.processed_count, refreshed.success_count) == (1, 1)
    assert _count(session, models.RawJob) == 1
    assert session.scalar(select(models.RawJobProvenance)).upstream_record_id == "first-page"
