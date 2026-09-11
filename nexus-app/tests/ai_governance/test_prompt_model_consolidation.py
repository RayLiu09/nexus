from __future__ import annotations

import json

from sqlalchemy import func, select

from nexus_app import models
from nexus_app.ai_governance.litellm_client import FakeLiteLLMClient
from nexus_app.ai_governance.model_alias import resolve_model_alias
from nexus_app.ai_governance.output_validator import validate_governance_stage_output
from nexus_app.ai_governance.prompt_registry import (
    GOVERNANCE_PROMPT_PROFILE_NAMES,
    GovernancePromptRegistry,
)
from nexus_app.ai_governance.services import (
    LEGACY_PROMPT_MAX_INPUT_TOKENS,
    LEGACY_PROMPT_MODEL_ALIAS,
    PromptProfileService,
)
from nexus_app.config import Settings
from nexus_app.enums import GovernancePromptTemplateStatus, NormalizedType


def _create_governance_profiles(session) -> dict[str, models.AIPromptProfile]:
    service = PromptProfileService()
    canonical_tasks = {
        "quality_scoring": "quality_assessment",
        "knowledge_type_inference": "knowledge_inference",
    }
    result = {}
    for stage, profile_name in GOVERNANCE_PROMPT_PROFILE_NAMES.items():
        result[stage] = service.create_profile(
            session,
            profile_name=profile_name,
            task_type=canonical_tasks.get(stage, stage),
            litellm_model_alias="must-be-ignored",
            prompt_version="1.0",
            prompt_template="rules={{RULES}} document={{DOCUMENT}}",
            scenario="metadata_governance",
            output_schema={"type": "object"},
            max_input_tokens=999999,
        )
    session.flush()
    return result


def test_profile_legacy_model_and_token_values_are_compatibility_only(session):
    profile = PromptProfileService().create_profile(
        session,
        profile_name="test.deprecated-fields",
        task_type="test",
        litellm_model_alias="legacy-override",
        prompt_version="1",
        prompt_template="{{DOCUMENT}}",
        max_input_tokens=123,
    )

    assert profile.litellm_model_alias == LEGACY_PROMPT_MODEL_ALIAS
    assert profile.max_input_tokens == LEGACY_PROMPT_MAX_INPUT_TOKENS
    assert resolve_model_alias(
        profile, Settings(DEFAULT_GOVERNANCE_MODEL="unified-governance")
    ) == "unified-governance"
    assert len(profile.content_hash) == 64


def test_governance_registry_reads_only_fixed_ai_prompt_profiles(session):
    profiles = _create_governance_profiles(session)
    session.add(
        models.GovernancePromptTemplate(
            task_type="classification",
            template_name="legacy-template-must-not-win",
            template_version=999,
            status=GovernancePromptTemplateStatus.ACTIVE,
            prompt_template="legacy",
            output_schema_version="1.0",
            litellm_model_alias="legacy-model",
            temperature=0.1,
            max_input_tokens=999,
            redaction_policy="masked_content",
        )
    )
    session.flush()

    registry = GovernancePromptRegistry()
    registry.load(session)

    assert registry.get_prompt("classification").id == profiles["classification"].id
    assert registry.get_prompt("quality_assessment").id == profiles["quality_scoring"].id
    assert registry.get_prompt("knowledge_inference").id == profiles["knowledge_type_inference"].id
    assert len(registry.get_prompts_content_hash()) == 64


def test_candidate_validation_enforces_fixed_governance_contract():
    service = PromptProfileService()
    valid = service.validate_candidate({
        "profile_name": "governance.classification",
        "task_type": "classification",
        "scenario": "metadata_governance",
        "prompt_template": "{{RULES}}\n{{DOCUMENT}}",
        "output_schema": {"type": "object"},
        "temperature": 0.1,
        "redaction_policy": "masked_content",
    })
    invalid = service.validate_candidate({
        "profile_name": "governance.classification",
        "task_type": "classification",
        "scenario": "metadata_governance",
        "prompt_template": "missing placeholders",
        "output_schema": {"type": "array"},
        "temperature": 0.1,
        "redaction_policy": "masked_content",
    })

    assert valid["valid"] is True
    assert valid["model_source"] == "DEFAULT_GOVERNANCE_MODEL"
    assert invalid["valid"] is False
    assert len(invalid["errors"]) == 3


def test_stage_validation_rejects_unknown_classification():
    class _Registry:
        def get_classifications(self):
            return [type("Classification", (), {"code": "active-code"})()]

    output, error = validate_governance_stage_output(
        "classification",
        {"classification_code": "not-active", "confidence": 0.9},
        registry=_Registry(),
    )

    assert output is None
    assert error is not None
    assert "not in registry-defined classifications" in error


def test_candidate_dry_run_uses_validation_chain_without_persistence(session):
    ref = models.NormalizedAssetRef(
        version_id="dry-run-version",
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="normalized/dry-run.json",
        schema_version="1.0",
        checksum="dry-run-checksum",
        source_type="file_upload",
        content_type="document",
        title="Dry Run",
        language="zh-CN",
        governance={"level": "L2"},
        quality={},
        lineage={},
        metadata_summary={"content_snippet": "standardized content"},
    )
    session.add(ref)
    session.flush()
    before = session.scalar(select(func.count()).select_from(models.AIGovernanceRun))

    result = PromptProfileService().dry_run_candidate(
        session,
        {
            "profile_name": "governance.classification",
            "task_type": "classification",
            "scenario": "metadata_governance",
            "prompt_version": "v1",
            "prompt_template": "{{RULES}}\n{{DOCUMENT}}",
            "output_schema": {"type": "object"},
            "redaction_policy": "masked_content",
        },
        ref.id,
        litellm_client=FakeLiteLLMClient(
            response_override=json.dumps(
                {"classification_code": "course_textbook", "confidence": 0.91}
            )
        ),
    )

    after = session.scalar(select(func.count()).select_from(models.AIGovernanceRun))
    assert result["validation"]["valid"] is True
    assert result["persisted"] is False
    assert result["output"]["classification_code"] == "course_textbook"
    assert result["output"]["_model_alias"] == result["model_alias"]
    assert after == before
