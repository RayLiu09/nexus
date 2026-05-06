from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import JobStatus
from nexus_app.models import utcnow


def claim_jobs(
    session: Session,
    worker_id: str,
    batch_size: int = 4,
    lease_seconds: int = 120,
) -> list[models.Job]:
    """Claim queued jobs using FOR UPDATE SKIP LOCKED semantics.

    Uses a CTE + UPDATE pattern for atomicity. SQLite (used in tests) does not
    support FOR UPDATE SKIP LOCKED, so a fallback path handles it by selecting
    then updating within the same transaction.
    """
    now = utcnow()
    lock_expires = now + timedelta(seconds=lease_seconds)
    is_sqlite = "sqlite" in str(session.bind.dialect.name if session.bind else "")

    if is_sqlite:
        candidates = list(
            session.scalars(
                select(models.Job)
                .where(
                    models.Job.status == JobStatus.QUEUED,
                    models.Job.next_run_at <= now,
                )
                .order_by(models.Job.priority.asc(), models.Job.created_at.asc())
                .limit(batch_size)
            ).all()
        )
        if not candidates:
            return []
        job_ids = [j.id for j in candidates]
        session.execute(
            models.Job.__table__.update()
            .where(models.Job.id.in_(job_ids))
            .values(
                status=JobStatus.RUNNING.value,
                locked_by=worker_id,
                locked_at=now,
                lock_expires_at=lock_expires,
                heartbeat_at=now,
                attempt_count=models.Job.attempt_count + 1,
                updated_at=now,
            )
        )
        session.commit()
        return [session.get(models.Job, jid) for jid in job_ids]

    result = session.execute(
        text(
            """
            WITH candidate AS (
                SELECT id FROM job
                WHERE status = 'queued'
                  AND next_run_at <= :now
                ORDER BY priority ASC, created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT :batch_size
            )
            UPDATE job
            SET status = 'running',
                locked_by = :worker_id,
                locked_at = :now,
                lock_expires_at = :lock_expires,
                heartbeat_at = :now,
                attempt_count = attempt_count + 1,
                updated_at = :now
            WHERE id IN (SELECT id FROM candidate)
            RETURNING id
            """
        ),
        {
            "now": now,
            "batch_size": batch_size,
            "worker_id": worker_id,
            "lock_expires": lock_expires,
        },
    )
    job_ids = [row[0] for row in result.fetchall()]
    session.commit()
    return [session.get(models.Job, jid) for jid in job_ids]


def update_heartbeat(session: Session, job_id: str, lease_seconds: int = 120) -> None:
    now = utcnow()
    lock_expires = now + timedelta(seconds=lease_seconds)
    session.execute(
        models.Job.__table__.update()
        .where(models.Job.id == job_id)
        .values(heartbeat_at=now, lock_expires_at=lock_expires, updated_at=now)
    )
    session.commit()
