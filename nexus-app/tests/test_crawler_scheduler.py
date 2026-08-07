"""Tests for the cron-driven CrawlerScheduler."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from nexus_app import models
from nexus_app.crawler.scheduler import CrawlerScheduler
from nexus_app.crawler.scheduling import (
    InvalidCronError,
    compute_next_run,
    validate_cron,
)
from nexus_app.database import Base
from nexus_app.enums import AuditEventType


UTC = timezone.utc


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


@pytest.fixture()
def db_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False,
        future=True,
    )
    return factory


def _seed_plan(
    factory: sessionmaker[Session],
    *,
    execution_mode: str = "scheduled",
    schedule_cron: str | None = "*/5 * * * *",
    next_run_at: datetime | None = None,
    status: str = "active",
    last_run_id: str | None = None,
) -> str:
    plan = models.CrawlerPlan(
        name="test-plan",
        connector_type="websearch",
        connector_version="custom",
        mode="custom",
        topic_keywords=[],
        content_goals=[],
        classification_hints=[],
        target_sites=[],
        execution_mode=execution_mode,
        schedule_cron=schedule_cron,
        next_run_at=next_run_at,
        last_run_id=last_run_id,
        crawl_policy={},
        search_policy={},
        pipeline_policy={},
        status=status,
    )
    with factory() as session:
        session.add(plan)
        session.commit()
        return plan.id


class _StubRun:
    def __init__(self, run_id: str, status: str = "succeeded") -> None:
        self.id = run_id
        self.status = status


def test_validate_cron_rejects_blank_and_bad_expressions():
    with pytest.raises(InvalidCronError):
        validate_cron("")
    with pytest.raises(InvalidCronError):
        validate_cron("not-a-cron")


def test_compute_next_run_returns_future_time():
    now = datetime.now(UTC)
    nxt = compute_next_run("*/5 * * * *", base=now)
    assert nxt > now


def test_compute_next_run_interprets_cron_in_provided_tz():
    # "0 16 * * *" in Asia/Shanghai == 08:00 UTC.
    base = datetime(2026, 8, 7, 6, 0, tzinfo=UTC)  # 14:00 CST
    nxt = compute_next_run("0 16 * * *", base=base, tz="Asia/Shanghai")
    assert nxt.tzinfo == UTC
    assert nxt == datetime(2026, 8, 7, 8, 0, tzinfo=UTC)


def test_compute_next_run_defaults_to_utc():
    base = datetime(2026, 8, 7, 6, 0, tzinfo=UTC)
    nxt = compute_next_run("0 16 * * *", base=base)  # default tz=UTC
    assert nxt == datetime(2026, 8, 7, 16, 0, tzinfo=UTC)


def test_tick_fires_due_plan_and_advances_next_run(db_factory):
    now_seed = datetime.now(UTC) - timedelta(minutes=1)
    plan_id = _seed_plan(db_factory, next_run_at=now_seed)

    fired_runs: list[str] = []

    def fake_run_plan(session: Session, plan_id: str):
        run = models.CrawlerRun(
            plan_id=plan_id, status="succeeded",
            connector_type="websearch", connector_version="custom",
            summary={"stub": True},
        )
        session.add(run)
        session.flush()
        fired_runs.append(run.id)
        return _StubRun(run.id)

    scheduler = CrawlerScheduler(db_factory, run_plan=fake_run_plan)

    fired = scheduler.tick()
    assert fired == 1
    assert len(fired_runs) == 1

    with db_factory() as session:
        plan = session.get(models.CrawlerPlan, plan_id)
        assert plan.next_run_at is not None
        # SQLite drops tz info; compare naive against naive.
        assert _naive(plan.next_run_at) > datetime.now(UTC).replace(tzinfo=None)
        assert plan.last_run_id == fired_runs[0]
        assert plan.last_fire_at is not None
        audits = session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type
                == AuditEventType.CRAWLER_RUN_STARTED_BY_SCHEDULE
            )
        ).all()
        assert len(audits) == 1

    # A second tick without advancing the clock must not fire again.
    fired_again = scheduler.tick()
    assert fired_again == 0


def test_tick_skips_when_previous_run_still_active(db_factory):
    now_seed = datetime.now(UTC) - timedelta(minutes=1)
    plan_id = _seed_plan(db_factory, next_run_at=now_seed)

    with db_factory() as session:
        prior = models.CrawlerRun(
            plan_id=plan_id, status="running",
            connector_type="websearch", connector_version="custom",
            summary={},
        )
        session.add(prior)
        session.flush()
        plan = session.get(models.CrawlerPlan, plan_id)
        plan.last_run_id = prior.id
        session.commit()

    started = 0

    def fake_run_plan(session: Session, plan_id: str):
        nonlocal started
        started += 1
        return _StubRun("should-not-happen")

    scheduler = CrawlerScheduler(db_factory, run_plan=fake_run_plan)
    fired = scheduler.tick()

    assert fired == 0
    assert started == 0
    with db_factory() as session:
        plan = session.get(models.CrawlerPlan, plan_id)
        # next_run_at still advances, just no new run was launched.
        # SQLite drops tz info; compare naive against naive.
        assert _naive(plan.next_run_at) > datetime.now(UTC).replace(tzinfo=None)
        skipped = session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type
                == AuditEventType.CRAWLER_RUN_SKIPPED_BY_SCHEDULE
            )
        ).all()
        assert len(skipped) == 1
        assert skipped[0].summary["reason"] == "previous_still_running"


def test_tick_ignores_paused_schedule(db_factory):
    now_seed = datetime.now(UTC) - timedelta(minutes=1)
    with db_factory() as session:
        plan = models.CrawlerPlan(
            name="paused-plan",
            connector_type="websearch",
            connector_version="custom",
            mode="custom",
            topic_keywords=[],
            content_goals=[],
            classification_hints=[],
            target_sites=[],
            execution_mode="scheduled",
            schedule_cron="*/5 * * * *",
            schedule_paused=True,
            next_run_at=now_seed,
            crawl_policy={},
            search_policy={},
            pipeline_policy={},
            status="active",
        )
        session.add(plan)
        session.commit()

    started = 0

    def fake_run_plan(session: Session, plan_id: str):
        nonlocal started
        started += 1
        return _StubRun("should-not-happen")

    scheduler = CrawlerScheduler(db_factory, run_plan=fake_run_plan)
    fired = scheduler.tick()

    assert fired == 0
    assert started == 0


def test_tick_clears_next_run_at_for_invalid_cron(db_factory):
    now_seed = datetime.now(UTC) - timedelta(minutes=1)
    plan_id = _seed_plan(
        db_factory,
        schedule_cron="not-a-cron",
        next_run_at=now_seed,
    )

    scheduler = CrawlerScheduler(db_factory, run_plan=lambda *_: _StubRun("nope"))
    fired = scheduler.tick()

    assert fired == 0
    with db_factory() as session:
        plan = session.get(models.CrawlerPlan, plan_id)
        assert plan.next_run_at is None
