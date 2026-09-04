from __future__ import annotations

import json
from typing import Any, Callable

import pytest
from sqlalchemy import inspect, select

from nexus_app import models
from nexus_app.enums import AuditEventType, PromptProfileStatus
from nexus_app.teaching_standard_library.course_extractor import (
    extract as extract_courses,
)
from nexus_app.teaching_standard_library.course_writer import write as write_courses
from nexus_app.teaching_standard_library.derivation_schema import (
    DERIVATION_SCHEMA_VERSION,
)
from nexus_app.teaching_standard_library.derivation_service import (
    PROFILE_NAME,
    SCENARIO,
    TASK_TYPE,
    derive_library,
)
from tests.teaching_standard_library.test_slice2_course_projection import (
    _library,
    _payload,
)


class RecordingClient:
    def __init__(
        self,
        response: dict[str, Any],
        callback: Callable[[], None] | None = None,
    ) -> None:
        self.response = response
        self.callback = callback
        self.calls: list[dict[str, Any]] = []

    def call(
        self,
        model_alias: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, Any]:
        self.calls.append(
            {
                "model_alias": model_alias,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
            }
        )
        if self.callback is not None:
            self.callback()
        return json.dumps(self.response, ensure_ascii=False), None


def _seed_profile(session, *, model_alias: str = "") -> models.AIPromptProfile:
    profile = models.AIPromptProfile(
        id="tsd-profile",
        profile_name=PROFILE_NAME,
        profile_version=1,
        task_type=TASK_TYPE,
        scenario=SCENARIO,
        status=PromptProfileStatus.ACTIVE,
        litellm_model_alias=model_alias,
        prompt_version="1.0",
        prompt_template="derive all courses as strict JSON",
        output_schema_version=DERIVATION_SCHEMA_VERSION,
        scoring_weight_version="1.0",
        temperature=0.1,
        max_input_tokens=8192,
        redaction_policy="masked_content",
    )
    session.add(profile)
    session.flush()
    return profile


def _seed_library_with_courses(session) -> models.TeachingStandardLibrary:
    library = _library(session)
    library.source_evidence = {
        **(library.source_evidence or {}),
        "training_goal_source": {
            "text": "培养能够从事网络营销和网店运营工作的技术技能人才。",
            "evidence_block_ids": ["goal-1"],
            "locator": {"heading_path": ["培养目标"], "pages": [3]},
        },
    }
    projection = extract_courses(_payload())
    assert projection is not None
    write_courses(session, library, projection)
    session.flush()
    return library


def _complexity(course_type: str) -> str:
    return {
        "foundation": "foundation_theory_case",
        "core": "core_multi_task",
        "extension": "extension_standard_application",
    }[course_type]


def _response(library: models.TeachingStandardLibrary) -> dict[str, Any]:
    return {
        "schema_version": DERIVATION_SCHEMA_VERSION,
        "training_goal_summary": "培养网络营销、网店运营与数据分析能力。",
        "training_goal_evidence_block_ids": ["goal-1"],
        "courses": [
            {
                "course_id": course.course_id,
                "knowledge_tags": [f"{course.standard_course_name}知识"],
                "skill_tags": [f"{course.standard_course_name}技能"],
                "tool_tags": [],
                "literacy_tags": [f"{course.standard_course_name}素养"],
                "complexity_classification": _complexity(course.course_type),
                "evidence_block_ids": [
                    course.evidence_bindings[0]["evidence_block_ids"][0]
                ],
                "tool_evidence_block_ids": [],
            }
            for course in reversed(library.courses)
        ],
    }


@pytest.mark.parametrize(
    ("profile_alias", "fallback_alias", "expected_alias"),
    [
        ("", "governance/env-model", "governance/env-model"),
        ("   ", "governance/env-model", "governance/env-model"),
        (
            "governance/profile-model",
            "governance/env-model",
            "governance/profile-model",
        ),
    ],
)
def test_one_call_uses_model_priority_and_maps_reordered_results_by_course_id(
    session,
    profile_alias: str,
    fallback_alias: str,
    expected_alias: str,
) -> None:
    library = _seed_library_with_courses(session)
    profile = _seed_profile(session, model_alias=profile_alias)
    client = RecordingClient(_response(library))

    result = derive_library(
        session,
        library,
        llm_client=client,
        default_governance_model=fallback_alias,
        trace_id="trace-derive",
    )
    session.commit()

    assert result.status == "completed"
    assert result.prompt_profile_id == profile.id
    assert len(client.calls) == 1
    assert client.calls[0]["model_alias"] == expected_alias
    assert client.calls[0]["temperature"] == profile.temperature
    assert client.calls[0]["max_tokens"] == profile.max_input_tokens
    assert library.status == "review"
    assert library.training_goal_summary == "培养网络营销、网店运营与数据分析能力。"
    for course in library.courses:
        assert course.knowledge_tags == [f"{course.standard_course_name}知识"]
        assert course.skill_tags == [f"{course.standard_course_name}技能"]
        assert course.tool_tags == ["无特定工具要求"]
        assert course.standard_course_name in course.match_keywords
        assert course.suggested_practice_hours <= course.suggested_total_hours
        assert course.suggested_hours_range["min"] <= course.suggested_total_hours
        assert course.suggested_total_hours <= course.suggested_hours_range["max"]
    run = session.get(models.TeachingStandardDerivationRun, result.run_id)
    assert run is not None
    assert run.status == "completed"
    assert run.prompt_profile_id == profile.id
    assert not hasattr(run, "model_alias")
    audit = session.scalar(
        select(models.AuditLog).where(
            models.AuditLog.event_type
            == AuditEventType.TEACHING_STANDARD_COURSE_DERIVATION_COMPLETED
        )
    )
    assert audit is not None
    assert audit.summary["course_count"] == len(library.courses)
    assert audit.summary["effective_model_alias"] == expected_alias

    replay = derive_library(
        session,
        library,
        llm_client=client,
        default_governance_model=fallback_alias,
        trace_id="trace-replay",
    )

    assert replay.reused is True
    assert replay.run_id == result.run_id
    assert len(client.calls) == 1


@pytest.mark.parametrize("mismatch", ["unknown", "missing", "duplicate", "modified"])
def test_course_id_set_mismatch_rejects_the_whole_batch(session, mismatch: str) -> None:
    library = _seed_library_with_courses(session)
    _seed_profile(session)
    response = _response(library)
    if mismatch == "unknown":
        response["courses"][0]["course_id"] = "VC-UNKNOWN"
    elif mismatch == "missing":
        response["courses"].pop()
    elif mismatch == "duplicate":
        response["courses"][0]["course_id"] = response["courses"][1]["course_id"]
    else:
        response["courses"][0]["course_id"] += " "
    client = RecordingClient(response)

    result = derive_library(
        session,
        library,
        llm_client=client,
        default_governance_model="governance/env-model",
    )
    session.commit()

    assert result.status == "failed"
    assert result.failure_code in {
        "batch_course_id_mismatch",
        "batch_derivation_schema_invalid",
    }
    assert len(client.calls) == 1
    assert library.training_goal_summary is None
    assert all(course.knowledge_tags == [] for course in library.courses)
    assert all(course.suggested_total_hours is None for course in library.courses)


def test_invalid_evidence_and_complexity_type_never_partially_update_courses(
    session,
) -> None:
    library = _seed_library_with_courses(session)
    _seed_profile(session)
    response = _response(library)
    response["courses"][0]["evidence_block_ids"] = ["other-course-block"]
    client = RecordingClient(response)

    evidence_result = derive_library(
        session,
        library,
        llm_client=client,
        default_governance_model="governance/env-model",
    )
    session.commit()

    assert evidence_result.failure_code == "batch_derivation_evidence_invalid"
    assert all(course.knowledge_tags == [] for course in library.courses)

    response = _response(library)
    response["courses"][0]["complexity_classification"] = "core_multi_task"
    client = RecordingClient(response)
    hour_result = derive_library(
        session,
        library,
        llm_client=client,
        default_governance_model="governance/env-model",
    )
    session.commit()

    assert hour_result.failure_code == "hour_rule_validation_failed"
    assert all(course.knowledge_tags == [] for course in library.courses)


def test_actual_tool_tags_require_corresponding_course_evidence(session) -> None:
    library = _seed_library_with_courses(session)
    _seed_profile(session)
    response = _response(library)
    response["courses"][0]["tool_tags"] = ["数据分析工具"]
    client = RecordingClient(response)

    result = derive_library(
        session,
        library,
        llm_client=client,
        default_governance_model="governance/env-model",
    )
    session.commit()

    assert result.failure_code == "batch_derivation_evidence_invalid"
    assert all(course.tool_tags == [] for course in library.courses)
    assert all(course.match_keywords is None for course in library.courses)


def test_l3_masked_content_never_sends_source_narrative(session) -> None:
    library = _seed_library_with_courses(session)
    library.normalized_ref.governance = {"level": "L3"}
    _seed_profile(session)
    client = RecordingClient(_response(library))

    result = derive_library(
        session,
        library,
        llm_client=client,
        default_governance_model="governance/env-model",
    )
    session.commit()

    assert result.status == "completed"
    request = json.loads(client.calls[0]["messages"][1]["content"])
    assert request["standard"]["training_goal"]["text"] == "[MASKED]"
    assert all(
        course["typical_work_task_description"] == "[MASKED]"
        and course["teaching_content_requirement"] == "[MASKED]"
        for course in request["courses"]
    )


def test_missing_profile_records_failure_without_call_or_source_mutation(
    session,
) -> None:
    library = _seed_library_with_courses(session)
    client = RecordingClient(_response(library))

    result = derive_library(
        session,
        library,
        llm_client=client,
        default_governance_model="governance/env-model",
    )
    session.commit()

    assert result.failure_code == "prompt_profile_missing"
    assert client.calls == []
    assert library.status == "review"
    assert library.training_goal_summary is None
    run = session.get(models.TeachingStandardDerivationRun, result.run_id)
    assert run is not None
    assert run.prompt_profile_id is None


def test_source_change_during_model_call_rejects_adoption(session) -> None:
    library = _seed_library_with_courses(session)
    _seed_profile(session)
    response = _response(library)

    def change_source() -> None:
        library.courses[0].source_hash = "changed-during-call"
        session.flush()

    client = RecordingClient(response, callback=change_source)

    result = derive_library(
        session,
        library,
        llm_client=client,
        default_governance_model="governance/env-model",
    )
    session.commit()

    assert result.failure_code == "derivation_input_changed"
    assert all(course.knowledge_tags == [] for course in library.courses)
    assert library.training_goal_summary is None


def test_redaction_policy_change_during_model_call_rejects_adoption(session) -> None:
    library = _seed_library_with_courses(session)
    profile = _seed_profile(session)
    profile.redaction_policy = "full_content_private"
    response = _response(library)

    def raise_sensitivity() -> None:
        library.normalized_ref.governance = {"level": "L3"}
        session.flush()

    client = RecordingClient(response, callback=raise_sensitivity)

    result = derive_library(
        session,
        library,
        llm_client=client,
        default_governance_model="governance/env-model",
    )
    session.commit()

    assert result.failure_code == "derivation_input_changed"
    assert all(course.knowledge_tags == [] for course in library.courses)
    assert library.training_goal_summary is None


def test_derivation_run_schema_does_not_duplicate_prompt_or_model_configuration(
    session,
) -> None:
    inspector = inspect(session.bind)
    columns = {
        column["name"]
        for column in inspector.get_columns("teaching_standard_derivation_run")
    }

    assert "prompt_profile_id" in columns
    assert {
        "profile_version",
        "prompt_version",
        "model_alias",
        "litellm_model_alias",
    }.isdisjoint(columns)
