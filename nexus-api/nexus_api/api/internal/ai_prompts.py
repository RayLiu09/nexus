"""AI Prompt Profile CRUD + dry-run (`/internal/v1/ai/prompt-profiles/*`).

Mutating endpoints require `Idempotency-Key`. Profile versioning rule (one
active per profile_name, save → new version auto-activates) lives in
`PromptProfileService`."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.api.internal._helpers import get_rules_registry, prompt_svc
from nexus_api.dependencies import (
    Pagination,
    pagination_params,
    require_idempotency_key,
    require_user,
)
from nexus_api.responses import list_response, response
from nexus_app import models, schemas as domain_schemas
from nexus_app.ai_governance.services import (
    AIGovernanceError,
    PromptProfileNotFoundError,
)
from nexus_app.database import get_db
from nexus_app.enums import PromptProfileStatus

router = APIRouter()


@router.post(
    "/ai/prompt-profiles/validate",
    response_model=schemas.ApiResponse[domain_schemas.PromptProfileValidationRead],
)
def validate_prompt_candidate(
    payload: domain_schemas.PromptProfileCreate,
    request: Request,
):
    result = prompt_svc.validate_candidate(payload.model_dump())
    return response(
        domain_schemas.PromptProfileValidationRead.model_validate(result), request
    )


@router.post(
    "/ai/prompt-profiles/dry-run",
    response_model=schemas.ApiResponse[domain_schemas.PromptCandidateDryRunRead],
)
def dry_run_prompt_candidate(
    payload: domain_schemas.PromptCandidateDryRunCreate,
    request: Request,
    session: Session = Depends(get_db),
):
    try:
        result = prompt_svc.dry_run_candidate(
            session,
            payload.candidate.model_dump(),
            payload.normalized_ref_id,
            registry=get_rules_registry(),
        )
    except AIGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return response(
        domain_schemas.PromptCandidateDryRunRead.model_validate(result), request
    )


@router.post(
    "/ai/prompt-profiles",
    response_model=schemas.ApiResponse[domain_schemas.PromptProfileRead],
    status_code=201,
    dependencies=[Depends(require_idempotency_key)],
)
def create_prompt_profile(
    payload: domain_schemas.PromptProfileCreate,
    request: Request,
    session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_user),
):
    try:
        profile = prompt_svc.create_profile(
            session,
            profile_name=payload.profile_name,
            task_type=payload.task_type,
            litellm_model_alias=None,
            prompt_version=payload.prompt_version,
            prompt_template=payload.prompt_template,
            scenario=payload.scenario,
            output_schema=payload.output_schema,
            output_schema_version=payload.output_schema_version,
            scoring_weight_version=payload.scoring_weight_version,
            temperature=payload.temperature,
            redaction_policy=payload.redaction_policy,
            change_summary=payload.change_summary,
            user_id=user.id,
            trace_id=request.state.trace_id,
        )
    except AIGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return response(domain_schemas.PromptProfileRead.model_validate(profile), request)


@router.get(
    "/ai/prompt-profiles",
    response_model=schemas.ListResponse[domain_schemas.PromptProfileRead],
)
def list_prompt_profiles(
    request: Request,
    profile_name: str | None = None,
    task_type: str | None = None,
    scenario: str | None = None,
    status: PromptProfileStatus | None = None,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    # Prompt profiles are bounded in practice (≤ tens per task_type), so a
    # full-list-then-slice is acceptable — keeps the service-layer signature
    # free of pagination plumbing.
    profiles = prompt_svc.list_profiles(
        session,
        profile_name=profile_name,
        task_type=task_type,
        scenario=scenario,
        status=status,
    )
    total = len(profiles)
    page_slice = profiles[pagination.offset : pagination.offset + pagination.limit]
    return list_response(
        [domain_schemas.PromptProfileRead.model_validate(p) for p in page_slice],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/ai/prompt-profiles/{profile_name}/history",
    response_model=schemas.ListResponse[domain_schemas.PromptProfileRead],
)
def list_prompt_profile_history(
    profile_name: str,
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    profiles = prompt_svc.list_profiles(session, profile_name=profile_name)
    total = len(profiles)
    page_slice = profiles[pagination.offset : pagination.offset + pagination.limit]
    return list_response(
        [domain_schemas.PromptProfileRead.model_validate(p) for p in page_slice],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/ai/prompt-profiles/{profile_id}",
    response_model=schemas.ApiResponse[domain_schemas.PromptProfileRead],
)
def get_prompt_profile(
    profile_id: str, request: Request, session: Session = Depends(get_db)
):
    try:
        profile = prompt_svc.get_profile(session, profile_id)
    except PromptProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(domain_schemas.PromptProfileRead.model_validate(profile), request)


@router.put(
    "/ai/prompt-profiles/{profile_name}/active",
    response_model=schemas.ApiResponse[domain_schemas.PromptProfileRead],
)
def update_prompt_profile(
    profile_name: str,
    payload: domain_schemas.PromptProfileUpdate,
    request: Request,
    session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_user),
):
    try:
        profile = prompt_svc.update_profile(
            session,
            profile_name,
            **payload.model_dump(exclude_none=True),
            user_id=user.id,
            trace_id=request.state.trace_id,
        )
    except PromptProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AIGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return response(domain_schemas.PromptProfileRead.model_validate(profile), request)


@router.post(
    "/ai/prompt-profiles/{profile_id}/disable",
    response_model=schemas.ApiResponse[domain_schemas.PromptProfileRead],
)
def disable_prompt_profile(
    profile_id: str,
    request: Request,
    session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_user),
):
    try:
        profile = prompt_svc.disable_profile(
            session,
            profile_id,
            user_id=user.id,
            trace_id=request.state.trace_id,
        )
    except PromptProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return response(domain_schemas.PromptProfileRead.model_validate(profile), request)


@router.post(
    "/ai/prompt-profiles/{profile_id}/dry-run",
    response_model=schemas.ApiResponse[domain_schemas.PromptDryRunRead],
)
def dry_run_prompt_profile(
    profile_id: str,
    payload: domain_schemas.PromptDryRunCreate,
    request: Request,
    session: Session = Depends(get_db),
):
    registry = get_rules_registry()
    try:
        result = prompt_svc.dry_run(
            session,
            profile_id,
            payload.normalized_ref_id,
            input_overrides=payload.input_overrides,
            registry=registry,
        )
    except PromptProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AIGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return response(domain_schemas.PromptDryRunRead.model_validate(result), request)
