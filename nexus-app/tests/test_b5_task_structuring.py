"""B5.4 — task_description_structured LLM service.

What we lock in:

- Service skips quietly when LLM client / rule_set / prompt is unavailable;
  caller never sees an exception.
- Happy path: well-formed LLM response (4 buckets, each list-of-strings)
  is persisted in-place on `occupational_work_task.task_description_structured`,
  overwriting the B6-written empty `{}`.
- Schema-invalid responses (missing bucket / non-list value / non-string
  member) are rejected as `schema_invalid` and the row is left alone.
- Hard guardrails fire as expected: `reject_empty_all_buckets`,
  `reject_string_over_64_chars`.
- Empty / blank `task_description` is silently skipped (no wasted LLM call).
- Long descriptions are truncated for the prompt input, not rejected.
- One task's LLM failure doesn't block sibling tasks.
- Aggregate counts roll up cleanly (structured / rejected / quality keys).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMCallSummary,
    LiteLLMErrorType,
)
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    NormalizedAssetRefStatus,
    NormalizedType,
    PromptProfileStatus,
    RawObjectStatus,
)
from nexus_app.knowledge_extraction import (
    seed_ai_analysis_rules,
    structure_task_descriptions_for_analysis,
)
from nexus_app.knowledge_extraction.task_structuring_service import (
    RejectReason,
    _evaluate_guardrails,
    _parse_buckets,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _ScriptedLLM:
    responses: list[str | LiteLLMCallError]

    def __post_init__(self):
        self.calls: list[dict[str, Any]] = []

    def call(self, model_alias, messages, *, temperature=0.2, max_tokens=2048,
             response_format=None):
        idx = len(self.calls)
        self.calls.append({
            "model_alias": model_alias, "messages": messages,
            "response_format": response_format,
        })
        if idx >= len(self.responses):
            raise LiteLLMCallError(
                f"_ScriptedLLM exhausted at call #{idx}",
                LiteLLMErrorType.UNKNOWN,
            )
        rv = self.responses[idx]
        if isinstance(rv, LiteLLMCallError):
            raise rv
        return rv, LiteLLMCallSummary(
            model_alias=model_alias, request_id=f"r{idx}",
            latency_ms=5.0, status="success", input_hash="h",
        )


class _TransactionCheckingLLM(_ScriptedLLM):
    def __init__(self, session, responses):
        super().__init__(responses=responses)
        self._session = session

    def call(self, *args, **kwargs):
        assert not self._session.in_transaction()
        return super().call(*args, **kwargs)


def _llm_buckets(*, roles=None, tools=None, env=None, modes=None) -> str:
    return json.dumps({
        "target_roles": roles or [],
        "tools": tools or [],
        "environment": env or [],
        "work_modes": modes or [],
    })


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_structuring(session):
    """Seed ai_analysis_rules + matching prompt profile."""
    seed_ai_analysis_rules(session)
    profile = models.AIPromptProfile(
        profile_name="occupation.task_description_structuring",
        profile_version=1,
        task_type="knowledge_extraction",
        scenario="occupational_task_description_structuring",
        domain="occupation",
        rules_object_type="ai_analysis_rules",
        rules_object_code="occupation.task_description_structuring.rules:v1",
        status=PromptProfileStatus.ACTIVE,
        litellm_model_alias="internal/task-struct-v1",
        prompt_version="1.0",
        prompt_template="structure task_description into target_roles / tools / environment / work_modes",
        temperature=0.2, max_input_tokens=2048,
        redaction_policy="masked_content", created_by="seed",
    )
    session.add(profile)
    session.commit()
    return profile


@pytest.fixture
def analysis(session, seeded_structuring):
    """One analysis with two tasks, both carrying real task_description text."""
    asset = models.Asset(
        id="a-1", asset_kind=AssetKind.RECORD, title="t",
        data_source_id="src", source_object_key="key-1",
    )
    raw = models.RawObject(
        id="r-1", data_source_id="src", batch_id="b-1",
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://b/p", checksum="cs",
        size_bytes=1, status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={},
    )
    version = models.AssetVersion(
        id="v-1", asset_id="a-1", raw_object_id="r-1",
        version_no=1, source_checksum="cs",
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id="ref-1", version_id="v-1",
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://b/payload.json",
        schema_version="normalized-record.v2",
        checksum="cs",
        status=NormalizedAssetRefStatus.GENERATED,
    )
    profile = models.AbilityAnalysisProfile(
        id="prof-1", model_code="PGSD", model_name="PGSD",
        schema_version="ability_analysis.pgsd.v1",
        category_schema=[], code_pattern={},
        is_active=True, is_builtin=True,
    )
    a = models.OccupationalAbilityAnalysis(
        id="ana-1", normalized_ref_id="ref-1", asset_version_id="v-1",
        profile_id="prof-1", analysis_model="PGSD",
        major_name="大数据技术应用",
        schema_version="ability_analysis.pgsd.v1",
    )
    session.add_all([asset, raw, version, ref, profile, a])
    session.flush()
    session.add_all([
        models.OccupationalWorkTask(
            id="t-1", analysis_id="ana-1",
            task_code="1", task_name="数据采集",
            task_description="①使用采集工具搭建系统 ②配置 Kafka 与 Flume",
            task_description_structured={},
            display_order=1,
        ),
        models.OccupationalWorkTask(
            id="t-2", analysis_id="ana-1",
            task_code="2", task_name="数据清洗",
            task_description="使用 Spark 在大数据集群完成数据清洗",
            task_description_structured={},
            display_order=2,
        ),
    ])
    session.commit()
    return a


# ---------------------------------------------------------------------------
# Service — happy path + edge cases
# ---------------------------------------------------------------------------


class TestServiceSkipPaths:
    def test_skips_when_llm_unavailable(self, session, analysis):
        result = structure_task_descriptions_for_analysis(
            session, analysis, llm_client=None,
        )
        assert result.skipped is True
        assert result.skipped_reason == "llm_client_unavailable"

    def test_skips_when_rule_set_missing(self, session, analysis):
        session.query(models.AIAnalysisRules).delete()
        session.commit()
        result = structure_task_descriptions_for_analysis(
            session, analysis, llm_client=_ScriptedLLM(responses=[]),
        )
        assert result.skipped is True
        assert result.skipped_reason == "rule_set_not_seeded"

    def test_skips_when_prompt_missing(self, session, analysis):
        session.query(models.AIPromptProfile).delete()
        session.commit()
        result = structure_task_descriptions_for_analysis(
            session, analysis, llm_client=_ScriptedLLM(responses=[]),
        )
        assert result.skipped is True
        assert result.skipped_reason == "prompt_profile_not_seeded"


class TestServiceHappyPath:
    def test_llm_calls_run_outside_database_transaction(self, session, analysis):
        llm = _TransactionCheckingLLM(
            session,
            responses=[_llm_buckets(roles=["数据工程师"])] * 2,
        )

        result = structure_task_descriptions_for_analysis(
            session, analysis, llm_client=llm,
        )

        assert result.tasks_structured == 2
        assert len(llm.calls) == 2

    def test_well_formed_response_populates_structured_column(
        self, session, analysis
    ):
        llm = _ScriptedLLM(responses=[
            _llm_buckets(
                roles=["数据采集工程师"], tools=["Kafka", "Flume"],
                env=["大数据集群"], modes=["持续运行"],
            ),
            _llm_buckets(
                roles=["数据工程师"], tools=["Spark"],
                env=["大数据集群"], modes=["批处理"],
            ),
        ])
        result = structure_task_descriptions_for_analysis(
            session, analysis, llm_client=llm,
        )
        session.commit()

        assert result.skipped is False
        assert result.tasks_processed == 2
        assert result.tasks_structured == 2
        assert result.tasks_rejected == 0

        rows = {t.id: t for t in session.scalars(
            select(models.OccupationalWorkTask).order_by(
                models.OccupationalWorkTask.task_code
            )
        )}
        assert rows["t-1"].task_description_structured == {
            "target_roles": ["数据采集工程师"],
            "tools": ["Kafka", "Flume"],
            "environment": ["大数据集群"],
            "work_modes": ["持续运行"],
        }
        assert rows["t-2"].task_description_structured["tools"] == ["Spark"]

    def test_blank_task_description_skipped_silently(self, session, analysis):
        for t in session.scalars(select(models.OccupationalWorkTask)):
            t.task_description = "   "
        session.commit()
        llm = _ScriptedLLM(responses=[])  # no responses queued — none should fire
        result = structure_task_descriptions_for_analysis(
            session, analysis, llm_client=llm,
        )
        # No LLM calls at all — both tasks short-circuited.
        assert len(llm.calls) == 0
        assert result.tasks_structured == 0
        assert result.tasks_rejected == 0

    def test_long_description_truncated_for_prompt(self, session, analysis):
        big = "x" * 5000
        for t in session.scalars(select(models.OccupationalWorkTask)):
            t.task_description = big
        session.commit()
        llm = _ScriptedLLM(responses=[
            _llm_buckets(roles=["a"]),
            _llm_buckets(roles=["a"]),
        ])
        structure_task_descriptions_for_analysis(session, analysis, llm_client=llm)
        for call in llm.calls:
            payload = json.loads(call["messages"][1]["content"])
            # Truncation cap is 4000 chars.
            assert len(payload["task_description"]) <= 4000

    def test_one_task_llm_failure_does_not_block_siblings(
        self, session, analysis
    ):
        llm = _ScriptedLLM(responses=[
            LiteLLMCallError("nope", LiteLLMErrorType.SERVER_ERROR),
            _llm_buckets(roles=["数据工程师"]),
        ])
        result = structure_task_descriptions_for_analysis(
            session, analysis, llm_client=llm,
        )
        session.commit()

        assert result.tasks_structured == 1
        assert result.tasks_rejected == 1
        # The failed task is still empty; the second task is populated.
        rows = {t.id: t for t in session.scalars(
            select(models.OccupationalWorkTask)
        )}
        assert rows["t-1"].task_description_structured == {}
        assert rows["t-2"].task_description_structured["target_roles"] == ["数据工程师"]


class TestServiceRejection:
    def test_schema_invalid_response_rejected(self, session, analysis):
        llm = _ScriptedLLM(responses=[
            "not json",
            _llm_buckets(roles=["a"]),
        ])
        result = structure_task_descriptions_for_analysis(
            session, analysis, llm_client=llm,
        )
        session.commit()
        assert result.tasks_rejected == 1
        assert result.tasks_structured == 1
        assert result.quality_summary.get(
            f"task_structuring_{RejectReason.SCHEMA_INVALID}"
        ) == 1

    def test_missing_bucket_rejected(self, session, analysis):
        llm = _ScriptedLLM(responses=[
            json.dumps({"target_roles": ["a"]}),  # missing 3 buckets
            _llm_buckets(roles=["a"]),
        ])
        result = structure_task_descriptions_for_analysis(
            session, analysis, llm_client=llm,
        )
        session.commit()
        assert result.tasks_rejected == 1

    def test_all_empty_buckets_rejected(self, session, analysis):
        llm = _ScriptedLLM(responses=[
            _llm_buckets(),
            _llm_buckets(roles=["a"]),
        ])
        result = structure_task_descriptions_for_analysis(
            session, analysis, llm_client=llm,
        )
        session.commit()
        assert result.tasks_rejected == 1
        assert result.quality_summary.get(
            f"task_structuring_{RejectReason.GUARDRAIL_EMPTY_ALL_BUCKETS}"
        ) == 1

    def test_long_string_rejects_task(self, session, analysis):
        long_tool = "x" * 65
        llm = _ScriptedLLM(responses=[
            _llm_buckets(roles=["a"], tools=[long_tool]),
            _llm_buckets(roles=["a"]),
        ])
        result = structure_task_descriptions_for_analysis(
            session, analysis, llm_client=llm,
        )
        session.commit()
        assert result.tasks_rejected == 1
        assert result.quality_summary.get(
            f"task_structuring_{RejectReason.GUARDRAIL_STRING_OVER_64_CHARS}"
        ) == 1


# ---------------------------------------------------------------------------
# Private helpers — direct unit tests for parse + guardrails
# ---------------------------------------------------------------------------


class TestParseBuckets:
    def test_accepts_4_bucket_object(self):
        result = _parse_buckets(_llm_buckets(roles=["a"], tools=["b"]))
        assert result == {
            "target_roles": ["a"], "tools": ["b"],
            "environment": [], "work_modes": [],
        }

    def test_unwraps_items_envelope(self):
        wrapped = json.dumps({"items": json.loads(_llm_buckets(roles=["a"]))})
        assert _parse_buckets(wrapped)["target_roles"] == ["a"]

    def test_strips_whitespace_and_drops_blank_items(self):
        body = json.dumps({
            "target_roles": ["  a ", "", "  ", "b"],
            "tools": [], "environment": [], "work_modes": [],
        })
        result = _parse_buckets(body)
        assert result["target_roles"] == ["a", "b"]

    def test_returns_none_when_bucket_non_list(self):
        body = json.dumps({
            "target_roles": "not a list",
            "tools": [], "environment": [], "work_modes": [],
        })
        assert _parse_buckets(body) is None

    def test_returns_none_when_member_non_string(self):
        body = json.dumps({
            "target_roles": [1, 2],
            "tools": [], "environment": [], "work_modes": [],
        })
        assert _parse_buckets(body) is None

    def test_returns_none_on_invalid_json(self):
        assert _parse_buckets("garbage") is None


class TestGuardrailEvaluator:
    def test_passes_when_one_bucket_has_content(self):
        result = _evaluate_guardrails({
            "target_roles": ["a"], "tools": [],
            "environment": [], "work_modes": [],
        })
        assert result is None

    def test_rejects_all_empty(self):
        result = _evaluate_guardrails({
            "target_roles": [], "tools": [],
            "environment": [], "work_modes": [],
        })
        assert result == RejectReason.GUARDRAIL_EMPTY_ALL_BUCKETS

    def test_rejects_long_string(self):
        result = _evaluate_guardrails({
            "target_roles": ["x" * 65],
            "tools": [], "environment": [], "work_modes": [],
        })
        assert result == RejectReason.GUARDRAIL_STRING_OVER_64_CHARS
