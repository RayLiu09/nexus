"""Focused Prompt Profile API contracts without the broken ASGI test bridge."""
from __future__ import annotations

from sqlalchemy import func, select

from nexus_api.api.internal.ai_prompts import (
    create_prompt_profile,
    list_prompt_profile_history,
    list_prompt_profiles,
    validate_prompt_candidate,
)
from nexus_api.api.internal.governance_prompts import update_prompt_template
from nexus_api.dependencies import Pagination
from nexus_app import models, schemas
from nexus_app.ai_governance.services import (
    LEGACY_PROMPT_MAX_INPUT_TOKENS,
    LEGACY_PROMPT_MODEL_ALIAS,
)
from nexus_app.enums import AuditEventType, PromptProfileStatus


def _payload(
    profile_name: str,
    *,
    task_type: str = "classification",
    scenario: str = "metadata_governance",
    prompt_version: str = "v1",
    prompt_template: str = "Rules: {{RULES}}\nDocument: {{DOCUMENT}}",
) -> dict:
    return {
        "profile_name": profile_name,
        "task_type": task_type,
        "scenario": scenario,
        "prompt_version": prompt_version,
        "prompt_template": prompt_template,
        "output_schema": {"type": "object"},
        "change_summary": "contract test",
    }


def _create(session, user, request, payload: dict):
    return create_prompt_profile(
        schemas.PromptProfileCreate.model_validate(payload),
        request,
        session,
        user,
    )


def test_create_hides_legacy_fields_and_writes_actor_trace_audit(
    session, stub_user, fake_request
):
    payload = _payload("governance.classification")
    # Old clients may still send these keys. Pydantic ignores them because
    # they are no longer part of the public request contract.
    payload.update({"litellm_model_alias": "ignored/model", "max_input_tokens": 999})
    fake_request.state.trace_id = "trace-prompt-create"

    result = _create(session, stub_user, fake_request, payload)
    body = result.data.model_dump(mode="json")
    assert "litellm_model_alias" not in body
    assert "max_input_tokens" not in body

    profile = session.get(models.AIPromptProfile, body["id"])
    assert profile is not None
    assert profile.litellm_model_alias == LEGACY_PROMPT_MODEL_ALIAS
    assert profile.max_input_tokens == LEGACY_PROMPT_MAX_INPUT_TOKENS
    assert profile.created_by == stub_user.id
    assert profile.trace_id == "trace-prompt-create"

    audit = session.scalar(
        select(models.AuditLog).where(
            models.AuditLog.target_type == "ai_prompt_profile",
            models.AuditLog.target_id == profile.id,
            models.AuditLog.event_type == AuditEventType.PROMPT_PROFILE_CREATED,
        )
    )
    assert audit is not None
    assert audit.actor_id == stub_user.id
    assert audit.trace_id == "trace-prompt-create"


def test_openapi_does_not_expose_legacy_prompt_fields(app):
    components = app.openapi()["components"]["schemas"]
    for schema_name in ("PromptProfileCreate", "PromptProfileUpdate", "PromptProfileRead"):
        properties = components[schema_name]["properties"]
        assert "litellm_model_alias" not in properties
        assert "max_input_tokens" not in properties


def test_filters_and_history_return_expected_profile_versions(
    session, stub_user, fake_request
):
    profile_name = "contract.versioned"
    first = _payload(
        profile_name,
        task_type="tagging",
        scenario="prompt_lab",
        prompt_template="Document: {{DOCUMENT}}",
    )
    second = {**first, "prompt_version": "v2", "prompt_template": "Updated {{DOCUMENT}}"}
    _create(session, stub_user, fake_request, first)
    _create(session, stub_user, fake_request, second)

    active = list_prompt_profiles(
        fake_request,
        profile_name=profile_name,
        task_type="tagging",
        scenario="prompt_lab",
        status=PromptProfileStatus.ACTIVE,
        pagination=Pagination(page=1, page_size=20),
        session=session,
    )
    history = list_prompt_profile_history(
        profile_name,
        fake_request,
        Pagination(page=1, page_size=20),
        session,
    )

    assert [row.profile_version for row in active.data] == [2]
    assert [row.profile_version for row in history.data] == [2, 1]
    assert [row.status for row in history.data] == [
        PromptProfileStatus.ACTIVE,
        PromptProfileStatus.ARCHIVED,
    ]


def test_candidate_validation_uses_unified_governance_model(fake_request):
    valid = validate_prompt_candidate(
        schemas.PromptProfileCreate.model_validate(
            _payload("governance.classification")
        ),
        fake_request,
    )
    invalid = validate_prompt_candidate(
        schemas.PromptProfileCreate.model_validate(
            _payload(
                "governance.classification",
                prompt_template="missing required placeholders",
            )
        ),
        fake_request,
    )

    assert valid.data.valid is True
    assert valid.data.model_alias
    assert valid.data.model_source == "DEFAULT_GOVERNANCE_MODEL"
    assert invalid.data.valid is False
    assert len(invalid.data.errors) == 2


def test_compatibility_route_versions_profile_without_writing_legacy_table(
    session, stub_user, fake_request
):
    _create(
        session,
        stub_user,
        fake_request,
        _payload("governance.classification"),
    )
    fake_request.state.trace_id = "trace-prompt-compat"
    updated = update_prompt_template(
        "classification",
        {
            "prompt_version": "v2",
            "prompt_template": "New rules: {{RULES}}\nNew document: {{DOCUMENT}}",
            "change_summary": "compatibility update",
        },
        fake_request,
        session,
        stub_user,
    )

    assert updated.data["template_name"] == "governance.classification"
    assert updated.data["template_version"] == 2
    assert session.scalar(
        select(func.count()).select_from(models.AIPromptProfile).where(
            models.AIPromptProfile.profile_name == "governance.classification"
        )
    ) == 2
    assert session.scalar(
        select(func.count()).select_from(models.GovernancePromptTemplate)
    ) == 0
    active = session.scalar(
        select(models.AIPromptProfile).where(
            models.AIPromptProfile.profile_name == "governance.classification",
            models.AIPromptProfile.status == PromptProfileStatus.ACTIVE,
        )
    )
    assert active is not None
    assert active.trace_id == "trace-prompt-compat"
