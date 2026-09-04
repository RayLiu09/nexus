"""Whole-standard one-call course derivation with all-or-nothing adoption."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType, PromptProfileStatus
from nexus_app.teaching_standard_library.derivation_rules import (
    DERIVATION_VERSION,
    NO_SPECIFIC_TOOL,
    HourRuleValidationError,
    derive_course_fields,
)
from nexus_app.teaching_standard_library.derivation_schema import (
    DERIVATION_SCHEMA_VERSION,
    TeachingStandardDerivationOutput,
)

logger = logging.getLogger(__name__)

PROFILE_NAME = "professional.teaching_standard.course_derivation"
TASK_TYPE = "teaching_standard_course_derivation"
SCENARIO = "teaching_standard_course_derivation"


@dataclass(frozen=True)
class DerivationResult:
    run_id: str
    status: str
    input_hash: str
    output_hash: str | None = None
    prompt_profile_id: str | None = None
    course_count: int = 0
    failure_code: str | None = None
    reused: bool = False


def derive_library(
    session: Session,
    library: models.TeachingStandardLibrary,
    *,
    llm_client: LiteLLMClientProtocol | None,
    default_governance_model: str,
    trace_id: str | None = None,
) -> DerivationResult:
    """Derive all courses with one model call and atomically adopt the result."""
    profile = _load_active_profile(session)
    effective_alias = _effective_model_alias(profile, default_governance_model)
    source_payload, input_error = _build_source_payload(library)
    input_hash = _input_hash(source_payload, profile, effective_alias)

    if library.status != "review":
        return _failed_without_call(
            session,
            library,
            profile,
            input_hash,
            "library_not_review",
            effective_alias,
            trace_id,
        )
    if profile is None:
        return _failed_without_call(
            session,
            library,
            None,
            input_hash,
            "prompt_profile_missing",
            effective_alias,
            trace_id,
        )
    if profile.output_schema_version != DERIVATION_SCHEMA_VERSION:
        return _failed_without_call(
            session,
            library,
            profile,
            input_hash,
            "prompt_output_schema_mismatch",
            effective_alias,
            trace_id,
        )
    if input_error is not None:
        return _failed_without_call(
            session,
            library,
            profile,
            input_hash,
            input_error,
            effective_alias,
            trace_id,
        )
    if not effective_alias:
        return _failed_without_call(
            session,
            library,
            profile,
            input_hash,
            "governance_model_missing",
            effective_alias,
            trace_id,
        )

    try:
        request_payload = _apply_redaction_policy(
            session,
            source_payload,
            policy=profile.redaction_policy,
            sensitivity_level=(library.normalized_ref.governance or {}).get(
                "level", "L1"
            ),
            effective_alias=effective_alias,
        )
    except ValueError:
        return _failed_without_call(
            session,
            library,
            profile,
            input_hash,
            "redaction_policy_blocked",
            effective_alias,
            trace_id,
        )

    input_hash = _input_hash(request_payload, profile, effective_alias)
    completed = session.scalars(
        select(models.TeachingStandardDerivationRun)
        .where(
            models.TeachingStandardDerivationRun.library_id == library.id,
            models.TeachingStandardDerivationRun.input_hash == input_hash,
            models.TeachingStandardDerivationRun.status == "completed",
        )
        .order_by(models.TeachingStandardDerivationRun.completed_at.desc())
    ).first()
    if completed is not None:
        return DerivationResult(
            run_id=completed.id,
            status="completed",
            input_hash=input_hash,
            output_hash=completed.output_hash,
            prompt_profile_id=completed.prompt_profile_id,
            course_count=len(library.courses),
            reused=True,
        )

    run = models.TeachingStandardDerivationRun(
        library_id=library.id,
        prompt_profile_id=profile.id,
        derivation_version=DERIVATION_VERSION,
        input_hash=input_hash,
        status="pending",
    )
    session.add(run)
    session.flush()
    run_id = run.id
    session.commit()

    if llm_client is None:
        return _fail_run(
            session,
            run_id,
            library.id,
            "llm_client_unavailable",
            effective_alias,
            len(source_payload["courses"]),
            trace_id,
        )

    messages = [
        {"role": "system", "content": profile.prompt_template},
        {"role": "user", "content": json.dumps(request_payload, ensure_ascii=False)},
    ]
    try:
        raw_output, _summary = llm_client.call(
            effective_alias,
            messages,
            temperature=float(profile.temperature),
            max_tokens=int(profile.max_input_tokens),
            response_format={"type": "json_object"},
        )
    except LiteLLMCallError as exc:
        logger.warning(
            "teaching-standard derivation LiteLLM call failed: %s", exc.error_type
        )
        return _fail_run(
            session,
            run_id,
            library.id,
            "llm_call_failed",
            effective_alias,
            len(source_payload["courses"]),
            trace_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "teaching-standard derivation call failed: %s", type(exc).__name__
        )
        return _fail_run(
            session,
            run_id,
            library.id,
            "llm_call_failed",
            effective_alias,
            len(source_payload["courses"]),
            trace_id,
        )

    try:
        output = TeachingStandardDerivationOutput.model_validate(json.loads(raw_output))
    except (json.JSONDecodeError, TypeError, ValidationError):
        return _fail_run(
            session,
            run_id,
            library.id,
            "batch_derivation_schema_invalid",
            effective_alias,
            len(source_payload["courses"]),
            trace_id,
        )

    courses_by_id = {course.course_id: course for course in library.courses}
    output_ids = [course.course_id for course in output.courses]
    if Counter(output_ids) != Counter(courses_by_id.keys()):
        return _fail_run(
            session,
            run_id,
            library.id,
            "batch_course_id_mismatch",
            effective_alias,
            len(source_payload["courses"]),
            trace_id,
        )
    if not _evidence_is_valid(library, courses_by_id, output):
        return _fail_run(
            session,
            run_id,
            library.id,
            "batch_derivation_evidence_invalid",
            effective_alias,
            len(source_payload["courses"]),
            trace_id,
        )

    try:
        derived_by_id = {
            item.course_id: derive_course_fields(
                library, courses_by_id[item.course_id], item
            )
            for item in output.courses
        }
    except (HourRuleValidationError, KeyError):
        return _fail_run(
            session,
            run_id,
            library.id,
            "hour_rule_validation_failed",
            effective_alias,
            len(source_payload["courses"]),
            trace_id,
        )

    current_library = session.get(models.TeachingStandardLibrary, library.id)
    if current_library is None:
        return _fail_run(
            session,
            run_id,
            library.id,
            "derivation_input_changed",
            effective_alias,
            len(source_payload["courses"]),
            trace_id,
        )
    current_source_payload, current_error = _build_source_payload(current_library)
    try:
        current_request = (
            _apply_redaction_policy(
                session,
                current_source_payload,
                policy=profile.redaction_policy,
                sensitivity_level=(current_library.normalized_ref.governance or {}).get(
                    "level", "L1"
                ),
                effective_alias=effective_alias,
            )
            if current_error is None
            else {}
        )
    except ValueError:
        return _fail_run(
            session,
            run_id,
            library.id,
            "derivation_input_changed",
            effective_alias,
            len(source_payload["courses"]),
            trace_id,
        )
    if (
        current_error is not None
        or _input_hash(current_request, profile, effective_alias) != input_hash
    ):
        return _fail_run(
            session,
            run_id,
            library.id,
            "derivation_input_changed",
            effective_alias,
            len(source_payload["courses"]),
            trace_id,
        )

    output_hash = _canonical_hash(output.model_dump(mode="json"))
    try:
        current_courses = {
            course.course_id: course for course in current_library.courses
        }
        for course_id, fields in derived_by_id.items():
            for field, value in fields.items():
                setattr(current_courses[course_id], field, value)
        current_library.training_goal_summary = output.training_goal_summary
        current_run = session.get(models.TeachingStandardDerivationRun, run_id)
        if current_run is None:
            raise RuntimeError("derivation run vanished before adoption")
        current_run.status = "completed"
        current_run.output_hash = output_hash
        current_run.failure_code = None
        current_run.completed_at = models.utcnow()
        write_audit(
            session,
            AuditEventType.TEACHING_STANDARD_COURSE_DERIVATION_COMPLETED,
            "teaching_standard_derivation_run",
            current_run.id,
            trace_id,
            _audit_summary(
                current_run,
                effective_alias,
                len(current_courses),
                reused=False,
            ),
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception("teaching-standard derivation adoption failed")
        return _fail_run(
            session,
            run_id,
            library.id,
            "derivation_persist_failed",
            effective_alias,
            len(source_payload["courses"]),
            trace_id,
        )

    return DerivationResult(
        run_id=run_id,
        status="completed",
        input_hash=input_hash,
        output_hash=output_hash,
        prompt_profile_id=profile.id,
        course_count=len(courses_by_id),
    )


def _load_active_profile(session: Session) -> models.AIPromptProfile | None:
    return session.scalars(
        select(models.AIPromptProfile)
        .where(
            models.AIPromptProfile.profile_name == PROFILE_NAME,
            models.AIPromptProfile.task_type == TASK_TYPE,
            models.AIPromptProfile.scenario == SCENARIO,
            models.AIPromptProfile.status == PromptProfileStatus.ACTIVE,
        )
        .order_by(models.AIPromptProfile.profile_version.desc())
    ).first()


def _effective_model_alias(
    profile: models.AIPromptProfile | None, default_governance_model: str
) -> str:
    profile_alias = (
        (profile.litellm_model_alias or "").strip() if profile is not None else ""
    )
    return profile_alias or default_governance_model.strip()


def _build_source_payload(
    library: models.TeachingStandardLibrary,
) -> tuple[dict[str, Any], str | None]:
    training_goal = (library.source_evidence or {}).get("training_goal_source")
    if not isinstance(training_goal, dict):
        training_goal = {}
    training_text = str(training_goal.get("text") or "").strip()
    training_ids = _clean_ids(training_goal.get("evidence_block_ids"))
    courses = sorted(
        library.courses,
        key=lambda item: (item.source_order, item.course_id),
    )
    payload = {
        "schema_version": DERIVATION_SCHEMA_VERSION,
        "standard": {
            "library_id": library.id,
            "standard_id": library.standard_id,
            "standard_title": library.standard_title,
            "major_name": library.major_name,
            "education_level": library.education_level,
            "training_goal": {
                "text": training_text[:12000],
                "evidence_block_ids": training_ids,
                "locator": training_goal.get("locator") or {},
            },
            "hour_rules": [
                {
                    "rule_type": rule.rule_type,
                    "comparator": rule.comparator,
                    "numeric_value": rule.numeric_value,
                    "unit": rule.unit,
                    "evidence_block_ids": rule.evidence_block_ids,
                }
                for rule in sorted(
                    library.rules,
                    key=lambda item: (
                        item.rule_type,
                        item.source_text,
                        item.id,
                    ),
                )
            ],
        },
        "courses": [
            {
                "course_id": course.course_id,
                "standard_course_name": course.standard_course_name,
                "course_type": course.course_type,
                "typical_work_task_description": (
                    course.typical_work_task_description or ""
                )[:6000],
                "teaching_content_requirement": (
                    course.teaching_content_requirement or ""
                )[:6000],
                "evidence_block_ids": _course_evidence_ids(course),
                "evidence_locators": [
                    binding.get("locator") or {}
                    for binding in course.evidence_bindings
                    if isinstance(binding, dict)
                ][:20],
                "source_hash": course.source_hash,
            }
            for course in courses
        ],
    }
    if not training_text or not training_ids or not courses:
        return payload, "derivation_input_incomplete"
    if any(not item["evidence_block_ids"] for item in payload["courses"]):
        return payload, "derivation_input_incomplete"
    return payload, None


def _apply_redaction_policy(
    session: Session,
    payload: dict[str, Any],
    *,
    policy: str,
    sensitivity_level: str,
    effective_alias: str,
) -> dict[str, Any]:
    if policy not in {"metadata_only", "masked_content", "full_content_private"}:
        raise ValueError("unknown redaction policy")
    if sensitivity_level in {"L3", "L4"} and policy == "full_content_private":
        active_rules = session.scalars(
            select(models.GovernanceRulesVersion)
            .where(models.GovernanceRulesVersion.status == "active")
            .order_by(models.GovernanceRulesVersion.version.desc())
        ).first()
        approved = set(
            (active_rules.rules_content or {}).get("approved_private_model_aliases", [])
            if active_rules is not None
            else []
        )
        if effective_alias not in approved:
            raise ValueError("effective model is not approved for L3/L4 full content")

    copied = json.loads(json.dumps(payload, ensure_ascii=False))
    if policy == "metadata_only":
        copied["standard"]["training_goal"]["text"] = "[METADATA_ONLY]"
        for course in copied["courses"]:
            course["typical_work_task_description"] = "[METADATA_ONLY]"
            course["teaching_content_requirement"] = "[METADATA_ONLY]"
    elif sensitivity_level in {"L3", "L4"} and policy == "masked_content":
        copied["standard"]["training_goal"]["text"] = "[MASKED]"
        for course in copied["courses"]:
            course["typical_work_task_description"] = "[MASKED]"
            course["teaching_content_requirement"] = "[MASKED]"
    return copied


def _evidence_is_valid(
    library: models.TeachingStandardLibrary,
    courses_by_id: dict[str, models.TeachingStandardCourse],
    output: TeachingStandardDerivationOutput,
) -> bool:
    training_goal = (library.source_evidence or {}).get("training_goal_source") or {}
    training_allowed = set(_clean_ids(training_goal.get("evidence_block_ids")))
    if not set(output.training_goal_evidence_block_ids).issubset(training_allowed):
        return False
    for item in output.courses:
        allowed = set(_course_evidence_ids(courses_by_id[item.course_id]))
        if not set(item.evidence_block_ids).issubset(allowed):
            return False
        actual_tools = [tag for tag in item.tool_tags if tag != NO_SPECIFIC_TOOL]
        if actual_tools and not item.tool_evidence_block_ids:
            return False
        if not set(item.tool_evidence_block_ids).issubset(allowed):
            return False
    return True


def _course_evidence_ids(course: models.TeachingStandardCourse) -> list[str]:
    return list(
        dict.fromkeys(
            block_id
            for binding in course.evidence_bindings
            if isinstance(binding, dict)
            for block_id in _clean_ids(binding.get("evidence_block_ids"))
        )
    )


def _clean_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _input_hash(
    payload: dict[str, Any],
    profile: models.AIPromptProfile | None,
    effective_alias: str,
) -> str:
    return _canonical_hash(
        {
            "derivation_version": DERIVATION_VERSION,
            "prompt_profile_id": profile.id if profile is not None else None,
            "effective_model_alias": effective_alias,
            "payload": payload,
        }
    )


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _failed_without_call(
    session: Session,
    library: models.TeachingStandardLibrary,
    profile: models.AIPromptProfile | None,
    input_hash: str,
    failure_code: str,
    effective_alias: str,
    trace_id: str | None,
) -> DerivationResult:
    run = models.TeachingStandardDerivationRun(
        library_id=library.id,
        prompt_profile_id=profile.id if profile is not None else None,
        derivation_version=DERIVATION_VERSION,
        input_hash=input_hash,
        status="failed",
        failure_code=failure_code,
        completed_at=models.utcnow(),
    )
    session.add(run)
    session.flush()
    write_audit(
        session,
        AuditEventType.TEACHING_STANDARD_COURSE_DERIVATION_FAILED,
        "teaching_standard_derivation_run",
        run.id,
        trace_id,
        _audit_summary(run, effective_alias, len(library.courses), reused=False),
    )
    session.commit()
    return DerivationResult(
        run_id=run.id,
        status="failed",
        input_hash=input_hash,
        prompt_profile_id=run.prompt_profile_id,
        course_count=len(library.courses),
        failure_code=failure_code,
    )


def _fail_run(
    session: Session,
    run_id: str,
    library_id: str,
    failure_code: str,
    effective_alias: str,
    course_count: int,
    trace_id: str | None,
) -> DerivationResult:
    run = session.get(models.TeachingStandardDerivationRun, run_id)
    if run is None:
        raise RuntimeError(f"derivation run {run_id} vanished")
    run.status = "failed"
    run.failure_code = failure_code
    run.completed_at = models.utcnow()
    write_audit(
        session,
        AuditEventType.TEACHING_STANDARD_COURSE_DERIVATION_FAILED,
        "teaching_standard_derivation_run",
        run.id,
        trace_id,
        _audit_summary(run, effective_alias, course_count, reused=False),
    )
    session.commit()
    return DerivationResult(
        run_id=run.id,
        status="failed",
        input_hash=run.input_hash,
        prompt_profile_id=run.prompt_profile_id,
        course_count=course_count,
        failure_code=failure_code,
    )


def _audit_summary(
    run: models.TeachingStandardDerivationRun,
    effective_alias: str,
    course_count: int,
    *,
    reused: bool,
) -> dict[str, Any]:
    return {
        "library_id": run.library_id,
        "derivation_run_id": run.id,
        "prompt_profile_id": run.prompt_profile_id,
        "effective_model_alias": effective_alias,
        "input_hash": run.input_hash,
        "output_hash": run.output_hash,
        "course_count": course_count,
        "status": run.status,
        "failure_code": run.failure_code,
        "reused": reused,
    }


__all__ = [
    "DERIVATION_VERSION",
    "PROFILE_NAME",
    "SCENARIO",
    "TASK_TYPE",
    "DerivationResult",
    "derive_library",
]
