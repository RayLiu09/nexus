"""GovernanceRulesService — CRUD and version management for governance rules."""

from __future__ import annotations

import logging
import uuid
from datetime import timezone, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.rules_registry import get_governance_rules_registry
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType, GovernanceRulesVersionStatus

logger = logging.getLogger(__name__)


class GovernanceRulesService:
    """CRUD operations for ``GovernanceRulesVersion`` with DB row-level locking.

    Creating a new version automatically:
    1. Locks the current active row (``SELECT ... FOR UPDATE``)
    2. Archives the old active row (status → archived)
    3. Inserts a new active row with version = old.version + 1
    4. Writes audit log entries
    5. Hot-reloads the process-level ``GovernanceRulesRegistry`` singleton
    """

    @staticmethod
    def get_active(session: Session) -> models.GovernanceRulesVersion | None:
        """Return the currently active rules version, or None."""
        return session.scalars(
            select(models.GovernanceRulesVersion)
            .where(models.GovernanceRulesVersion.status == GovernanceRulesVersionStatus.ACTIVE)
        ).first()

    @staticmethod
    def get_active_or_raise(session: Session) -> models.GovernanceRulesVersion:
        row = GovernanceRulesService.get_active(session)
        if row is None:
            raise RuntimeError("No active governance rules version found")
        return row

    @staticmethod
    def get_version_history(session: Session) -> list[models.GovernanceRulesVersion]:
        """Return all versions ordered by version descending."""
        return list(
            session.scalars(
                select(models.GovernanceRulesVersion)
                .order_by(models.GovernanceRulesVersion.version.desc())
            ).all()
        )

    @staticmethod
    def get_version(
        session: Session, version_id: str
    ) -> models.GovernanceRulesVersion | None:
        return session.get(models.GovernanceRulesVersion, version_id)

    @staticmethod
    def create_new_version(
        session: Session,
        rules_content: dict[str, Any],
        *,
        change_summary: str | None = None,
        user_id: str | None = None,
    ) -> models.GovernanceRulesVersion:
        """Create a new active rules version, archiving the previous one.

        Parameters
        ----------
        session:
            Active DB session (caller should manage transaction boundaries).
        rules_content:
            The full rules_content dict (validated by caller).
        change_summary:
            Short description of what changed (audit trail).
        user_id:
            ID of the user or system principal making the change.

        Returns
        -------
        GovernanceRulesVersion
            The newly created active version.
        """
        # 1. Lock current active row
        current = session.scalars(
            select(models.GovernanceRulesVersion)
            .where(models.GovernanceRulesVersion.status == GovernanceRulesVersionStatus.ACTIVE)
            .with_for_update()
        ).first()

        new_version_number = 1
        if current is not None:
            new_version_number = current.version + 1
            # Archive old active
            current.status = GovernanceRulesVersionStatus.ARCHIVED
            current.updated_at = datetime.now(timezone.utc)
            session.add(current)
            session.flush()

            write_audit(
                session,
                AuditEventType.GOVERNANCE_RULES_VERSION_ARCHIVED,
                target_type="governance_rules_version",
                target_id=current.id,
                summary={
                    "archived_version": current.version,
                    "new_version": new_version_number,
                    "change_summary": change_summary,
                },
                actor_id=user_id,
                trace_id=str(uuid.uuid4()),
            )

        trace_id = str(uuid.uuid4())
        schema_version = rules_content.get("schema_version", "unknown")

        new_version = models.GovernanceRulesVersion(
            version=new_version_number,
            status=GovernanceRulesVersionStatus.ACTIVE,
            rules_content=rules_content,
            schema_version=schema_version,
            change_summary=change_summary,
            created_by=user_id,
            trace_id=trace_id,
        )
        session.add(new_version)
        session.flush()

        write_audit(
            session,
            AuditEventType.GOVERNANCE_RULES_VERSION_CREATED,
            target_type="governance_rules_version",
            target_id=new_version.id,
            summary={
                "version": new_version_number,
                "schema_version": schema_version,
                "change_summary": change_summary,
                "classifications_count": len(rules_content.get("classifications", [])),
            },
            actor_id=user_id,
            trace_id=trace_id,
        )

        # Hot-reload the process-level singleton
        registry = get_governance_rules_registry()
        registry.reload(session)

        logger.info(
            "Created governance rules version %d (id=%s) by user=%s",
            new_version_number, new_version.id, user_id,
        )
        return new_version
