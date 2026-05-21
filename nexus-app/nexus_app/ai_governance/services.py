"""AI governance services: PromptProfileService and AIGovernanceService."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.input_builder import DefaultAIInputBuilder
from nexus_app.ai_governance.knowledge_type_inference import infer_knowledge_emissions
from nexus_app.ai_governance.litellm_client import (
    FakeLiteLLMClient,
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.ai_governance.output_validator import AIOutputValidator, PydanticOutputValidator
from nexus_app.ai_governance.quality_scorer import QualityScoringService
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.audit import write_audit as _write_audit_raw
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    AuditEventType,
    PromptProfileStatus,
)

logger = logging.getLogger(__name__)


def _write_audit(
    session: Session,
    event_type: AuditEventType,
    entity_type: str,
    entity_id: str,
    actor_id: str | None,
    trace_id: str,
    detail: dict[str, Any],
) -> None:
    _write_audit_raw(session, event_type, target_type=entity_type,
                     target_id=entity_id, trace_id=trace_id, summary=detail,
                     actor_id=actor_id)


class AIGovernanceError(Exception):
    pass


class PromptProfileNotFoundError(AIGovernanceError):
    pass


class PromptProfileDisabledError(AIGovernanceError):
    pass


class PromptProfileService:
    """Manages ai_prompt_profile lifecycle: create, update, disable, query."""

    def create_profile(
        self,
        session: Session,
        profile_name: str,
        task_type: str,
        litellm_model_alias: str,
        prompt_version: str,
        prompt_template: str,
        *,
        output_schema_version: str = "1.0",
        scoring_weight_version: str = "1.0",
        temperature: float = 0.2,
        max_input_tokens: int = 4096,
        redaction_policy: str = "masked_content",
        user_id: str | None = None,
    ) -> models.AIPromptProfile:
        self._archive_active_version(session, profile_name)
        next_ver = self._generate_next_version(session, profile_name)
        trace_id = str(uuid.uuid4())

        profile = models.AIPromptProfile(
            profile_name=profile_name,
            profile_version=next_ver,
            task_type=task_type,
            status=PromptProfileStatus.ACTIVE,
            litellm_model_alias=litellm_model_alias,
            prompt_version=prompt_version,
            prompt_template=prompt_template,
            output_schema_version=output_schema_version,
            scoring_weight_version=scoring_weight_version,
            temperature=temperature,
            max_input_tokens=max_input_tokens,
            redaction_policy=redaction_policy,
            created_by=user_id,
            trace_id=trace_id,
        )
        session.add(profile)
        session.flush()

        _write_audit(session, AuditEventType.PROMPT_PROFILE_CREATED, "ai_prompt_profile",
                     profile.id, user_id, trace_id,
                     {"profile_name": profile_name, "version": next_ver})
        return profile

    def update_profile(
        self,
        session: Session,
        profile_name: str,
        *,
        prompt_template: str | None = None,
        litellm_model_alias: str | None = None,
        prompt_version: str | None = None,
        temperature: float | None = None,
        redaction_policy: str | None = None,
        output_schema_version: str | None = None,
        scoring_weight_version: str | None = None,
        max_input_tokens: int | None = None,
        user_id: str | None = None,
    ) -> models.AIPromptProfile:
        current = self._get_active_profile(session, profile_name)
        if current is None:
            raise PromptProfileNotFoundError(f"No active profile for '{profile_name}'")

        trace_id = str(uuid.uuid4())
        self._archive_active_version(session, profile_name)
        next_ver = self._generate_next_version(session, profile_name)

        profile = models.AIPromptProfile(
            profile_name=current.profile_name,
            profile_version=next_ver,
            task_type=current.task_type,
            status=PromptProfileStatus.ACTIVE,
            litellm_model_alias=litellm_model_alias or current.litellm_model_alias,
            prompt_version=prompt_version or current.prompt_version,
            prompt_template=prompt_template or current.prompt_template,
            output_schema_version=output_schema_version or current.output_schema_version,
            scoring_weight_version=scoring_weight_version or current.scoring_weight_version,
            temperature=temperature if temperature is not None else current.temperature,
            max_input_tokens=max_input_tokens or current.max_input_tokens,
            redaction_policy=redaction_policy or current.redaction_policy,
            created_by=user_id,
            trace_id=trace_id,
        )
        session.add(profile)
        session.flush()
        _write_audit(session, AuditEventType.PROMPT_PROFILE_UPDATED, "ai_prompt_profile",
                     profile.id, user_id, trace_id,
                     {"profile_name": profile_name, "version": next_ver})
        return profile

    def disable_profile(
        self,
        session: Session,
        profile_id: str,
        *,
        user_id: str | None = None,
    ) -> models.AIPromptProfile:
        profile = session.get(models.AIPromptProfile, profile_id)
        if profile is None:
            raise PromptProfileNotFoundError(f"Profile '{profile_id}' not found")
        profile.status = PromptProfileStatus.DISABLED
        trace_id = str(uuid.uuid4())
        _write_audit(session, AuditEventType.PROMPT_PROFILE_DISABLED, "ai_prompt_profile",
                     profile_id, user_id, trace_id,
                     {"profile_name": profile.profile_name})
        return profile

    def get_profile(self, session: Session, profile_id: str) -> models.AIPromptProfile:
        profile = session.get(models.AIPromptProfile, profile_id)
        if profile is None:
            raise PromptProfileNotFoundError(f"Profile '{profile_id}' not found")
        return profile

    def list_profiles(
        self,
        session: Session,
        *,
        profile_name: str | None = None,
        status: PromptProfileStatus | None = None,
    ) -> list[models.AIPromptProfile]:
        q = select(models.AIPromptProfile)
        if profile_name:
            q = q.where(models.AIPromptProfile.profile_name == profile_name)
        if status:
            q = q.where(models.AIPromptProfile.status == status)
        q = q.order_by(
            models.AIPromptProfile.profile_name,
            models.AIPromptProfile.profile_version.desc(),
        )
        return list(session.scalars(q).all())

    def _generate_next_version(self, session: Session, profile_name: str) -> int:
        row = session.scalars(
            select(models.AIPromptProfile.profile_version)
            .where(models.AIPromptProfile.profile_name == profile_name)
            .order_by(models.AIPromptProfile.profile_version.desc())
            .limit(1)
        ).first()
        return (row or 0) + 1

    def _archive_active_version(self, session: Session, profile_name: str) -> None:
        active = self._get_active_profile(session, profile_name)
        if active is not None:
            active.status = PromptProfileStatus.ARCHIVED

    def _get_active_profile(
        self, session: Session, profile_name: str
    ) -> models.AIPromptProfile | None:
        return session.scalars(
            select(models.AIPromptProfile)
            .where(
                models.AIPromptProfile.profile_name == profile_name,
                models.AIPromptProfile.status == PromptProfileStatus.ACTIVE,
            )
            .limit(1)
        ).first()


class AIGovernanceService:
    """Runs AI governance for a normalized_asset_ref."""

    def run_governance(
        self,
        session: Session,
        normalized_ref_id: str,
        profile_id: str,
        *,
        litellm_client: LiteLLMClientProtocol | None = None,
        input_builder: DefaultAIInputBuilder | None = None,
        output_validator: AIOutputValidator | None = None,
        registry: GovernanceRulesRegistry | None = None,
        user_id: str | None = None,
    ) -> models.AIGovernanceRun:
        client = litellm_client or FakeLiteLLMClient()
        builder = input_builder or DefaultAIInputBuilder()
        validator = output_validator or PydanticOutputValidator(registry=registry)
        trace_id = str(uuid.uuid4())

        ref = session.get(models.NormalizedAssetRef, normalized_ref_id)
        if ref is None:
            raise AIGovernanceError(f"NormalizedAssetRef '{normalized_ref_id}' not found")

        profile = session.get(models.AIPromptProfile, profile_id)
        if profile is None:
            raise AIGovernanceError(f"AIPromptProfile '{profile_id}' not found")
        if profile.status == PromptProfileStatus.DISABLED:
            raise AIGovernanceError(f"AIPromptProfile '{profile_id}' is disabled")

        sensitivity_level = (ref.governance or {}).get("level", "L1")
        ref_dict = self._build_ref_dict(ref)

        built = builder.build(ref_dict, profile.redaction_policy, sensitivity_level,
                              registry=registry)

        run = models.AIGovernanceRun(
            normalized_ref_id=normalized_ref_id,
            profile_id=profile_id,
            model_alias=profile.litellm_model_alias,
            prompt_version=profile.prompt_version,
            input_hash=built["input_hash"],
            input_summary=built["input_summary"],
            validation_status=AIGovernanceRunValidationStatus.FAILED,
            adoption_status=AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED,
            created_by=user_id,
            trace_id=trace_id,
        )
        session.add(run)
        session.flush()

        try:
            messages = self._build_messages(profile.prompt_template, built["payload"])
            raw_output, call_summary = client.call(
                profile.litellm_model_alias,
                messages,
                temperature=profile.temperature,
                max_tokens=profile.max_input_tokens,
            )
            run.raw_output = raw_output
            run.call_latency_ms = call_summary.latency_ms
            run.request_id = call_summary.request_id
        except LiteLLMCallError as exc:
            run.validation_status = AIGovernanceRunValidationStatus.FAILED
            run.validation_error = str(exc)
            _write_audit(session, AuditEventType.AI_GOVERNANCE_RUN_FAILED,
                         "ai_governance_run", run.id, user_id, trace_id,
                         {"error": str(exc), "normalized_ref_id": normalized_ref_id})
            return run

        ai_output_obj, error = validator.validate(run.raw_output or "")
        if ai_output_obj is None:
            run.validation_status = AIGovernanceRunValidationStatus.SCHEMA_INVALID
            run.validation_error = error
            return run

        run.ai_output = ai_output_obj.model_dump()
        run.validation_status = AIGovernanceRunValidationStatus.SCHEMA_VALID
        run.adoption_status = AIGovernanceRunAdoptionStatus.PENDING_RULE_GUARDRAIL

        if registry is not None:
            try:
                scorer = QualityScoringService(registry)
                quality_summary = scorer.generate_quality_summary(ai_output_obj, ref_dict)
                run.quality_summary = quality_summary.model_dump()
            except Exception as exc:
                logger.warning("Quality scoring failed for run %s: %s", run.id, exc)

            # Infer knowledge_emissions and write to normalized_asset_ref
            try:
                knowledge_emissions = infer_knowledge_emissions(
                    run.ai_output or {}, ref_dict, registry
                )
                if knowledge_emissions:
                    # Update normalized_asset_ref.metadata_summary.knowledge_emissions
                    if ref.metadata_summary is None:
                        ref.metadata_summary = {}
                    ref.metadata_summary["knowledge_emissions"] = knowledge_emissions
                    session.flush()
                    logger.info(
                        f"Inferred {len(knowledge_emissions)} knowledge_emissions for ref {normalized_ref_id}"
                    )
            except Exception as exc:
                logger.warning("Knowledge type inference failed for run %s: %s", run.id, exc)

        _write_audit(session, AuditEventType.AI_GOVERNANCE_RUN_CREATED,
                     "ai_governance_run", run.id, user_id, trace_id,
                     {"normalized_ref_id": normalized_ref_id, "profile_id": profile_id,
                      "validation_status": run.validation_status.value})
        return run

    def get_governance_run(
        self, session: Session, run_id: str
    ) -> models.AIGovernanceRun:
        run = session.get(models.AIGovernanceRun, run_id)
        if run is None:
            raise AIGovernanceError(f"AIGovernanceRun '{run_id}' not found")
        return run

    def list_governance_runs(
        self,
        session: Session,
        *,
        normalized_ref_id: str | None = None,
        profile_id: str | None = None,
        validation_status: AIGovernanceRunValidationStatus | None = None,
    ) -> list[models.AIGovernanceRun]:
        q = select(models.AIGovernanceRun).order_by(
            models.AIGovernanceRun.created_at.desc()
        )
        if normalized_ref_id:
            q = q.where(models.AIGovernanceRun.normalized_ref_id == normalized_ref_id)
        if profile_id:
            q = q.where(models.AIGovernanceRun.profile_id == profile_id)
        if validation_status:
            q = q.where(models.AIGovernanceRun.validation_status == validation_status)
        return list(session.scalars(q).all())

    def get_quality_summary(
        self, session: Session, run_id: str
    ) -> dict[str, Any] | None:
        run = self.get_governance_run(session, run_id)
        return run.quality_summary

    @staticmethod
    def _build_ref_dict(ref: models.NormalizedAssetRef) -> dict[str, Any]:
        return {
            "title": ref.title,
            "summary": (ref.metadata_summary or {}).get("summary", ""),
            "schema_version": ref.schema_version,
            "content_snippet": (ref.metadata_summary or {}).get("content_snippet", ""),
            "source_type_hint": ref.source_type,
            "sensitivity_summary": (ref.governance or {}).get("sensitivity_summary", ""),
            "org_context": (ref.governance or {}).get("org_scope", ""),
            "content_type": ref.content_type,
            "language": ref.language,
            "normalized_type": ref.normalized_type.value if ref.normalized_type else None,
        }

    @staticmethod
    def _build_messages(
        prompt_template: str, payload: dict[str, Any]
    ) -> list[dict[str, str]]:
        """Build chat messages for LiteLLM call.

        governance_context is extracted from payload and rendered as structured
        instructions so the AI is explicitly guided to use registry-defined
        criteria when selecting classification, level, and tags.
        """
        import json as _json

        governance_context = payload.get("governance_context", {})
        content_payload = {k: v for k, v in payload.items() if k != "governance_context"}

        rules_section = _build_rules_section(governance_context)
        system_content = f"{prompt_template}\n\n{rules_section}" if rules_section else prompt_template

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": _json.dumps(content_payload, ensure_ascii=False,
                                                     default=str)},
        ]


def _build_rules_section(governance_context: dict[str, Any]) -> str:
    """Render governance_context criteria as structured prompt instructions."""
    if not governance_context:
        return ""

    lines: list[str] = ["## 治理规则定义（必须严格遵守）\n"]

    classifications = governance_context.get("classifications", [])
    if classifications:
        lines.append("### 数据域分类（classification 字段必须从以下 code 中选择）")
        for c in classifications:
            criteria_text = "；".join(c.get("criteria", []))
            lines.append(f"- **{c['code']}**（{c.get('name', '')}）：{criteria_text}")
        lines.append("")

    levels = governance_context.get("levels", [])
    if levels:
        lines.append("### 数据分级（level 字段必须从以下 code 中选择）")
        for lv in levels:
            criteria_text = "；".join(lv.get("criteria", []))
            lines.append(f"- **{lv['code']}**（{lv.get('name', '')}）：{criteria_text}")
        lines.append("")

    tags = governance_context.get("tags", [])
    if tags:
        lines.append("### 数据标签（tags 字段只能包含以下 code，不得自造标签）")
        for t in tags:
            applicable = t.get("applicable_classifications", [])
            scope = f"适用分类：{applicable}" if applicable else "通用"
            criteria_text = "；".join(t.get("criteria", []))
            lines.append(f"- **{t['code']}**（{t.get('name', '')}，{scope}）：{criteria_text}")
        lines.append("")

    lines.append(
        "**输出约束**：classification 必须是上述分类 code 之一；"
        "level 必须是上述分级 code 之一；"
        "tags 中每个值必须是上述标签 code 之一，不得包含未定义的标签。"
    )
    return "\n".join(lines)

