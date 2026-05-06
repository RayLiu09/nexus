from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import AuditEventType


def write_audit(
    session: Session,
    event_type: AuditEventType,
    target_type: str,
    target_id: str,
    trace_id: str | None,
    summary: dict[str, Any],
    *,
    actor_type: str | None = None,
    actor_id: str | None = None,
) -> models.AuditLog:
    audit = models.AuditLog(
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        trace_id=trace_id,
        summary=summary,
    )
    session.add(audit)
    session.flush()
    return audit
