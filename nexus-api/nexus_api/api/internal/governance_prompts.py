"""Admin CRUD for governance prompt templates (governance_prompt_template table).

Mount point: ``/internal/v1/admin/governance-prompts``
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.api.internal._helpers import prompt_registry
from nexus_api.responses import response
from nexus_app.ai_governance.prompt_service import GovernancePromptService
from nexus_app.database import get_db

router = APIRouter()


# ── List / Get ────────────────────────────────────────────────────────────


@router.get("/admin/governance-prompts")
def list_prompt_templates(
    request: Request,
    session: Session = Depends(get_db),
):
    """List all governance prompt templates (all versions, grouped by task_type)."""
    templates = GovernancePromptService.list_templates(session)
    return response(
        [
            {
                "id": t.id,
                "task_type": t.task_type,
                "template_name": t.template_name,
                "template_version": t.template_version,
                "status": t.status.value,
                "litellm_model_alias": t.litellm_model_alias,
                "temperature": t.temperature,
                "max_input_tokens": t.max_input_tokens,
                "redaction_policy": t.redaction_policy,
                "change_summary": t.change_summary,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "created_by": t.created_by,
            }
            for t in templates
        ],
        request,
    )


@router.get("/admin/governance-prompts/{template_id}")
def get_prompt_template(
    template_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    """Get a single governance prompt template by ID (returns full content)."""
    tmpl = GovernancePromptService.get_template(session, template_id)
    if tmpl is None:
        raise HTTPException(
            status_code=404,
            detail=f"GovernancePromptTemplate '{template_id}' not found",
        )
    return response(
        {
            "id": tmpl.id,
            "task_type": tmpl.task_type,
            "template_name": tmpl.template_name,
            "template_version": tmpl.template_version,
            "status": tmpl.status.value,
            "prompt_template": tmpl.prompt_template,
            "output_schema_version": tmpl.output_schema_version,
            "litellm_model_alias": tmpl.litellm_model_alias,
            "temperature": tmpl.temperature,
            "max_input_tokens": tmpl.max_input_tokens,
            "redaction_policy": tmpl.redaction_policy,
            "change_summary": tmpl.change_summary,
            "created_at": tmpl.created_at.isoformat() if tmpl.created_at else None,
            "updated_at": tmpl.updated_at.isoformat() if tmpl.updated_at else None,
            "created_by": tmpl.created_by,
        },
        request,
    )


# ── Update / Disable ──────────────────────────────────────────────────────


@router.put("/admin/governance-prompts/{task_type}/active")
def update_prompt_template(
    task_type: str,
    payload: dict,
    request: Request,
    session: Session = Depends(get_db),
):
    """Update a prompt template for *task_type*, creating a new active version.

    The previous active version is archived. Accepts partial overrides:
    only the fields present in *payload* will be changed.
    """
    try:
        new_tmpl = GovernancePromptService.update_template(
            session,
            task_type,
            template_data=payload,
            change_summary=payload.get("change_summary", "Console update"),
            user_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update prompt template: {exc}",
        ) from exc

    session.commit()
    return response(
        {
            "id": new_tmpl.id,
            "task_type": new_tmpl.task_type,
            "template_version": new_tmpl.template_version,
            "template_name": new_tmpl.template_name,
            "status": new_tmpl.status.value,
        },
        request,
    )


@router.post("/admin/governance-prompts/{template_id}/disable")
def disable_prompt_template(
    template_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    """Disable a governance prompt template by ID."""
    try:
        tmpl = GovernancePromptService.disable_template(
            session, template_id, user_id=None
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to disable prompt template: {exc}",
        ) from exc

    session.commit()
    return response(
        {
            "id": tmpl.id,
            "task_type": tmpl.task_type,
            "template_version": tmpl.template_version,
            "status": tmpl.status.value,
        },
        request,
    )
