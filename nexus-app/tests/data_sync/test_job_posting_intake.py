from copy import deepcopy

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from nexus_app import models
from nexus_app.data_sync.job_posting_intake import JobPostingResultHandler
from nexus_app.data_sync.plans import create_plan
from nexus_app.data_sync.runs import create_manual_run
from nexus_app.data_sync.runtime import DataSyncExecutor


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
    provenance = session.scalar(select(models.RawJobProvenance).where(
        models.RawJobProvenance.upstream_record_id == record["recordId"]
    ))
    assert provenance.raw_record == record
    assert provenance.raw_record["fields"]["newField"] == {"retained": True}
    assert provenance.source_job_id == "source-1"


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
