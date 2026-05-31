"""AI governance services: PromptProfileService and AIGovernanceService."""
from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.input_builder import DefaultAIInputBuilder, RedactionPolicyError
from nexus_app.ai_governance.knowledge_type_inference import infer_knowledge_emissions
from nexus_app.ai_governance.litellm_client import (
    FakeLiteLLMClient,
    LiteLLMCallError,
    LiteLLMCallSummary,
    LiteLLMClientProtocol,
    LiteLLMErrorType,
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


# Retry policy for transient LiteLLM failures. After exhausting retries the
# AIGovernanceRun is marked FAILED and the version_status is set to FAILED so
# the workbench can surface a manual restart action.
_AI_CALL_MAX_RETRIES = 3
_AI_CALL_RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
_AI_CALL_RETRIABLE_ERRORS = frozenset({
    LiteLLMErrorType.TIMEOUT,
    LiteLLMErrorType.RATE_LIMIT,
    LiteLLMErrorType.SERVER_ERROR,
})


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

        try:
            built = builder.build(
                ref_dict, profile.redaction_policy, sensitivity_level,
                registry=registry, model_alias=profile.litellm_model_alias,
            )
        except RedactionPolicyError as exc:
            # Policy blocked the call before any LiteLLM request — record an
            # AIGovernanceRun with POLICY_BLOCKED status so the audit trail and
            # downstream decision service can react without an LLM round-trip.
            blocked_hash = hashlib.sha256(
                (
                    f"policy_blocked:{normalized_ref_id}:{profile_id}:"
                    f"{sensitivity_level}:{profile.redaction_policy}"
                ).encode()
            ).hexdigest()
            run = models.AIGovernanceRun(
                normalized_ref_id=normalized_ref_id,
                profile_id=profile_id,
                model_alias=profile.litellm_model_alias,
                prompt_version=profile.prompt_version,
                input_hash=blocked_hash,
                input_summary={
                    "blocked_reason": "redaction_policy",
                    "level": sensitivity_level,
                    "policy": profile.redaction_policy,
                },
                validation_status=AIGovernanceRunValidationStatus.POLICY_BLOCKED,
                adoption_status=AIGovernanceRunAdoptionStatus.REJECTED,
                validation_error=str(exc),
                created_by=user_id,
                trace_id=trace_id,
            )
            session.add(run)
            session.flush()
            _write_audit(
                session,
                AuditEventType.AI_GOVERNANCE_RUN_FAILED,
                "ai_governance_run", run.id, user_id, trace_id,
                {
                    "normalized_ref_id": normalized_ref_id,
                    "profile_id": profile_id,
                    "blocked_reason": "redaction_policy",
                    "level": sensitivity_level,
                    "policy": profile.redaction_policy,
                    "model_alias": profile.litellm_model_alias,
                    "error": str(exc)[:500],
                },
            )
            return run

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
            raw_output, call_summary, attempts = self._call_llm_with_retry(
                client,
                profile.litellm_model_alias,
                messages,
                temperature=profile.temperature,
                max_tokens=profile.max_input_tokens,
            )
            run.raw_output = raw_output
            run.call_latency_ms = call_summary.latency_ms
            run.request_id = call_summary.request_id
            if attempts > 1:
                logger.info(
                    "LiteLLM call succeeded after %d attempts (run=%s)",
                    attempts, run.id,
                )
        except LiteLLMCallError as exc:
            run.validation_status = AIGovernanceRunValidationStatus.FAILED
            run.validation_error = str(exc)
            error_type_value = exc.error_type.value if exc.error_type else "unknown"
            _write_audit(session, AuditEventType.AI_GOVERNANCE_RUN_FAILED,
                         "ai_governance_run", run.id, user_id, trace_id,
                         {
                             "error": str(exc),
                             "error_type": error_type_value,
                             "normalized_ref_id": normalized_ref_id,
                             "max_retries": _AI_CALL_MAX_RETRIES,
                             "retriable": exc.error_type in _AI_CALL_RETRIABLE_ERRORS,
                         })
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

            # knowledge_emissions is written separately via
            # AIGovernanceService.write_knowledge_emissions(); the pipeline calls
            # it explicitly after governance_decision so the write timing is
            # part of the documented stage contract (see Review §1.4).

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

    def write_knowledge_emissions(
        self,
        session: Session,
        ai_run: models.AIGovernanceRun,
        registry: GovernanceRulesRegistry,
    ) -> list[dict[str, Any]]:
        """Infer knowledge_emissions from an AI run and persist them on the
        bound NormalizedAssetRef.

        Idempotent: skips when ai_run has no validated output or when emissions
        already exist on the ref. Returns the emissions list that was either
        written or already present (empty list if nothing applies).
        Errors are caught and logged — emissions are best-effort; callers should
        not abort the pipeline if this returns an empty list.
        """
        if ai_run.ai_output is None:
            return []
        ref = session.get(models.NormalizedAssetRef, ai_run.normalized_ref_id)
        if ref is None:
            return []
        existing = (ref.metadata_summary or {}).get("knowledge_emissions")
        if existing:
            return list(existing)
        try:
            ref_dict = self._build_ref_dict(ref)
            emissions = infer_knowledge_emissions(
                ai_run.ai_output or {}, ref_dict, registry
            )
            if not emissions:
                return []
            summary = dict(ref.metadata_summary or {})
            summary["knowledge_emissions"] = emissions
            ref.metadata_summary = summary
            session.flush()
            logger.info(
                "Wrote %d knowledge_emissions for ref %s (run %s)",
                len(emissions), ref.id, ai_run.id,
            )
            return emissions
        except Exception as exc:
            logger.warning(
                "Knowledge type inference failed for run %s: %s", ai_run.id, exc
            )
            return []

    @staticmethod
    def _call_llm_with_retry(
        client: LiteLLMClientProtocol,
        model_alias: str,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, LiteLLMCallSummary, int]:
        """Call LiteLLM with exponential backoff for transient errors.

        Retries on TIMEOUT / RATE_LIMIT / SERVER_ERROR up to _AI_CALL_MAX_RETRIES.
        Non-retriable errors (INVALID_REQUEST, UNKNOWN) bubble up immediately.
        Returns (raw_output, summary, total_attempts).
        """
        import time as _time

        attempt = 0
        last_exc: LiteLLMCallError | None = None
        max_attempts = _AI_CALL_MAX_RETRIES + 1  # 1 initial + N retries
        while attempt < max_attempts:
            attempt += 1
            try:
                raw_output, summary = client.call(
                    model_alias, messages,
                    temperature=temperature, max_tokens=max_tokens,
                )
                return raw_output, summary, attempt
            except LiteLLMCallError as exc:
                last_exc = exc
                if exc.error_type not in _AI_CALL_RETRIABLE_ERRORS:
                    logger.info(
                        "LiteLLM non-retriable error (%s), aborting after attempt %d",
                        exc.error_type, attempt,
                    )
                    raise
                if attempt >= max_attempts:
                    logger.warning(
                        "LiteLLM retries exhausted (%d attempts, error_type=%s)",
                        attempt, exc.error_type,
                    )
                    raise
                backoff_idx = min(attempt - 1, len(_AI_CALL_RETRY_BACKOFF_SECONDS) - 1)
                delay = _AI_CALL_RETRY_BACKOFF_SECONDS[backoff_idx]
                logger.warning(
                    "LiteLLM call attempt %d failed (%s), retrying in %.1fs",
                    attempt, exc.error_type, delay,
                )
                _time.sleep(delay)
        # unreachable — loop either returns or raises
        assert last_exc is not None
        raise last_exc

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

    knowledge_types = governance_context.get("knowledge_types", [])
    if knowledge_types:
        lines.append(
            "### 知识类型（knowledge_type 字段为可选，若内容明显属于某种类型则从下列 code 中选择）"
        )
        for kt in knowledge_types:
            applicable = kt.get("applicable_classifications", [])
            scope = f"适用分类：{applicable}" if applicable else "通用"
            criteria_text = "；".join(kt.get("source_criteria", []))
            lines.append(
                f"- **{kt['code']}**（{kt.get('name', '')}，{scope}）：{criteria_text}"
            )
        lines.append("")

    lines.append(
        "**输出约束**：classification 必须是上述分类 code 之一；"
        "level 必须是上述分级 code 之一；"
        "tags 中每个值必须是上述标签 code 之一，不得包含未定义的标签；"
        "knowledge_type 可空；若提供，必须是上述知识类型 code 之一。"
    )
    return "\n".join(lines)

