from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.data_sync.plans import create_plan
from nexus_app.data_sync.runs import RunConflict, RunError, create_scheduled_run
from nexus_app.enums import AuditEventType


def test_scheduled_run_replays_slot_and_respects_active_plan(session):
    plan = create_plan(
        session, name="Monthly jobs", provider_code="mock", frequency="1_month",
        query_config={"keyword": "jobs"}, actor_id="admin", idempotency_key="plan-1",
        trace_id="trace-plan",
    )
    slot = datetime(2026, 10, 1, tzinfo=timezone.utc)
    first = create_scheduled_run(session, plan_id=plan.id, scheduled_slot=slot, trace_id="trace-run")
    assert first.status == "queued"
    assert first.created_by is None
    assert first.scheduled_slot.replace(tzinfo=timezone.utc) == slot
    assert create_scheduled_run(
        session, plan_id=plan.id, scheduled_slot=slot, trace_id="trace-repeat"
    ).id == first.id
    with pytest.raises(RunConflict):
        create_scheduled_run(
            session, plan_id=plan.id,
            scheduled_slot=datetime(2026, 11, 1, tzinfo=timezone.utc), trace_id="trace-next",
        )
    assert session.scalar(select(models.AuditLog).where(
        models.AuditLog.target_id == first.id,
        models.AuditLog.event_type == AuditEventType.DATA_SYNC_RUN_QUEUED,
    )).actor_type == "system"
    with pytest.raises(RunError):
        create_scheduled_run(
            session, plan_id=plan.id, scheduled_slot=datetime(2026, 12, 1), trace_id="trace-naive",
        )
    first.status = "succeeded"
    session.commit()
    plan.status = "paused"
    session.commit()
    with pytest.raises(RunConflict):
        create_scheduled_run(
            session, plan_id=plan.id,
            scheduled_slot=datetime(2026, 11, 1, tzinfo=timezone.utc), trace_id="trace-paused",
        )
