"""Compatibility routes backed exclusively by ``ai_prompt_profile``.

The historical ``governance_prompt_template`` table remains readable at the
database level for audit/history, but these endpoints never read or mutate it.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from nexus_api.api.internal._helpers import prompt_svc
from nexus_api.dependencies import require_user
from nexus_api.responses import response
from nexus_app import models
from nexus_app.ai_governance.prompt_registry import GOVERNANCE_PROMPT_PROFILE_NAMES
from nexus_app.ai_governance.services import PromptProfileNotFoundError
from nexus_app.database import get_db
from nexus_app.enums import PromptProfileStatus

router = APIRouter()


def _serialize(profile: models.AIPromptProfile, *, include_template: bool = False) -> dict:
    payload = {
        "id": profile.id,
        "task_type": profile.task_type,
        "template_name": profile.profile_name,
        "template_version": profile.profile_version,
        "status": profile.status.value,
        "output_schema": profile.output_schema,
        "output_schema_version": profile.output_schema_version,
        "temperature": profile.temperature,
        "redaction_policy": profile.redaction_policy,
        "content_hash": profile.content_hash,
        "change_summary": profile.change_summary,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        "created_by": profile.created_by,
    }
    if include_template:
        payload["prompt_template"] = profile.prompt_template
    return payload


@router.get("/admin/governance-prompts")
def list_prompt_templates(request: Request, session: Session = Depends(get_db)):
    profiles = prompt_svc.list_profiles(session, scenario="metadata_governance")
    return response([_serialize(profile) for profile in profiles], request)


@router.get("/admin/governance-prompts/{profile_id}")
def get_prompt_template(
    profile_id: str, request: Request, session: Session = Depends(get_db)
):
    try:
        profile = prompt_svc.get_profile(session, profile_id)
    except PromptProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if profile.profile_name not in GOVERNANCE_PROMPT_PROFILE_NAMES.values():
        raise HTTPException(status_code=404, detail="Governance Prompt Profile not found")
    return response(_serialize(profile, include_template=True), request)


@router.put("/admin/governance-prompts/{task_type}/active")
def update_prompt_template(
    task_type: str,
    payload: dict,
    request: Request,
    session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_user),
):
    normalized_task = {
        "quality_assessment": "quality_scoring",
        "knowledge_inference": "knowledge_type_inference",
    }.get(task_type, task_type)
    profile_name = GOVERNANCE_PROMPT_PROFILE_NAMES.get(normalized_task)
    if profile_name is None:
        raise HTTPException(status_code=422, detail=f"Unknown governance task_type '{task_type}'")
    allowed = {
        "prompt_template",
        "prompt_version",
        "output_schema",
        "output_schema_version",
        "temperature",
        "redaction_policy",
        "change_summary",
    }
    overrides = {key: value for key, value in payload.items() if key in allowed}
    try:
        profile = prompt_svc.update_profile(
            session,
            profile_name,
            **overrides,
            user_id=user.id,
            trace_id=request.state.trace_id,
        )
    except PromptProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return response(_serialize(profile, include_template=True), request)


@router.post("/admin/governance-prompts/{profile_id}/disable")
def disable_prompt_template(
    profile_id: str,
    request: Request,
    session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_user),
):
    try:
        profile = prompt_svc.get_profile(session, profile_id)
        if profile.profile_name not in GOVERNANCE_PROMPT_PROFILE_NAMES.values():
            raise PromptProfileNotFoundError("Governance Prompt Profile not found")
        if profile.status == PromptProfileStatus.DISABLED:
            return response(_serialize(profile), request)
        profile = prompt_svc.disable_profile(
            session,
            profile_id,
            user_id=user.id,
            trace_id=request.state.trace_id,
        )
    except PromptProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return response(_serialize(profile), request)
