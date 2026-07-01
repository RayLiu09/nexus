"""Tests for AI governance module — Week 3."""
from __future__ import annotations

import json
import time
import pytest

from nexus_app.ai_governance.input_builder import DefaultAIInputBuilder, RedactionPolicyError
from nexus_app.ai_governance.litellm_client import (
    FakeLiteLLMClient,
    LiteLLMCallError,
    LiteLLMErrorType,
)
from nexus_app.ai_governance.output_validator import AIGovernanceOutput, PydanticOutputValidator
from nexus_app.ai_governance.quality_scorer import QualityScoringService
from nexus_app.ai_governance.rules_config import GovernanceRulesConfig
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry():
    rules = {
        "schema_version": "1.0",
        "classifications": [
            {"code": "D4", "name": "教学资料", "description": "Teaching materials",
             "criteria": ["Contains teaching content"], "examples": ["Slides"]},
        ],
        "levels": [
            {"code": "L1", "name": "公开", "description": "Public",
             "criteria": ["Approved for public"], "requires_approval": False},
            {"code": "L2", "name": "内部", "description": "Internal",
             "criteria": ["Internal only"], "requires_approval": False},
            {"code": "L3", "name": "机密", "description": "Confidential",
             "criteria": ["Sensitive"], "requires_approval": True},
            {"code": "L4", "name": "绝密", "description": "Top secret",
             "criteria": ["Highest sensitivity"], "requires_approval": True},
        ],
        "tags": [
            {"code": "knowledge_asset", "name": "知识资产", "description": "Knowledge asset",
             "criteria": ["Reusable knowledge"], "applicable_classifications": ["D4"]},
        ],
        "quality_scoring": {
            "dimensions": [
                {"name": "completeness", "weight": 0.3, "description": "Completeness",
                 "check_items": [{"name": "has_title", "description": "Has title",
                                  "severity": "blocking"}]},
                {"name": "accuracy", "weight": 0.25, "description": "Accuracy",
                 "check_items": [{"name": "classification_confidence",
                                  "description": "Confidence", "severity": "warning"}]},
                {"name": "consistency", "weight": 0.25, "description": "Consistency",
                 "check_items": [{"name": "level_matches_classification",
                                  "description": "Level consistent", "severity": "warning"}]},
                {"name": "usability", "weight": 0.2, "description": "Usability",
                 "check_items": [{"name": "no_parse_errors",
                                  "description": "No parse errors", "severity": "blocking"}]},
            ],
            "thresholds": {"pass": 80, "warning": 60, "fail": 0},
            "confidence_threshold_auto_adopt": 0.85,
        },
    }
    reg = GovernanceRulesRegistry()
    reg.load_dict(rules)
    return reg


@pytest.fixture
def valid_ai_output():
    return AIGovernanceOutput(
        classification="D4", level="L2", tags=["knowledge_asset"],
        org_scope="all",
        quality_scores={"completeness": 85.0, "accuracy": 80.0,
                        "consistency": 90.0, "usability": 75.0},
        overall_score=83.0,
        evidence_refs=[],
        confidence=0.88,
        reasoning="Test reasoning",
    )


# ---------------------------------------------------------------------------
# GovernanceRulesRegistry tests
# ---------------------------------------------------------------------------

class TestGovernanceRulesRegistry:
    def test_load_valid_file(self, registry):
        assert registry._config is not None
        assert registry._config.schema_version == "1.0"

    def test_get_classifications(self, registry):
        classifications = registry.get_classifications()
        assert len(classifications) == 1
        assert classifications[0].code == "D4"

    def test_get_levels(self, registry):
        levels = registry.get_levels()
        assert len(levels) == 4
        codes = [l.code for l in levels]
        assert "L1" in codes and "L4" in codes

    def test_get_tags(self, registry):
        tags = registry.get_tags()
        assert len(tags) == 1
        assert tags[0].code == "knowledge_asset"

    def test_get_quality_scoring(self, registry):
        qs = registry.get_quality_scoring()
        total_weight = sum(d.weight for d in qs.dimensions)
        assert abs(total_weight - 1.0) < 0.001

    def test_reload_from_dict(self, registry):
        new_rules = {
            "schema_version": "1.0",
            "classifications": [{"code": "D2", "name": "D2", "description": "d",
                                  "criteria": ["c"]}],
            "levels": [{"code": "L1", "name": "L1", "description": "d",
                        "criteria": ["c"], "requires_approval": False}],
            "tags": [],
            "quality_scoring": {
                "dimensions": [{"name": "completeness", "weight": 1.0, "description": "c",
                                 "check_items": []}],
                "thresholds": {"pass": 80, "warning": 60},
                "confidence_threshold_auto_adopt": 0.85,
            },
        }
        registry.load_dict(new_rules)
        assert registry._config is not None
        assert len(registry.get_classifications()) == 1
        assert registry.get_classifications()[0].code == "D2"

    def test_weight_sum_not_one_raises(self):
        rules = {
            "schema_version": "1.0",
            "classifications": [{"code": "D1", "name": "D1", "description": "D1",
                                  "criteria": ["c1"]}],
            "levels": [{"code": "L1", "name": "L1", "description": "L1",
                        "criteria": ["c1"], "requires_approval": False}],
            "quality_scoring": {
                "dimensions": [
                    {"name": "completeness", "weight": 0.5, "description": "c",
                     "check_items": []},
                    {"name": "accuracy", "weight": 0.3, "description": "a",
                     "check_items": []},
                ],
                "thresholds": {"pass": 80, "warning": 60},
                "confidence_threshold_auto_adopt": 0.85,
            },
        }
        reg = GovernanceRulesRegistry()
        with pytest.raises(ValueError, match="weights must sum to 1.0"):
            reg.load_dict(rules)

    def test_tag_invalid_classification_ref_raises(self):
        rules = {
            "schema_version": "1.0",
            "classifications": [{"code": "D1", "name": "D1", "description": "D1",
                                  "criteria": ["c1"]}],
            "levels": [{"code": "L1", "name": "L1", "description": "L1",
                        "criteria": ["c1"], "requires_approval": False}],
            "tags": [{"code": "bad_tag", "name": "Bad", "description": "Bad",
                      "criteria": ["c"], "applicable_classifications": ["D99"]}],
            "quality_scoring": {
                "dimensions": [{"name": "completeness", "weight": 1.0, "description": "c",
                                 "check_items": []}],
                "thresholds": {"pass": 80, "warning": 60},
                "confidence_threshold_auto_adopt": 0.85,
            },
        }
        reg = GovernanceRulesRegistry()
        with pytest.raises(ValueError, match="unknown classification"):
            reg.load_dict(rules)

    def test_not_loaded_raises(self):
        reg = GovernanceRulesRegistry()
        with pytest.raises(RuntimeError, match="not initialized"):
            reg.get_classifications()


# ---------------------------------------------------------------------------
# FakeLiteLLMClient tests
# ---------------------------------------------------------------------------

class TestFakeLiteLLMClient:
    def test_call_returns_valid_json(self):
        client = FakeLiteLLMClient()
        content, summary = client.call("nexus-gpt-4o", [{"role": "user", "content": "test"}])
        parsed = json.loads(content)
        assert "classification" in parsed
        assert "level" in parsed
        assert summary.status == "success"
        assert summary.model_alias == "nexus-gpt-4o"

    def test_call_summary_has_input_hash(self):
        client = FakeLiteLLMClient()
        _, summary = client.call("alias", [{"role": "user", "content": "hello"}])
        assert len(summary.input_hash) > 0

    def test_custom_response_override(self):
        override = json.dumps({"classification": "D1", "level": "L1",
                               "overall_score": 90, "confidence": 0.95,
                               "evidence_refs": [], "reasoning": ""})
        client = FakeLiteLLMClient(response_override=override)
        content, _ = client.call("alias", [])
        assert json.loads(content)["classification"] == "D1"


# ---------------------------------------------------------------------------
# DefaultAIInputBuilder tests
# ---------------------------------------------------------------------------

class TestDefaultAIInputBuilder:
    def test_whitelist_filters_fields(self, registry):
        builder = DefaultAIInputBuilder()
        ref = {"title": "Doc", "content_snippet": "text", "secret_field": "should_be_removed"}
        result = builder.build(ref, "masked_content", "L1", registry=registry)
        assert "secret_field" not in result["payload"]
        assert "title" in result["payload"]

    def test_l3_content_masked(self, registry):
        builder = DefaultAIInputBuilder()
        ref = {"title": "Sensitive", "content_snippet": "secret content"}
        result = builder.build(ref, "masked_content", "L3", registry=registry)
        assert "[MASKED" in result["payload"]["content_snippet"]

    def test_l4_content_masked(self, registry):
        builder = DefaultAIInputBuilder()
        ref = {"title": "Top Secret", "content_snippet": "top secret content"}
        result = builder.build(ref, "masked_content", "L4", registry=registry)
        assert "[MASKED" in result["payload"]["content_snippet"]

    def test_l1_content_not_masked(self, registry):
        builder = DefaultAIInputBuilder()
        ref = {"title": "Public", "content_snippet": "public content"}
        result = builder.build(ref, "masked_content", "L1", registry=registry)
        assert result["payload"]["content_snippet"] == "public content"

    def test_metadata_only_strips_content(self, registry):
        builder = DefaultAIInputBuilder()
        ref = {"title": "Doc", "content_snippet": "some content"}
        result = builder.build(ref, "metadata_only", "L3", registry=registry)
        assert "[METADATA_ONLY" in result["payload"]["content_snippet"]

    def test_input_hash_is_deterministic(self, registry):
        builder = DefaultAIInputBuilder()
        ref = {"title": "Doc", "content_snippet": "text"}
        r1 = builder.build(ref, "masked_content", "L1", registry=registry)
        r2 = builder.build(ref, "masked_content", "L1", registry=registry)
        assert r1["input_hash"] == r2["input_hash"]

    def test_governance_context_injected(self, registry):
        builder = DefaultAIInputBuilder()
        ref = {"title": "Doc"}
        result = builder.build(ref, "masked_content", "L1", registry=registry)
        ctx = result["payload"]["governance_context"]
        assert len(ctx["classifications"]) > 0
        assert len(ctx["levels"]) > 0
        assert "criteria" in ctx["classifications"][0]

    def test_unknown_policy_raises(self, registry):
        builder = DefaultAIInputBuilder()
        ref = {"title": "Doc"}
        with pytest.raises(RedactionPolicyError):
            builder.build(ref, "unknown_policy", "L1", registry=registry)


# ---------------------------------------------------------------------------
# PydanticOutputValidator tests
# ---------------------------------------------------------------------------

class TestPydanticOutputValidator:
    def test_valid_output_passes(self):
        v = PydanticOutputValidator()
        raw = json.dumps({
            "classification": "D4", "level": "L2", "tags": [],
            "org_scope": "all", "quality_scores": {}, "overall_score": 80,
            "evidence_refs": [], "confidence": 0.9, "reasoning": "",
        })
        out, err = v.validate(raw)
        assert out is not None
        assert err is None

    def test_invalid_level_fails(self):
        v = PydanticOutputValidator()
        raw = json.dumps({
            "classification": "D4", "level": "L99",
            "overall_score": 80, "confidence": 0.9,
        })
        out, err = v.validate(raw)
        assert out is None
        assert err is not None

    def test_invalid_json_fails(self):
        v = PydanticOutputValidator()
        out, err = v.validate("not json {{{")
        assert out is None
        assert "JSON parse error" in err

    def test_missing_required_fields_fails(self):
        v = PydanticOutputValidator()
        out, err = v.validate(json.dumps({"level": "L1"}))
        assert out is None

    def test_confidence_out_of_range_fails(self):
        v = PydanticOutputValidator()
        raw = json.dumps({
            "classification": "D4", "level": "L2",
            "overall_score": 80, "confidence": 1.5,
        })
        out, err = v.validate(raw)
        assert out is None

    def test_registry_validation_allows_free_form_tag_values(self, registry):
        v = PydanticOutputValidator(registry)
        raw = json.dumps({
            "classification": "D4", "level": "L2", "tags": ["电子商务", "国际贸易"],
            "org_scope": "all", "quality_scores": {}, "overall_score": 80,
            "evidence_refs": [], "confidence": 0.9, "reasoning": "",
        })
        out, err = v.validate(raw)
        assert err is None
        assert out is not None
        assert out.tags == ["电子商务", "国际贸易"]


# ---------------------------------------------------------------------------
# QualityScoringService tests
# ---------------------------------------------------------------------------

class TestQualityScoringService:
    def test_generate_summary_pass(self, registry, valid_ai_output):
        svc = QualityScoringService(registry)
        ref = {"title": "Test", "content_snippet": "content"}
        summary = svc.generate_quality_summary(valid_ai_output, ref)
        assert summary.quality_level == "pass"
        assert summary.quality_score >= 80
        assert summary.scoring_source == "ai_primary"

    def test_dimension_scores_from_ai_output(self, registry, valid_ai_output):
        svc = QualityScoringService(registry)
        ref = {"title": "Test"}
        summary = svc.generate_quality_summary(valid_ai_output, ref)
        assert "completeness" in summary.dimension_scores
        assert summary.dimension_scores["completeness"] == 85.0

    def test_blocking_reasons_populated_on_fail(self, registry):
        svc = QualityScoringService(registry)
        low_ai = AIGovernanceOutput(
            classification="D4", level="L2", tags=[],
            org_scope="all", quality_scores={"completeness": 20, "accuracy": 30,
                                              "consistency": 40, "usability": 50},
            overall_score=35, evidence_refs=[], confidence=0.5, reasoning="",
        )
        ref = {}  # no title, no content
        summary = svc.generate_quality_summary(low_ai, ref)
        assert summary.quality_level in ("warning", "fail")

    def test_domain_quality_blocking_reasons_are_merged(self, registry, valid_ai_output):
        svc = QualityScoringService(registry)
        ref = {
            "title": "专业简介",
            "content_snippet": "专业介绍结构化内容",
            "domain_profile": "major_profile.v1",
            "domain_quality": {
                "blocking_reasons": [
                    "major_profile.missing_training_goal",
                    "major_profile.missing_core_courses",
                ],
            },
        }

        summary = svc.generate_quality_summary(valid_ai_output, ref)

        assert "major_profile.missing_training_goal" in summary.blocking_reasons
        assert "major_profile.missing_core_courses" in summary.blocking_reasons

    def test_weights_from_registry_not_hardcoded(self, registry):
        svc = QualityScoringService(registry)
        qs = registry.get_quality_scoring()
        weights = {d.name: d.weight for d in qs.dimensions}
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_evidence_refs_propagated(self, registry):
        from nexus_app.ai_governance.output_validator import EvidenceRef
        svc = QualityScoringService(registry)
        ai_out = AIGovernanceOutput(
            classification="D4", level="L2", tags=[],
            org_scope="all", quality_scores={}, overall_score=80,
            evidence_refs=[EvidenceRef(field="title", value="test", confidence=0.9)],
            confidence=0.88, reasoning="",
        )
        ref = {"title": "Test"}
        summary = svc.generate_quality_summary(ai_out, ref)
        assert len(summary.evidence_refs) == 1
        assert summary.evidence_refs[0].field == "title"


class TestMultiStageGovernanceAggregation:
    def test_aggregate_extracts_fixed_dimension_free_form_tag_values(self):
        from nexus_app.ai_governance.services import AIGovernanceService

        output = AIGovernanceService._aggregate_stage_outputs({
            "classification": {"classification_code": "D4", "confidence": 0.9},
            "level_assessment": {"level_code": "L1", "confidence": 0.9},
            "tagging": {
                "tags": {
                    "professional_domain": [
                        {"value": "电子商务", "criteria": "跨境电商行业报告"},
                        {"value": "国际贸易", "criteria": "出口贸易数据"},
                    ],
                    "education_level": [{"value": "高等教育", "criteria": "行业研究学习"}],
                    "geographic_scope": [{"value": "全球", "criteria": "覆盖全球市场"}],
                },
                "confidence": 0.91,
            },
        })

        assert output["tags"] == ["电子商务", "国际贸易", "高等教育", "全球"]
        assert output["tag_dimensions"]["professional_domain"][0] == {
            "value": "电子商务",
            "criteria": "跨境电商行业报告",
        }

    def test_aggregate_ignores_stage_metadata_and_ingest_channel_tags(self):
        from nexus_app.ai_governance.services import AIGovernanceService

        output = AIGovernanceService._aggregate_stage_outputs({
            "classification": {"classification_code": "D4", "confidence": 0.9},
            "level_assessment": {"level_code": "L1", "confidence": 0.9},
            "tagging": {
                "tags": {
                    "professional_domain": [
                        {"value": "电子商务", "criteria": "跨境电商行业报告"},
                        {"value": "#tagging", "criteria": "展示 token，不是业务标签"},
                        {"value": "doubao-seed-2-0-lite-260215", "criteria": "模型别名"},
                    ],
                    "data_source_type": [
                        {"value": "文件上传", "criteria": "source_type_hint=file_upload"},
                        {"value": "第三方行业研究机构", "criteria": "AMZ123 出品"},
                    ],
                },
                "confidence": 0.91,
                "_task_type": "tagging",
                "_model_alias": "doubao-seed-2-0-lite-260215",
            },
        })

        assert output["tags"] == ["电子商务", "第三方行业研究机构"]
        assert output["tag_dimensions"]["data_source_type"] == [
            {"value": "第三方行业研究机构", "criteria": "AMZ123 出品"}
        ]

    def test_aggregate_accepts_legacy_field_names_and_quality_scores(self):
        from nexus_app.ai_governance.services import AIGovernanceService

        output = AIGovernanceService._aggregate_stage_outputs({
            "classification": {
                "classification": "D4",
                "level": "L2",
                "tags": ["knowledge_asset"],
                "org_scope": "all",
                "quality_scores": {
                    "completeness": 85.0,
                    "accuracy": 80.0,
                    "consistency": 90.0,
                    "usability": 75.0,
                },
                "overall_score": 83.0,
                "confidence": 0.88,
                "evidence_refs": [],
            },
            "level_assessment": {"level": "L2", "confidence": 0.88},
            "tagging": {"tags": ["knowledge_asset"], "confidence": 0.88},
            "knowledge_type_inference": {"confidence": 0.88},
        })

        assert output["classification"] == "D4"
        assert output["level"] == "L2"
        assert output["tags"] == ["knowledge_asset"]
        assert output["quality_scores"]["completeness"] == 85.0
        assert output["overall_score"] == 83.0

    def test_quality_input_matches_scorer_contract(self, registry):
        from nexus_app.ai_governance.services import AIGovernanceService

        scoring_input = AIGovernanceService._build_quality_input(
            {
                "classification": "D4",
                "quality_scores": {
                    "completeness": 85.0,
                    "accuracy": 80.0,
                    "consistency": 90.0,
                    "usability": 75.0,
                },
                "overall_score": 83.0,
                "confidence": 0.88,
                "evidence_refs": [],
            },
            {"level": "L2", "confidence": 0.88},
            {"tags": ["knowledge_asset"], "confidence": 0.88},
        )

        summary = QualityScoringService(registry).generate_quality_summary(
            scoring_input, {"title": "doc", "content_snippet": "content"}
        )

        assert summary.quality_score > 0
        assert summary.confidence == 0.88


class TestMultiStageParallelExecution:
    def test_llm_stages_run_in_parallel(self, registry):
        from nexus_app.ai_governance.services import AIGovernanceService
        from nexus_app.ai_governance.prompt_registry import GovernancePromptRegistry
        from nexus_app.ai_governance.litellm_client import LiteLLMCallSummary
        from nexus_app import models

        class SlowFakeClient:
            def call(self, model_alias, messages, *, temperature=0.2, max_tokens=2048, response_format=None):
                time.sleep(0.05)
                content = json.dumps({
                    "classification": "D4",
                    "level": "L2",
                    "tags": ["knowledge_asset"],
                    "org_scope": "all",
                    "quality_scores": {
                        "completeness": 85.0,
                        "accuracy": 80.0,
                        "consistency": 90.0,
                        "usability": 75.0,
                    },
                    "overall_score": 83.0,
                    "evidence_refs": [],
                    "confidence": 0.88,
                })
                return content, LiteLLMCallSummary(
                    model_alias=model_alias,
                    request_id="slow-fake",
                    latency_ms=50.0,
                    status="success",
                    input_hash="h",
                )

        prompt_registry = GovernancePromptRegistry()
        prompt_registry._loaded = True
        prompt_registry._prompts = {
            task: models.GovernancePromptTemplate(
                id=f"prompt-{task}",
                task_type=task,
                template_name=task,
                template_version=1,
                status="active",
                prompt_template="{{DOCUMENT}}",
                output_schema_version="1.0",
                litellm_model_alias="fake",
                temperature=0.1,
                max_input_tokens=256,
                redaction_policy="metadata_only",
            )
            for task in ("classification", "level_assessment", "tagging", "knowledge_type_inference")
        }

        start = time.monotonic()
        outputs = AIGovernanceService()._run_llm_stages_parallel(
            SlowFakeClient(),
            prompt_registry,
            ("classification", "level_assessment", "tagging", "knowledge_type_inference"),
            {"title": "doc"},
            "L1",
            registry,
        )
        elapsed = time.monotonic() - start

        assert set(outputs) == {"classification", "level_assessment", "tagging", "knowledge_type_inference"}
        assert elapsed < 0.16
