"""AI governance services: PromptProfileService and AIGovernanceService."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    LiteLLMConfig,
    create_litellm_client,
)
from nexus_app.ai_governance.output_validator import AIOutputValidator, PydanticOutputValidator
from nexus_app.ai_governance.quality_scorer import QualityScoringService
from nexus_app.ai_governance.prompt_registry import GovernancePromptRegistry
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.audit import write_audit as _write_audit_raw
from nexus_app.config import Settings, get_settings
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

_TAG_DIMENSION_KEYS = frozenset({
    "professional_domain",
    "education_level",
    "geographic_scope",
    "timeliness",
    "data_source_type",
})
_TAG_STAGE_INPUT_EXCLUDED_FIELDS = frozenset({
    "source_type_hint",
})
_NON_BUSINESS_TAG_VALUES = frozenset({
    "file_upload",
    "文件上传",
    "本地文件上传",
    "nas",
    "crawler",
    "爬虫",
    "database",
    "数据库",
    "webhook",
    "api推送",
    "API推送",
    "第三方API推送",
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
        scenario: str = "default",
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
            scenario=scenario,
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
                     {"profile_name": profile_name, "version": next_ver, "scenario": scenario})
        return profile

    def update_profile(
        self,
        session: Session,
        profile_name: str,
        *,
        prompt_template: str | None = None,
        litellm_model_alias: str | None = None,
        scenario: str | None = None,
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
            scenario=scenario or current.scenario,
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
                     {"profile_name": profile_name, "version": next_ver, "scenario": profile.scenario})
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

    def dry_run(
        self,
        session: Session,
        profile_id: str,
        normalized_ref_id: str,
        *,
        input_overrides: dict[str, Any] | None = None,
        litellm_client: LiteLLMClientProtocol | None = None,
        input_builder: DefaultAIInputBuilder | None = None,
        output_validator: AIOutputValidator | None = None,
        registry: GovernanceRulesRegistry | None = None,
    ) -> dict[str, Any]:
        """Preview prompt execution without persisting a governance run.

        The dry-run follows the same redaction, whitelist, LiteLLM call, schema
        validation, and quality-scoring path as official governance. It never
        inserts `ai_governance_run`, `governance_result`, or state transitions.
        """
        client = litellm_client
        builder = input_builder or DefaultAIInputBuilder()
        validator = output_validator or PydanticOutputValidator(registry=registry)

        ref = session.get(models.NormalizedAssetRef, normalized_ref_id)
        if ref is None:
            raise AIGovernanceError(f"NormalizedAssetRef '{normalized_ref_id}' not found")
        profile = self.get_profile(session, profile_id)
        if profile.status == PromptProfileStatus.DISABLED:
            raise PromptProfileDisabledError(f"Profile '{profile_id}' is disabled")

        sensitivity_level = (ref.governance or {}).get("level", "L1")
        ref_dict = AIGovernanceService._build_ref_dict(ref)
        if input_overrides:
            ref_dict.update(input_overrides)

        try:
            built = builder.build(
                ref_dict,
                profile.redaction_policy,
                sensitivity_level,
                registry=registry,
                model_alias=_governance_model_alias(profile.litellm_model_alias),
            )
        except RedactionPolicyError as exc:
            return _dry_run_payload(
                profile,
                normalized_ref_id,
                input_hash=f"policy_blocked:{normalized_ref_id}:{profile_id}",
                input_summary={"blocked_reason": "redaction_policy"},
                validation_status=AIGovernanceRunValidationStatus.POLICY_BLOCKED,
                adoption_status=AIGovernanceRunAdoptionStatus.REJECTED,
                validation_error=str(exc),
            )

        try:
            messages = AIGovernanceService._build_messages(profile.prompt_template, built["payload"])
            client = client or _create_default_litellm_client()
            raw_output, call_summary, _ = AIGovernanceService._call_llm_with_retry(
                client,
                _governance_model_alias(profile.litellm_model_alias),
                messages,
                temperature=profile.temperature,
                max_tokens=profile.max_input_tokens,
            )
        except LiteLLMCallError as exc:
            return _dry_run_payload(
                profile,
                normalized_ref_id,
                input_hash=built["input_hash"],
                input_summary=built["input_summary"],
                validation_status=AIGovernanceRunValidationStatus.FAILED,
                adoption_status=AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED,
                validation_error=str(exc),
            )

        ai_output_obj, error = validator.validate(raw_output)
        if ai_output_obj is None:
            return _dry_run_payload(
                profile,
                normalized_ref_id,
                input_hash=built["input_hash"],
                input_summary=built["input_summary"],
                validation_status=AIGovernanceRunValidationStatus.SCHEMA_INVALID,
                adoption_status=AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED,
                validation_error=error,
                call_latency_ms=call_summary.latency_ms,
                request_id=call_summary.request_id,
            )

        quality_summary: dict[str, Any] | None = None
        if registry is not None:
            try:
                scorer = QualityScoringService(registry)
                quality_summary = scorer.generate_quality_summary(ai_output_obj, ref_dict).model_dump()
            except Exception as exc:
                logger.warning("Dry-run quality scoring failed: %s", exc)

        return _dry_run_payload(
            profile,
            normalized_ref_id,
            input_hash=built["input_hash"],
            input_summary=built["input_summary"],
            validation_status=AIGovernanceRunValidationStatus.SCHEMA_VALID,
            adoption_status=AIGovernanceRunAdoptionStatus.PENDING_RULE_GUARDRAIL,
            ai_output=ai_output_obj.model_dump(),
            quality_summary=quality_summary,
            call_latency_ms=call_summary.latency_ms,
            request_id=call_summary.request_id,
        )

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


def _dry_run_payload(
    profile: models.AIPromptProfile,
    normalized_ref_id: str,
    *,
    input_hash: str,
    input_summary: dict[str, Any],
    validation_status: AIGovernanceRunValidationStatus,
    adoption_status: AIGovernanceRunAdoptionStatus,
    ai_output: dict[str, Any] | None = None,
    quality_summary: dict[str, Any] | None = None,
    validation_error: str | None = None,
    call_latency_ms: float | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "profile_id": profile.id,
        "profile_name": profile.profile_name,
        "profile_version": profile.profile_version,
        "scenario": profile.scenario,
        "normalized_ref_id": normalized_ref_id,
        "model_alias": profile.litellm_model_alias,
        "prompt_version": profile.prompt_version,
        "input_hash": input_hash,
        "input_summary": input_summary,
        "validation_status": validation_status,
        "adoption_status": adoption_status,
        "ai_output": ai_output,
        "quality_summary": quality_summary,
        "validation_error": validation_error,
        "call_latency_ms": call_latency_ms,
        "request_id": request_id,
        "persisted": False,
    }


def _create_default_litellm_client(settings: Settings | None = None) -> LiteLLMClientProtocol:
    current = settings or get_settings()
    if not current.litellm_endpoint:
        raise AIGovernanceError(
            "LiteLLM endpoint is not configured; set LITELLM_ENDPOINT in .env.dev"
        )
    if not current.litellm_api_key:
        raise AIGovernanceError(
            "LiteLLM API key is not configured; set LITELLM_API_KEY in .env.dev"
        )
    return create_litellm_client(
        LiteLLMConfig(
            base_url=current.litellm_endpoint.rstrip("/"),
            api_key_ref="LITELLM_API_KEY",
            timeout=current.litellm_timeout,
        ),
        current.litellm_api_key,
    )


def _governance_model_alias(configured_alias: str, settings: Settings | None = None) -> str:
    current = settings or get_settings()
    return current.default_governance_model or configured_alias


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
        client = litellm_client
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
                registry=registry, model_alias=_governance_model_alias(profile.litellm_model_alias),
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
                model_alias=_governance_model_alias(profile.litellm_model_alias),
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
                    "model_alias": _governance_model_alias(profile.litellm_model_alias),
                    "error": str(exc)[:500],
                },
            )
            return run

        run = models.AIGovernanceRun(
            normalized_ref_id=normalized_ref_id,
            profile_id=profile_id,
            model_alias=_governance_model_alias(profile.litellm_model_alias),
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
            client = client or _create_default_litellm_client()
            raw_output, call_summary, attempts = self._call_llm_with_retry(
                client,
                _governance_model_alias(profile.litellm_model_alias),
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

    def run_governance_multi(
        self,
        session: Session,
        normalized_ref_id: str,
        *,
        prompt_registry: "GovernancePromptRegistry",
        rules_registry: "GovernanceRulesRegistry | None" = None,
        litellm_client: LiteLLMClientProtocol | None = None,
        user_id: str | None = None,
    ) -> models.AIGovernanceRun:
        """Multi-stage governance: 5 independent LLM calls + quality scoring.

        Stages:
          1. classification       → LLM (determine category)
          2. level_assessment     → LLM (sensitivity level L1-L4)
          3. tagging              → LLM (5-dimension tags)
          4. quality_scoring      → Rule engine (QualityScoringService)
          5. knowledge_type       → LLM (infer knowledge types)

        All stage outputs are aggregated into a single ``AIGovernanceRun``
        record with per-stage details in ``ai_output._stages``.
        """
        client = litellm_client or _create_default_litellm_client()
        trace_id = str(uuid.uuid4())

        ref = session.get(models.NormalizedAssetRef, normalized_ref_id)
        if ref is None:
            raise AIGovernanceError(
                f"NormalizedAssetRef '{normalized_ref_id}' not found"
            )
        ref_dict = self._build_ref_dict(ref)
        sensitivity_level = (ref.governance or {}).get("level", "L1")

        # Snapshot: record which prompt-templates were used
        prompt_ids: dict[str, str] = {}
        for task_type in ("classification", "level_assessment", "tagging",
                          "knowledge_type_inference"):
            try:
                tmpl = prompt_registry.get_prompt(task_type)
                prompt_ids[task_type] = tmpl.id
            except Exception:
                pass

        # Create the run record (profile_id is nullable for multi-stage)
        classification_tmpl = prompt_registry.get_prompt("classification")
        run = models.AIGovernanceRun(
            normalized_ref_id=normalized_ref_id,
            profile_id=None,
            model_alias=_governance_model_alias(classification_tmpl.litellm_model_alias),
            prompt_version=f"multi-stage/{classification_tmpl.template_version}",
            input_hash="",
            input_summary={"mode": "multi_stage", "task_types": sorted(prompt_ids)},
            validation_status=AIGovernanceRunValidationStatus.FAILED,
            adoption_status=AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED,
            prompt_snapshot=prompt_ids,
            created_by=user_id,
            trace_id=trace_id,
        )
        session.add(run)
        session.flush()

        stage_outputs: dict[str, Any] = self._run_llm_stages_parallel(
            client,
            prompt_registry,
            ("classification", "level_assessment", "tagging", "knowledge_type_inference"),
            ref_dict,
            sensitivity_level,
            rules_registry,
        )
        total_latency_ms = sum(
            float(output.get("_latency_ms", 0.0))
            for output in stage_outputs.values()
            if isinstance(output, dict)
        )

        cls_output = stage_outputs.get("classification")
        lvl_output = stage_outputs.get("level_assessment")
        tag_output = stage_outputs.get("tagging")

        if not isinstance(cls_output, dict):
            cls_output = {}
        if not isinstance(lvl_output, dict):
            lvl_output = {}
        if not isinstance(tag_output, dict):
            tag_output = {}

        # ---- Stage 4: Quality Scoring (rule engine, not LLM) ----
        quality_summary: dict[str, Any] | None = None
        if rules_registry is not None and cls_output and "_error" not in cls_output:
            try:
                scorer = QualityScoringService(rules_registry)
                scoring_input = self._build_quality_input(
                    cls_output, lvl_output, tag_output
                )
                qs = scorer.generate_quality_summary(scoring_input, ref_dict)
                quality_summary = qs.model_dump()
                stage_outputs["quality_scoring"] = quality_summary
            except Exception as exc:
                logger.warning("Quality scoring failed: %s", exc)
                stage_outputs["quality_scoring"] = {"error": str(exc)}
        elif rules_registry is not None:
            stage_outputs["quality_scoring"] = {
                "error": "classification stage unavailable; quality scoring skipped"
            }

        # ---- Aggregate ----
        ai_output = self._aggregate_stage_outputs(stage_outputs)
        any_failed = any(
            s.get("_error") for s in stage_outputs.values()
            if isinstance(s, dict)
        )

        run.ai_output = ai_output
        run.raw_output = json.dumps(stage_outputs, ensure_ascii=False, default=str)
        run.call_latency_ms = total_latency_ms
        run.input_hash = self._compute_multi_input_hash(ref_dict, prompt_ids)
        run.validation_status = (
            AIGovernanceRunValidationStatus.SCHEMA_VALID
            if not any_failed
            else AIGovernanceRunValidationStatus.FAILED
        )
        run.adoption_status = AIGovernanceRunAdoptionStatus.PENDING_RULE_GUARDRAIL

        if quality_summary is not None:
            run.quality_summary = quality_summary

        _write_audit(
            session, AuditEventType.AI_GOVERNANCE_RUN_CREATED,
            "ai_governance_run", run.id, user_id, trace_id,
            {
                "normalized_ref_id": normalized_ref_id,
                "mode": "multi_stage",
                "task_types": sorted(prompt_ids),
                "validation_status": run.validation_status.value,
                "total_latency_ms": total_latency_ms,
            },
        )
        return run

    # ------------------------------------------------------------------
    # Multi-stage helpers
    # ------------------------------------------------------------------

    def _run_llm_stages_parallel(
        self,
        client: LiteLLMClientProtocol,
        prompt_registry: "GovernancePromptRegistry",
        task_types: tuple[str, ...],
        ref_dict: dict[str, Any],
        sensitivity_level: str,
        rules_registry: "GovernanceRulesRegistry | None",
    ) -> dict[str, Any]:
        """Run independent LLM governance stages concurrently.

        The worker session is not touched inside these threads. Each task only
        builds prompt input and calls LiteLLM, then the main thread persists the
        combined AIGovernanceRun.
        """
        outputs: dict[str, Any] = {}
        max_workers = max(1, len(task_types))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._run_llm_stage,
                    client,
                    prompt_registry,
                    task_type,
                    dict(ref_dict),
                    sensitivity_level,
                    rules_registry,
                ): task_type
                for task_type in task_types
            }
            for future in as_completed(futures):
                task_type = futures[future]
                try:
                    output = future.result()
                except Exception as exc:  # defensive: stage failures must be visible, not fatal
                    logger.warning("LLM stage %s raised unexpectedly: %s", task_type, exc)
                    output = {"_error": f"stage_exception: {type(exc).__name__}: {exc}", "_task_type": task_type}
                if output is not None:
                    outputs[task_type] = output
        return outputs

    def _run_llm_stage(
        self,
        client: LiteLLMClientProtocol,
        prompt_registry: "GovernancePromptRegistry",
        task_type: str,
        ref_dict: dict[str, Any],
        sensitivity_level: str,
        rules_registry: "GovernanceRulesRegistry | None",
    ) -> dict[str, Any] | None:
        """Execute one LLM governance stage. Returns output dict or None on failure."""
        try:
            tmpl = prompt_registry.get_prompt(task_type)
        except Exception as exc:
            logger.warning("No prompt for task_type=%s: %s", task_type, exc)
            return {"_error": f"no_prompt: {exc}", "_task_type": task_type}

        builder = DefaultAIInputBuilder()
        try:
            stage_ref_dict = dict(ref_dict)
            if task_type == "tagging":
                for field in _TAG_STAGE_INPUT_EXCLUDED_FIELDS:
                    stage_ref_dict.pop(field, None)
            built = builder.build(
                stage_ref_dict, tmpl.redaction_policy, sensitivity_level,
                registry=rules_registry, model_alias=tmpl.litellm_model_alias,
            )
        except RedactionPolicyError as exc:
            logger.warning("Redaction blocked for %s: %s", task_type, exc)
            return {"_error": f"redaction_blocked: {exc}", "_task_type": task_type}

        # Build stage-specific rules section
        rules_text = self._build_stage_rules(task_type, rules_registry)

        # Render the prompt template
        document_json = json.dumps(built["payload"], ensure_ascii=False, default=str)
        rendered = tmpl.prompt_template.replace("{{RULES}}", rules_text).replace(
            "{{DOCUMENT}}", document_json
        )

        messages = [
            {"role": "system", "content": rendered},
        ]

        try:
            raw_output, call_summary, attempts = self._call_llm_with_retry(
                client,
                _governance_model_alias(tmpl.litellm_model_alias),
                messages,
                temperature=tmpl.temperature,
                max_tokens=tmpl.max_input_tokens,
            )
        except LiteLLMCallError as exc:
            logger.warning("LLM call failed for %s: %s", task_type, exc)
            return {
                "_error": f"llm_call_failed: {exc}",
                "_task_type": task_type,
                "_error_type": exc.error_type.value if exc.error_type else "unknown",
            }

        # Parse JSON from LLM output
        parsed = self._parse_llm_json(raw_output)
        if parsed is None:
            return {
                "_error": "json_parse_failed",
                "_task_type": task_type,
                "_raw": raw_output[:500],
            }  # type: ignore[dict-item]

        parsed["_latency_ms"] = call_summary.latency_ms
        parsed["_attempts"] = attempts
        parsed["_task_type"] = task_type
        parsed["_model_alias"] = _governance_model_alias(tmpl.litellm_model_alias)
        return parsed

    # ------------------------------------------------------------------
    # Stage-specific rules rendering
    # ------------------------------------------------------------------

    @staticmethod
    def _build_stage_rules(
        task_type: str,
        rules_registry: "GovernanceRulesRegistry | None",
    ) -> str:
        """Build the {{RULES}} replacement text for a given stage."""
        if rules_registry is None:
            return ""

        if task_type == "classification":
            return _render_classification_rules(rules_registry)
        elif task_type == "level_assessment":
            return _render_level_rules(rules_registry)
        elif task_type == "tagging":
            return _render_tagging_rules(rules_registry)
        elif task_type == "quality_scoring":
            return _render_quality_rules(rules_registry)
        elif task_type == "knowledge_type_inference":
            return _render_knowledge_type_rules(rules_registry)
        return ""

    @staticmethod
    def _parse_llm_json(raw: str) -> dict[str, Any] | None:
        """Extract a JSON object from LLM output (may be wrapped in markdown)."""
        text = raw.strip()
        # Try direct parse first
        try:
            val = json.loads(text)
            if isinstance(val, dict):
                return val
        except (json.JSONDecodeError, ValueError):
            pass
        # Try extracting from ```json ... ``` block
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            try:
                val = json.loads(m.group(1).strip())
                if isinstance(val, dict):
                    return val
            except (json.JSONDecodeError, ValueError):
                pass
        # Try finding the first { ... } block
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                val = json.loads(m.group(0))
                if isinstance(val, dict):
                    return val
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    @staticmethod
    def _first_str(source: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _extract_tags(tag_output: dict[str, Any]) -> list[str]:
        tags: list[str] = []
        seen: set[str] = set()

        def is_valid_tag_value(value: str) -> bool:
            if value.startswith("#") or value.startswith("_"):
                return False
            if value in _NON_BUSINESS_TAG_VALUES:
                return False
            if re.search(r"(?:gpt|doubao|qwen|deepseek|claude|gemini)[-_a-z0-9.]*", value, re.I):
                return False
            return True

        def add(value: Any) -> None:
            if isinstance(value, dict):
                value = value.get("value") or value.get("code") or value.get("tag")
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned and is_valid_tag_value(cleaned) and cleaned not in seen:
                    seen.add(cleaned)
                    tags.append(cleaned)

        def add_many(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    add_many(item)
            elif isinstance(value, dict):
                if any(key in value for key in ("value", "code", "tag")):
                    add(value)
                else:
                    for nested in value.values():
                        add_many(nested)
            else:
                add(value)

        explicit = tag_output.get("tags")
        add_many(explicit)
        for dim_k in _TAG_DIMENSION_KEYS:
            if dim_k in tag_output:
                add_many(tag_output[dim_k])
        return tags

    @staticmethod
    def _extract_tag_dimensions(tag_output: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
        raw = tag_output.get("tags")
        if not isinstance(raw, dict):
            return {}

        dimensions: dict[str, list[dict[str, str]]] = {}
        for dim_key, dim_value in raw.items():
            if not isinstance(dim_key, str):
                continue
            values = dim_value if isinstance(dim_value, list) else [dim_value]
            items: list[dict[str, str]] = []
            for value in values:
                if isinstance(value, dict):
                    label = value.get("value") or value.get("code") or value.get("tag")
                    criteria = value.get("criteria") or value.get("evidence") or value.get("rationale") or ""
                else:
                    label = value
                    criteria = ""
                if isinstance(label, str) and label.strip():
                    cleaned = label.strip()
                    if (
                        cleaned in _NON_BUSINESS_TAG_VALUES
                        or cleaned.startswith("#")
                        or re.search(r"(?:gpt|doubao|qwen|deepseek|claude|gemini)[-_a-z0-9.]*", cleaned, re.I)
                    ):
                        continue
                    items.append({"value": cleaned, "criteria": str(criteria) if criteria else ""})
            if items:
                dimensions[dim_key] = items
        return dimensions

    @staticmethod
    def _aggregate_stage_outputs(stage_outputs: dict[str, Any]) -> dict[str, Any]:
        """Merge per-stage outputs into a single ai_output dict.

        Top-level fields maintain backward compatibility with
        decision_service.py expectations; full stage details stored in _stages.
        """
        cls = stage_outputs.get("classification", {})
        lvl = stage_outputs.get("level_assessment", {})
        tag = stage_outputs.get("tagging", {})
        qual = stage_outputs.get("quality_scoring", {})
        kt = stage_outputs.get("knowledge_type_inference", {})

        if not isinstance(cls, dict):
            cls = {}
        if not isinstance(lvl, dict):
            lvl = {}
        if not isinstance(tag, dict):
            tag = {}
        if not isinstance(qual, dict):
            qual = {}
        if not isinstance(kt, dict):
            kt = {}

        # Overall confidence: average across non-error stages
        confidences = []
        for s in (cls, lvl, tag, kt):
            if isinstance(s, dict) and "_error" not in s:
                c = s.get("confidence")
                if isinstance(c, (int, float)):
                    confidences.append(float(c))
        avg_confidence = (
            sum(confidences) / len(confidences) if confidences else 0.0
        )

        quality_scores = cls.get("quality_scores")
        if not isinstance(quality_scores, dict):
            quality_scores = tag.get("quality_scores")
        if not isinstance(quality_scores, dict):
            quality_scores = {}

        overall_score = cls.get("overall_score")
        if not isinstance(overall_score, (int, float)):
            overall_score = qual.get("quality_score")

        tags = AIGovernanceService._extract_tags(tag)
        tag_dimensions = AIGovernanceService._extract_tag_dimensions(tag)

        return {
            "classification": AIGovernanceService._first_str(
                cls, "classification_code", "code", "classification"
            ),
            "classification_name": AIGovernanceService._first_str(
                cls, "classification_name", "name", "classification_name"
            ),
            "level": AIGovernanceService._first_str(
                lvl, "level_code", "code", "level"
            ) or AIGovernanceService._first_str(cls, "level"),
            "level_name": AIGovernanceService._first_str(
                lvl, "level_name", "name", "level_name"
            ),
            "tags": tags,
            "tag_dimensions": tag_dimensions,
            "org_scope": (
                cls.get("org_scope")
                or lvl.get("org_scope")
                or tag.get("org_scope")
                or "all"
            ),
            "quality_scores": quality_scores,
            "overall_score": float(overall_score) if isinstance(overall_score, (int, float)) else 0.0,
            "evidence_refs": cls.get("evidence_refs") or lvl.get("evidence_refs") or [],
            "confidence": avg_confidence,
            **({"quality_summary": qual} if qual and "error" not in qual else {}),
            "_stages": stage_outputs,
            "_mode": "multi_stage",
        }

    @staticmethod
    def _build_quality_input(
        cls_output: dict[str, Any],
        lvl_output: dict[str, Any],
        tag_output: dict[str, Any],
    ) -> Any:
        """Build an AIGovernanceOutput-compatible object for QualityScoringService."""
        from nexus_app.ai_governance.output_validator import AIGovernanceOutput

        aggregate = AIGovernanceService._aggregate_stage_outputs({
            "classification": cls_output,
            "level_assessment": lvl_output,
            "tagging": tag_output,
        })
        return AIGovernanceOutput.model_validate({
            "classification": aggregate.get("classification") or "unknown",
            "level": aggregate.get("level") or "L1",
            "tags": aggregate.get("tags") or [],
            "org_scope": aggregate.get("org_scope") or "all",
            "quality_scores": aggregate.get("quality_scores") or {},
            "overall_score": aggregate.get("overall_score") or 0.0,
            "evidence_refs": aggregate.get("evidence_refs") or [],
            "confidence": aggregate.get("confidence") or 0.0,
            "reasoning": cls_output.get("reasoning") or "",
        })

    @staticmethod
    def _compute_multi_input_hash(
        ref_dict: dict[str, Any],
        prompt_ids: dict[str, str],
    ) -> str:
        serialized = json.dumps(
            {"ref_keys": sorted(ref_dict.keys()), "prompt_ids": prompt_ids},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(serialized.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Query helpers (unchanged)
    # ------------------------------------------------------------------

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

        Idempotent for retries: keeps existing emissions when they already
        match the current AI output + active rules, but replaces stale
        emissions when re-governance changes the classification/rule mapping.
        Returns the emissions list that was either written or already present
        (empty list if nothing applies).
        Errors are caught and logged — emissions are best-effort; callers should
        not abort the pipeline if this returns an empty list.
        """
        if ai_run.ai_output is None:
            return []
        ref = session.get(models.NormalizedAssetRef, ai_run.normalized_ref_id)
        if ref is None:
            return []
        try:
            ref_dict = self._build_ref_dict(ref)
            emissions = infer_knowledge_emissions(
                ai_run.ai_output or {}, ref_dict, registry
            )
            if not emissions:
                return []
            existing = (ref.metadata_summary or {}).get("knowledge_emissions")
            if existing and _knowledge_emissions_match(existing, emissions):
                return list(existing)
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
        configured_attempts = max(1, get_settings().litellm_retry_attempts)
        max_attempts = configured_attempts + 1  # 1 initial + N retries
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
        metadata_summary = ref.metadata_summary or {}
        summary = metadata_summary.get("summary", "")
        content_snippet = metadata_summary.get("content_snippet", "")
        # Compatibility for historical refs created before normalize started
        # writing summary/content_snippet into metadata_summary: fetch the
        # normalized payload from object storage and derive a snippet from
        # body_markdown / record_body. Failures are swallowed so governance
        # still proceeds with the original (possibly empty) values.
        if not content_snippet:
            fetched = AIGovernanceService._fetch_snippet_fallback(ref)
            if fetched:
                content_snippet = fetched
        if not summary and content_snippet:
            summary = content_snippet[:600]
        return {
            "title": ref.title,
            "summary": summary,
            "schema_version": ref.schema_version,
            "content_snippet": content_snippet,
            "source_type_hint": ref.source_type,
            "domain_profile": metadata_summary.get("domain_profile"),
            "domain_quality": (
                metadata_summary.get("major_profile_quality")
                if metadata_summary.get("domain_profile") == "major_profile.v1"
                else None
            ),
            "sensitivity_summary": (ref.governance or {}).get("sensitivity_summary", ""),
            "org_context": (ref.governance or {}).get("org_scope", ""),
            "content_type": ref.content_type,
            "language": ref.language,
            "normalized_type": ref.normalized_type.value if ref.normalized_type else None,
        }

    @staticmethod
    def _fetch_snippet_fallback(ref: models.NormalizedAssetRef) -> str:
        """Pull body text from the normalized payload object when snippet is missing.

        Used only as a compatibility path for historical refs. Errors are logged
        and swallowed; the caller proceeds with an empty snippet (and governance
        records "Missing content" as before).
        """
        object_uri = ref.object_uri
        if not object_uri or object_uri == "pending":
            return ""
        try:
            from nexus_app.storage import get_object_storage

            storage = get_object_storage()
            key = object_uri.split("/", 3)[-1] if object_uri.startswith("s3://") else object_uri
            raw_bytes = storage.get_bytes(key)
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 defensive: never let fallback break governance
            logger.warning(
                "Normalized payload fetch failed for ref %s (%s); proceeding without snippet",
                ref.id, exc,
            )
            return ""

        body = payload.get("body_markdown")
        if isinstance(body, str) and body.strip():
            collapsed = re.sub(r"\s+", " ", body).strip()
            return collapsed[:2000]
        record_body = payload.get("record_body")
        if record_body:
            try:
                text = json.dumps(record_body, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                text = str(record_body)
            return re.sub(r"\s+", " ", text).strip()[:2000]
        return ""

    @staticmethod
    def _build_messages(
        prompt_template: str, payload: dict[str, Any]
    ) -> list[dict[str, str]]:
        """Build chat messages for LiteLLM call.

        governance_context is extracted from payload and rendered as structured
        instructions so the AI is explicitly guided to use registry-defined
        criteria when selecting classification, level, and tags.
        """
        governance_context = payload.get("governance_context", {})
        content_payload = {k: v for k, v in payload.items() if k != "governance_context"}

        rules_section = _build_rules_section(governance_context)
        system_content = f"{prompt_template}\n\n{rules_section}" if rules_section else prompt_template

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": json.dumps(content_payload, ensure_ascii=False,
                                                     default=str)},
        ]


def _knowledge_emissions_match(
    existing: Any,
    expected: list[dict[str, Any]],
) -> bool:
    """Compare the identity-bearing emission fields used by chunk routing.

    Confidence/evidence can legitimately drift between governance runs without
    requiring chunk routing changes. The routing contract is the ordered
    primary/code pair sequence.
    """
    if not isinstance(existing, list):
        return False
    existing_key = [
        (item.get("code"), bool(item.get("primary")))
        for item in existing
        if isinstance(item, dict)
    ]
    expected_key = [
        (item.get("code"), bool(item.get("primary")))
        for item in expected
    ]
    return existing_key == expected_key


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
        lines.append("### 数据标签定义（用于判断标签维度和候选值语义，标签值允许按内容生成）")
        for t in tags:
            applicable = t.get("applicable_classifications", [])
            scope = f"适用分类：{applicable}" if applicable else "通用"
            criteria_text = "；".join(t.get("criteria", []))
            name = t.get("name") or t.get("code", "")
            lines.append(f"- **{name}**（{scope}）：{criteria_text}")
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
        "tags 是内容标签值列表或固定维度标签对象，标签值不是有限 code 集，不要自造分类/分级 code；"
        "knowledge_type 可空；若提供，必须是上述知识类型 code 之一。"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stage-specific rules rendering (used by AIGovernanceService._build_stage_rules)
# ---------------------------------------------------------------------------


def _render_classification_rules(registry: GovernanceRulesRegistry) -> str:
    """Render classifications as {{RULES}} for the classification stage."""
    lines: list[str] = ["## 数据域分类\n"]
    lines.append("你必须从以下分类代码中选择一个最匹配的：\n")
    for c in registry.get_classifications():
        criteria_text = "；".join(c.criteria or [])
        desc = c.description or ""
        lines.append(
            f"- **{c.code}**（{c.name}）"
            + (f"：{desc}" if desc else "")
            + (f" 关键词：{criteria_text}" if criteria_text else "")
        )
    lines.append("")
    lines.append(
        "**约束**：classification_code 必须是上述 code 之一。"
        "如果文档匹配多个分类，选择匹配度最高的一个。"
    )
    return "\n".join(lines)


def _render_level_rules(registry: GovernanceRulesRegistry) -> str:
    """Render sensitivity levels as {{RULES}} for the level_assessment stage."""
    lines: list[str] = ["## 数据安全分级\n"]
    lines.append("你必须从以下分级代码中选择一个：\n")
    for lv in registry.get_levels():
        criteria_text = "；".join(lv.criteria or [])
        desc = lv.description or ""
        lines.append(
            f"- **{lv.code}**（{lv.name}）"
            + (f"：{desc}" if desc else "")
            + (f" 标准：{criteria_text}" if criteria_text else "")
        )
    lines.append("")
    lines.append(
        "**约束**：level_code 必须是上述 code 之一（L1/L2/L3/L4）。"
        "默认新导入数据判定为 L1 或 L2，除非有明确证据支持更高等级。"
        "涉及个人身份信息（姓名、身份证号、手机号、薪资等）至少判定为 L3。"
    )
    return "\n".join(lines)


def _render_tagging_rules(registry: GovernanceRulesRegistry) -> str:
    """Render 5-dimension tag definitions as {{RULES}} for the tagging stage."""
    content = registry.get_rules_content()
    tag_dims = content.get("tag_dimensions", {}) or {}

    lines: list[str] = ["## 标签维度\n"]
    lines.append("文档标签包含以下 5 个维度，每维度从允许值中选择：\n")

    dim_labels = {
        "professional_domain": "专业领域",
        "education_level": "学历层次",
        "geographic_scope": "地域范围",
        "timeliness": "时效性",
        "data_source_type": "数据来源",
    }

    for dim_key, dim_label in dim_labels.items():
        dim_values = tag_dims.get(dim_key, [])
        lines.append(f"### {dim_label}（{dim_key}）")
        if dim_values:
            for item in dim_values:
                if isinstance(item, dict):
                    val = item.get("value", item.get("code", ""))
                    criteria = item.get("criteria", item.get("description", ""))
                    lines.append(f"- **{val}**" + (f"：{criteria}" if criteria else ""))
                elif isinstance(item, str):
                    lines.append(f"- **{item}**")
        lines.append("")

    lines.append(
        "**约束**：每个维度从上述允许值中选择。"
        "professional_domain 可选 1-3 个标签，其余维度各选 1 个。"
        "返回格式：每个维度是一个数组，每项包含 value 和 criteria 字段。"
    )
    return "\n".join(lines)


def _render_quality_rules(registry: GovernanceRulesRegistry) -> str:
    """Render quality scoring config as {{RULES}} for the quality stage."""
    qs = registry.get_quality_scoring()
    lines: list[str] = ["## 质量评分维度\n"]

    for dim in qs.dimensions:
        items = [f"- **{item.name}**" for item in dim.check_items]
        lines.append(f"### {dim.name}（权重 {dim.weight}）")
        if dim.description:
            lines.append(f"{dim.description}")
        lines.extend(items)
        lines.append("")

    lines.append("### 阈值")
    lines.append(f"- 通过（pass）：{qs.thresholds.pass_}")
    lines.append(f"- 警告（warning）：{qs.thresholds.warning}")
    if qs.thresholds.review_required_below > 0:
        lines.append(f"- 需审核低于（review_required_below）：{qs.thresholds.review_required_below}")
    lines.append(f"- 自动采纳置信度阈值：{qs.confidence_threshold_auto_adopt}")
    return "\n".join(lines)


def _render_knowledge_type_rules(registry: GovernanceRulesRegistry) -> str:
    """Render knowledge_types as {{RULES}} for the knowledge_type stage."""
    kts = registry.get_knowledge_types()
    lines: list[str] = ["## 知识类型\n"]
    lines.append("你必须从以下知识类型代码中选择适用的类型：\n")

    for kt in kts:
        code = kt.get("code", "")
        name = kt.get("name", "")
        desc = kt.get("description", "")
        criteria = "；".join(kt.get("source_criteria", []))
        applicable = kt.get("applicable_classifications", [])
        scope = f"适用分类：{applicable}" if applicable else "通用"
        lines.append(
            f"- **{code}**（{name}，{scope}）"
            + (f"：{desc}" if desc else "")
            + (f" 判断依据：{criteria}" if criteria else "")
        )

    lines.append("")
    lines.append(
        "**约束**：knowledge_types 数组中每个对象的 code 必须是上述 code 之一。"
        "primary_type 是置信度最高的知识类型。可以为空数组。"
    )
    return "\n".join(lines)
