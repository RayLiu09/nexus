"""Cron-driven CrawlerPlan scheduler.

Runs as a daemon thread inside `WorkerPool`. On every tick it:

1. Reads a batch of due plans (`next_run_at <= now`).
2. For each plan, atomically advances `next_run_at` via CAS
   (`UPDATE ... WHERE next_run_at = :seen`). Losers of the race skip.
3. If the plan's previous scheduler-initiated run is still `running`,
   the tick is recorded as skipped and no new run is started —
   `next_run_at` was already advanced, so the next tick is on the clock.
4. Otherwise calls `crawler.service.run_plan()`. Both success and
   failure paths write a `CrawlerRun` row; the scheduler stamps
   `last_run_id` for the next-tick overlap check.

Multi-replica safety comes from the atomic CAS: even without SELECT FOR
UPDATE, only one process can win the `WHERE next_run_at = :seen` clause.
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable, TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.config import Settings, get_settings
from nexus_app.enums import AuditEventType
from nexus_app.crawler.scheduling import InvalidCronError, compute_next_run

if TYPE_CHECKING:
    from nexus_app.crawler.service import CrawlerRunResult  # noqa: F401

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


RunPlan = Callable[[Session, str], object]


class CrawlerScheduler:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        settings: Settings | None = None,
        run_plan: RunPlan | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings or get_settings()
        self._poll_interval = float(self._settings.crawler_scheduler_poll_interval_seconds)
        self._batch_limit = int(self._settings.crawler_scheduler_batch_limit)
        # Late-bound to avoid a circular import at module load.
        self._run_plan: RunPlan
        if run_plan is not None:
            self._run_plan = run_plan
        else:
            from nexus_app.crawler.service import run_plan as _default_run_plan

            self._run_plan = _default_run_plan

    # ── Public loop ──────────────────────────────────────────────────────
    def run_until_stopped(self, stop_event: threading.Event) -> None:
        logger.info(
            "crawler scheduler started poll_interval=%.1fs batch_limit=%d",
            self._poll_interval,
            self._batch_limit,
        )
        while not stop_event.is_set():
            try:
                fired = self.tick()
                if fired:
                    logger.info("crawler scheduler fired=%d", fired)
            except Exception:
                logger.exception("crawler scheduler tick error")
            stop_event.wait(timeout=self._poll_interval)
        logger.info("crawler scheduler stopping")

    # ── One iteration ────────────────────────────────────────────────────
    def tick(self) -> int:
        now = _utcnow()
        candidates = self._load_due_plans(now)
        fired = 0
        for plan_id, cron, seen_next, last_run_id in candidates:
            try:
                if self._process(plan_id, cron, seen_next, last_run_id, now):
                    fired += 1
            except Exception:
                # Isolate per-plan failures — one bad plan must not stall others.
                logger.exception("crawler scheduler failed to process plan %s", plan_id)
        return fired

    def _load_due_plans(
        self, now: datetime
    ) -> list[tuple[str, str, datetime, str | None]]:
        stmt = (
            select(
                models.CrawlerPlan.id,
                models.CrawlerPlan.schedule_cron,
                models.CrawlerPlan.next_run_at,
                models.CrawlerPlan.last_run_id,
            )
            .where(
                models.CrawlerPlan.execution_mode == "scheduled",
                models.CrawlerPlan.status == "active",
                models.CrawlerPlan.schedule_paused.is_(False),
                models.CrawlerPlan.next_run_at.is_not(None),
                models.CrawlerPlan.next_run_at <= now,
            )
            .order_by(models.CrawlerPlan.next_run_at.asc())
            .limit(self._batch_limit)
        )
        with self._session_factory() as session:
            rows = session.execute(stmt).all()
        return [(r[0], r[1], r[2], r[3]) for r in rows if r[1]]

    def _process(
        self,
        plan_id: str,
        cron: str,
        seen_next: datetime,
        last_run_id: str | None,
        now: datetime,
    ) -> bool:
        try:
            new_next = compute_next_run(cron, base=now, tz=self._settings.crawler_scheduler_tz)
        except InvalidCronError:
            logger.exception("plan %s has invalid cron %r; clearing next_run_at", plan_id, cron)
            with self._session_factory() as session:
                session.execute(
                    update(models.CrawlerPlan)
                    .where(models.CrawlerPlan.id == plan_id)
                    .values(next_run_at=None)
                )
                session.commit()
            return False

        # Atomic claim: only one worker wins the row where next_run_at is
        # still the value we observed. Others get 0 rows and back off.
        with self._session_factory() as session:
            claimed = session.execute(
                update(models.CrawlerPlan)
                .where(
                    models.CrawlerPlan.id == plan_id,
                    models.CrawlerPlan.next_run_at == seen_next,
                )
                .values(next_run_at=new_next, last_fire_at=now)
            )
            session.commit()
            if claimed.rowcount == 0:
                return False

        # Skip if the previous scheduler-initiated run is still going.
        if last_run_id and self._previous_run_still_active(last_run_id):
            self._audit_skip(plan_id, seen_next, new_next, "previous_still_running")
            return False

        return self._start_run(plan_id, seen_next, new_next)

    def _previous_run_still_active(self, run_id: str) -> bool:
        with self._session_factory() as session:
            status = session.execute(
                select(models.CrawlerRun.status).where(models.CrawlerRun.id == run_id)
            ).scalar_one_or_none()
        return status == "running"

    def _start_run(
        self, plan_id: str, seen_next: datetime, new_next: datetime
    ) -> bool:
        trace_id = uuid.uuid4().hex
        with self._session_factory() as session:
            try:
                run = self._run_plan(session, plan_id)
            except Exception:
                logger.exception(
                    "crawler scheduler run_plan failed plan=%s trace=%s",
                    plan_id, trace_id,
                )
                return False
            run_id = getattr(run, "id", None)
            if run_id:
                session.execute(
                    update(models.CrawlerPlan)
                    .where(models.CrawlerPlan.id == plan_id)
                    .values(last_run_id=run_id)
                )
            write_audit(
                session,
                AuditEventType.CRAWLER_RUN_STARTED_BY_SCHEDULE,
                "crawler_plan",
                plan_id,
                trace_id,
                {
                    "fired_for": seen_next.isoformat(),
                    "next_run_at": new_next.isoformat(),
                    "run_id": run_id,
                },
            )
            session.commit()
        return True

    def _audit_skip(
        self,
        plan_id: str,
        seen_next: datetime,
        new_next: datetime,
        reason: str,
    ) -> None:
        with self._session_factory() as session:
            write_audit(
                session,
                AuditEventType.CRAWLER_RUN_SKIPPED_BY_SCHEDULE,
                "crawler_plan",
                plan_id,
                uuid.uuid4().hex,
                {
                    "fired_for": seen_next.isoformat(),
                    "next_run_at": new_next.isoformat(),
                    "reason": reason,
                },
            )
            session.commit()
