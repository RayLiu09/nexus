"""B5.2 — knowledge_unit extraction service.

What we lock in:

- Guardrails reject the right items (literacy-leak / cert-no-qualifier /
  unknown type / over-length / empty name) and never reject good ones.
- The service:
  - skips quietly when LLM client is None / rule set missing / prompt missing
  - persists items into job_demand_requirement_item with FK to record +
    rule_set + prompt
  - splits items by confidence vs. auto_admit_threshold (both persist, but
    low-confidence increments the dataset's quality_summary key)
  - drops malformed LLM output without raising
  - handles list-shaped responses as well as {items:[...]} shapes
- Seed-shipped rule set + prompt profile are picked up by the service's
  scenario lookup (no env config needed).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
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
    extract_requirements_for_dataset,
    seed_ai_analysis_rules,
)
from nexus_app.knowledge_extraction.guardrails import evaluate as eval_guard
from nexus_app.knowledge_extraction.schemas import (
    ALLOWED_ITEM_TYPES,
    RejectReason,
)
from nexus_app.knowledge_extraction.service import (
    _normalise_item,
    _parse_items,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _ScriptedLLM:
    """LLM stub that returns pre-canned responses keyed by call index.

    Falls back to raising LiteLLMCallError when responses are exhausted —
    that way a test that under-counts the expected call volume fails loudly
    instead of silently returning the same response twice.
    """
    responses: list[str | LiteLLMCallError]

    def __post_init__(self):
        self.calls: list[dict[str, Any]] = []

    def call(self, model_alias, messages, *, temperature=0.2, max_tokens=2048,
             response_format=None):
        idx = len(self.calls)
        self.calls.append({
            "model_alias": model_alias,
            "messages": messages,
            "response_format": response_format,
        })
        if idx >= len(self.responses):
            raise LiteLLMCallError(
                f"_ScriptedLLM ran out of responses at call #{idx}",
                LiteLLMErrorType.UNKNOWN,
            )
        rv = self.responses[idx]
        if isinstance(rv, LiteLLMCallError):
            raise rv
        return rv, LiteLLMCallSummary(
            model_alias=model_alias,
            request_id=f"scripted-{idx}",
            latency_ms=10.0,
            status="success",
            input_hash="h",
        )


# ---------------------------------------------------------------------------
# Fixtures — seed rule_set + prompt profile + a dataset with one record
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded(session):
    """Seed the ai_analysis_rules + ai_prompt_profile rows the service expects."""
    seed_ai_analysis_rules(session)
    # Insert the matching prompt profile (migration 0047 also does this for
    # PG; the test DB starts blank so we add it here).
    profile = models.AIPromptProfile(
        profile_name="occupation.job_demand.requirement_extraction",
        profile_version=1,
        task_type="knowledge_extraction",
        scenario="job_demand_requirement_extraction",
        domain="occupation",
        rules_object_type="ai_analysis_rules",
        rules_object_code="occupation.job_demand.requirement_extraction.rules:v1",
        status=PromptProfileStatus.ACTIVE,
        litellm_model_alias="internal/job-extract-v1",
        prompt_version="1.0",
        prompt_template="extract requirements as JSON {items:[...]}",
        temperature=0.2,
        max_input_tokens=4096,
        redaction_policy="masked_content",
        created_by="seed",
    )
    session.add(profile)
    session.commit()
    return profile


@pytest.fixture
def dataset(session, seeded):
    """One job_demand_dataset with two records — enough for low/high confidence splits."""
    # Minimal upstream rows so FK targets exist.
    asset = models.Asset(
        id="asset-1", asset_kind=AssetKind.RECORD, title="x",
        data_source_id="src", source_object_key="key-1",
    )
    raw = models.RawObject(
        id="raw-1", data_source_id="src", batch_id="batch-1",
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://b/p", checksum="cs",
        size_bytes=1, status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={},
    )
    version = models.AssetVersion(
        id="ver-1", asset_id="asset-1", raw_object_id="raw-1",
        version_no=1, source_checksum="cs",
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id="ref-1", version_id="ver-1",
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://b/payload.json",
        schema_version="normalized-record.v2",
        checksum="cs",
        status=NormalizedAssetRefStatus.GENERATED,
    )
    ds = models.JobDemandDataset(
        id="ds-1", normalized_ref_id="ref-1", asset_version_id="ver-1",
        source_channel="excel_upload", record_count=2,
        schema_version="job_demand.v1",
    )
    session.add_all([asset, raw, version, ref, ds])
    session.flush()
    session.add_all([
        models.JobDemandRecord(
            id="rec-1", dataset_id="ds-1", normalized_ref_id="ref-1",
            source_record_key="Sheet1#row2",
            job_title="数据分析师", company_name="字节",
            job_skill_text="精通 Python、SQL；熟悉 Spark",
            record_fingerprint="fp-1",
        ),
        models.JobDemandRecord(
            id="rec-2", dataset_id="ds-1", normalized_ref_id="ref-1",
            source_record_key="Sheet1#row3",
            job_title="数据工程师", company_name="美团",
            job_skill_text="精通 Java、Kafka",
            record_fingerprint="fp-2",
        ),
    ])
    session.commit()
    return ds


# ---------------------------------------------------------------------------
# Guardrails — direct unit tests
# ---------------------------------------------------------------------------


class TestGuardrails:
    def test_empty_name_rejected_even_with_no_tokens(self):
        assert eval_guard({"item_type": "tool", "item_name": ""}, []) == \
            RejectReason.GUARDRAIL_EMPTY_ITEM_NAME

    def test_unknown_type_rejected_even_with_no_tokens(self):
        assert eval_guard({"item_type": "garbage", "item_name": "x"}, []) == \
            RejectReason.GUARDRAIL_UNKNOWN_TYPE

    @pytest.mark.parametrize("name", ["团队协作", "communication", "学习能力"])
    def test_literacy_keyword_in_skill_rejected(self, name):
        assert eval_guard(
            {"item_type": "professional_skill", "item_name": name},
            ["reject_literacy_mixed_with_skill"],
        ) == RejectReason.GUARDRAIL_LITERACY_MIXED

    def test_literacy_keyword_in_actual_literacy_passes(self):
        # The guardrail fires only on professional_skill, not professional_literacy.
        assert eval_guard(
            {"item_type": "professional_literacy", "item_name": "团队协作"},
            ["reject_literacy_mixed_with_skill"],
        ) is None

    @pytest.mark.parametrize("name,expected_pass", [
        ("PMP", True),         # acronym
        ("AWS-SA", True),      # acronym with dash
        ("注册会计师证书", True),  # 证书 suffix
        ("证", True),           # 证 suffix
        ("hi", True),          # 2+ letters
        ("我", False),          # single Chinese char, no acronym, no qualifier
    ])
    def test_certificate_qualifier_guard(self, name, expected_pass):
        result = eval_guard(
            {"item_type": "certificate", "item_name": name},
            ["reject_certificate_without_acronym_or_full_name"],
        )
        assert (result is None) == expected_pass

    def test_long_item_name_rejected(self):
        name = "x" * 129
        assert eval_guard(
            {"item_type": "tool", "item_name": name},
            ["reject_skill_name_over_128_chars"],
        ) == RejectReason.GUARDRAIL_ITEM_NAME_TOO_LONG

    def test_unknown_token_is_ignored(self, caplog):
        # Forward-compatibility: a seed-side token that doesn't match a
        # registered fn must NOT crash the call.
        assert eval_guard(
            {"item_type": "tool", "item_name": "x"},
            ["a_brand_new_guardrail_token"],
        ) is None


# ---------------------------------------------------------------------------
# Service — happy path + edge cases
# ---------------------------------------------------------------------------


def _llm_payload(items: list[dict[str, Any]]) -> str:
    return json.dumps({"items": items})


class TestExtractionService:
    def test_skips_when_llm_unavailable(self, session, dataset):
        result = extract_requirements_for_dataset(
            session, dataset, llm_client=None,
        )
        assert result.skipped is True
        assert result.skipped_reason == "llm_client_unavailable"

    def test_skips_when_no_rule_set(self, session, dataset):
        session.query(models.AIAnalysisRules).delete()
        session.commit()
        result = extract_requirements_for_dataset(
            session, dataset,
            llm_client=_ScriptedLLM(responses=[]),
        )
        assert result.skipped is True
        assert result.skipped_reason == "rule_set_not_seeded"

    def test_skips_when_no_prompt_profile(self, session, dataset):
        session.query(models.AIPromptProfile).delete()
        session.commit()
        result = extract_requirements_for_dataset(
            session, dataset,
            llm_client=_ScriptedLLM(responses=[]),
        )
        assert result.skipped is True
        assert result.skipped_reason == "prompt_profile_not_seeded"

    def test_persists_items_above_threshold(self, session, dataset):
        items = [
            {"item_type": "professional_skill", "item_name": "Python",
             "raw_text": "精通 Python", "confidence": 0.95},
            {"item_type": "tool", "item_name": "SQL",
             "raw_text": "熟悉 SQL", "confidence": 0.90},
        ]
        llm = _ScriptedLLM(responses=[_llm_payload(items), _llm_payload(items)])
        result = extract_requirements_for_dataset(session, dataset, llm_client=llm)
        session.commit()

        assert result.skipped is False
        assert result.records_processed == 2
        assert result.items_persisted == 4
        assert result.items_low_confidence == 0
        assert result.items_rejected == 0

        rows = list(session.scalars(select(models.JobDemandRequirementItem)))
        assert len(rows) == 4
        assert all(r.dataset_id == "ds-1" for r in rows)
        assert all(r.rules_version_id == result.rule_set_id for r in rows)
        assert all(r.prompt_template_id == result.prompt_profile_id for r in rows)

    def test_low_confidence_items_persisted_and_counted(self, session, dataset):
        # threshold = 0.85 per seed; 0.6 < 0.85 → counted as low-confidence.
        items = [
            {"item_type": "professional_skill", "item_name": "Python",
             "confidence": 0.95},
            {"item_type": "tool", "item_name": "SQL", "confidence": 0.60},
        ]
        llm = _ScriptedLLM(responses=[_llm_payload(items), _llm_payload(items)])
        result = extract_requirements_for_dataset(session, dataset, llm_client=llm)
        session.commit()

        assert result.items_persisted == 4
        assert result.items_low_confidence == 2
        assert result.quality_summary["extraction_low_confidence_items"] == 2

    def test_guardrail_rejected_items_not_persisted(self, session, dataset):
        items = [
            {"item_type": "professional_skill", "item_name": "团队协作",  # literacy leak
             "confidence": 0.95},
            {"item_type": "tool", "item_name": "Python", "confidence": 0.95},
        ]
        llm = _ScriptedLLM(responses=[_llm_payload(items), _llm_payload(items)])
        result = extract_requirements_for_dataset(session, dataset, llm_client=llm)
        session.commit()

        assert result.items_persisted == 2   # only the tools
        assert result.items_rejected == 2
        key = f"extraction_{RejectReason.GUARDRAIL_LITERACY_MIXED}"
        assert result.quality_summary[key] == 2

    def test_malformed_llm_response_drops_record_without_raising(self, session, dataset):
        llm = _ScriptedLLM(responses=["not even json", _llm_payload([
            {"item_type": "tool", "item_name": "Python", "confidence": 0.95},
        ])])
        result = extract_requirements_for_dataset(session, dataset, llm_client=llm)
        session.commit()

        # record 1 → malformed (counts as 1 rejected). record 2 → 1 persisted.
        assert result.items_persisted == 1
        assert result.items_rejected == 1
        assert result.quality_summary["extraction_schema_invalid"] == 1

    def test_llm_call_failure_does_not_crash(self, session, dataset):
        llm = _ScriptedLLM(responses=[
            LiteLLMCallError("nope", LiteLLMErrorType.SERVER_ERROR),
            _llm_payload([
                {"item_type": "tool", "item_name": "Python", "confidence": 0.95},
            ]),
        ])
        result = extract_requirements_for_dataset(session, dataset, llm_client=llm)
        session.commit()
        # record 1 failed wholesale (counted under llm_call_failed quality key);
        # record 2 still persisted normally.
        assert result.items_persisted == 1
        assert result.quality_summary.get("extraction_llm_call_failed") == 1

    def test_accepts_list_shaped_response(self, session, dataset):
        # Some LLMs drop the {items:[...]} wrapper. Service should still parse.
        items = [
            {"item_type": "tool", "item_name": "Python", "confidence": 0.95},
        ]
        llm = _ScriptedLLM(responses=[json.dumps(items), json.dumps(items)])
        result = extract_requirements_for_dataset(session, dataset, llm_client=llm)
        session.commit()
        assert result.items_persisted == 2

    def test_field_whitelist_filters_llm_input(self, session, dataset):
        # `company_name` isn't in the rule_set's field_whitelist — verify it
        # never reaches the LLM input payload.
        llm = _ScriptedLLM(responses=[
            _llm_payload([]),
            _llm_payload([]),
        ])
        extract_requirements_for_dataset(session, dataset, llm_client=llm)
        session.commit()

        for call in llm.calls:
            user_msg = call["messages"][1]["content"]
            assert "美团" not in user_msg and "字节" not in user_msg, (
                f"company_name should be filtered by whitelist; got: {user_msg}"
            )

    def test_empty_dataset_returns_clean_result(self, session, dataset):
        session.query(models.JobDemandRecord).delete()
        session.commit()
        result = extract_requirements_for_dataset(
            session, dataset, llm_client=_ScriptedLLM(responses=[]),
        )
        assert result.skipped is False
        assert result.records_processed == 0
        assert result.items_persisted == 0


# ---------------------------------------------------------------------------
# Private helpers — direct unit tests so corner cases stay in the test file
# ---------------------------------------------------------------------------


class TestParseAndNormalise:
    def test_parse_dict_with_items_key(self):
        assert _parse_items('{"items": [{"a": 1}]}') == [{"a": 1}]

    def test_parse_list(self):
        assert _parse_items("[{\"a\": 1}]") == [{"a": 1}]

    def test_parse_returns_none_on_invalid_json(self):
        assert _parse_items("not json") is None

    def test_parse_returns_none_when_no_items_key(self):
        assert _parse_items('{"foo": 1}') is None

    def test_normalise_drops_missing_required(self):
        assert _normalise_item({"item_name": "x"}, Decimal("0.5")) is None
        assert _normalise_item({"item_type": "tool"}, Decimal("0.5")) is None

    def test_normalise_drops_unknown_item_type(self):
        assert _normalise_item(
            {"item_type": "garbage", "item_name": "x", "confidence": 0.9},
            Decimal("0.5"),
        ) is None

    def test_normalise_clamps_string_lengths(self):
        long = "x" * 600
        item = _normalise_item(
            {"item_type": "tool", "item_name": long[:200],
             "raw_text": long, "confidence": 0.9},
            Decimal("0.5"),
        )
        assert item is not None
        assert len(item.item_name) <= 128
        assert len(item.raw_text or "") <= 512

    def test_normalise_marks_low_confidence(self):
        item = _normalise_item(
            {"item_type": "tool", "item_name": "x", "confidence": 0.4},
            Decimal("0.85"),
        )
        assert item is not None
        assert item.is_low_confidence is True

    def test_allowed_item_types_covers_all_five(self):
        assert ALLOWED_ITEM_TYPES == {
            "professional_skill",
            "tool",
            "certificate",
            "professional_literacy",
            "work_task_candidate",
        }
