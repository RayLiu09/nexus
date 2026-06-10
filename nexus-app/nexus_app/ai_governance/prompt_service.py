"""GovernancePromptService — CRUD and version management for prompt templates."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.prompt_registry import get_governance_prompt_registry
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType, GovernancePromptTemplateStatus

logger = logging.getLogger(__name__)


class GovernancePromptService:
    """CRUD operations for ``GovernancePromptTemplate`` with DB row-level locking.

    Updating a prompt template automatically:
    1. Locks the current active row (``SELECT ... FOR UPDATE``)
    2. Archives the old active row (status → archived)
    3. Inserts a new active row with template_version = old.version + 1
    4. Writes audit log entries
    5. Hot-reloads the process-level ``GovernancePromptRegistry`` singleton
    """

    @staticmethod
    def list_templates(session: Session) -> list[models.GovernancePromptTemplate]:
        """Return all templates ordered by task_type and version descending."""
        return list(
            session.scalars(
                select(models.GovernancePromptTemplate)
                .order_by(
                    models.GovernancePromptTemplate.task_type,
                    models.GovernancePromptTemplate.template_version.desc(),
                )
            ).all()
        )

    @staticmethod
    def get_template(
        session: Session, template_id: str
    ) -> models.GovernancePromptTemplate | None:
        return session.get(models.GovernancePromptTemplate, template_id)

    @staticmethod
    def get_active_by_task_type(
        session: Session, task_type: str
    ) -> models.GovernancePromptTemplate | None:
        return session.scalars(
            select(models.GovernancePromptTemplate).where(
                models.GovernancePromptTemplate.task_type == task_type,
                models.GovernancePromptTemplate.status
                == GovernancePromptTemplateStatus.ACTIVE,
            )
        ).first()

    @staticmethod
    def update_template(
        session: Session,
        task_type: str,
        *,
        template_data: dict[str, Any],
        change_summary: str | None = None,
        user_id: str | None = None,
    ) -> models.GovernancePromptTemplate:
        """Create a new active version for *task_type*, archiving the previous one.

        Parameters
        ----------
        session:
            Active DB session (caller manages transaction boundaries).
        task_type:
            The task type to update (e.g. "classification").
        template_data:
            Dict of field overrides.  At minimum must include
            ``prompt_template``; may also override ``litellm_model_alias``,
            ``temperature``, ``max_input_tokens``, ``redaction_policy``,
            ``output_schema_version``, and ``template_name``.
        change_summary:
            Short description of what changed (audit trail).
        user_id:
            ID of the user or system principal making the change.

        Returns
        -------
        GovernancePromptTemplate
            The newly created active template version.
        """
        # 1. Lock current active row for this task_type
        current = session.scalars(
            select(models.GovernancePromptTemplate)
            .where(
                models.GovernancePromptTemplate.task_type == task_type,
                models.GovernancePromptTemplate.status
                == GovernancePromptTemplateStatus.ACTIVE,
            )
            .with_for_update()
        ).first()

        if current is None:
            raise ValueError(f"No active template found for task_type={task_type!r}")

        new_version_number = current.template_version + 1

        # 2. Archive old active
        current.status = GovernancePromptTemplateStatus.ARCHIVED
        current.updated_at = datetime.now(timezone.utc)
        session.add(current)
        session.flush()

        write_audit(
            session,
            AuditEventType.GOVERNANCE_PROMPT_TEMPLATE_ARCHIVED,
            target_type="governance_prompt_template",
            target_id=current.id,
            summary={
                "task_type": task_type,
                "archived_version": current.template_version,
                "new_version": new_version_number,
                "change_summary": change_summary,
            },
            actor_id=user_id,
            trace_id=str(uuid.uuid4()),
        )

        # 3. Create new active version
        trace_id = str(uuid.uuid4())
        new_template = models.GovernancePromptTemplate(
            task_type=task_type,
            template_name=template_data.get(
                "template_name", current.template_name
            ),
            template_version=new_version_number,
            status=GovernancePromptTemplateStatus.ACTIVE,
            prompt_template=template_data.get(
                "prompt_template", current.prompt_template
            ),
            output_schema_version=template_data.get(
                "output_schema_version", current.output_schema_version
            ),
            litellm_model_alias=template_data.get(
                "litellm_model_alias", current.litellm_model_alias
            ),
            temperature=template_data.get("temperature", current.temperature),
            max_input_tokens=template_data.get(
                "max_input_tokens", current.max_input_tokens
            ),
            redaction_policy=template_data.get(
                "redaction_policy", current.redaction_policy
            ),
            change_summary=change_summary,
            created_by=user_id,
            trace_id=trace_id,
        )
        session.add(new_template)
        session.flush()

        write_audit(
            session,
            AuditEventType.GOVERNANCE_PROMPT_TEMPLATE_UPDATED,
            target_type="governance_prompt_template",
            target_id=new_template.id,
            summary={
                "task_type": task_type,
                "version": new_version_number,
                "change_summary": change_summary,
            },
            actor_id=user_id,
            trace_id=trace_id,
        )

        # 4. Hot-reload the process-level singleton
        registry = get_governance_prompt_registry()
        registry.reload(session)

        logger.info(
            "Updated prompt template task_type=%s version=%d (id=%s) by user=%s",
            task_type, new_version_number, new_template.id, user_id,
        )
        return new_template

    @staticmethod
    def disable_template(
        session: Session,
        template_id: str,
        *,
        user_id: str | None = None,
    ) -> models.GovernancePromptTemplate:
        """Disable a prompt template by ID.

        Does NOT create a new version — simply marks the template as disabled.
        Use when a task_type should no longer have an active prompt.
        """
        template = session.get(models.GovernancePromptTemplate, template_id)
        if template is None:
            raise ValueError(f"Template {template_id!r} not found")

        template.status = GovernancePromptTemplateStatus.DISABLED
        template.updated_at = datetime.now(timezone.utc)
        session.add(template)
        session.flush()

        write_audit(
            session,
            AuditEventType.GOVERNANCE_PROMPT_TEMPLATE_DISABLED,
            target_type="governance_prompt_template",
            target_id=template.id,
            summary={
                "task_type": template.task_type,
                "version": template.template_version,
            },
            actor_id=user_id,
            trace_id=str(uuid.uuid4()),
        )

        registry = get_governance_prompt_registry()
        registry.reload(session)

        logger.info(
            "Disabled prompt template id=%s task_type=%s by user=%s",
            template_id, template.task_type, user_id,
        )
        return template
