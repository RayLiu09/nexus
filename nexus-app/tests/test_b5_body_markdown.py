"""B5.3 — body_markdown rendering with deterministic fallback + TTL cache.

What we lock in:

- Skeleton validator catches missing required headings + required field
  blocks + max_chars breaches; passes on a clean render; tolerates a buggy
  skeleton regex without raising.
- Deterministic renderers for job_demand + ability_analysis pass the B0
  seed skeleton validators (so the fallback path is contract-clean by
  construction).
- Service:
  - LLM success → returns llm_assisted strategy + caches result
  - LLM failure → falls back to deterministic, fallback_reason recorded
  - LLM produces skeleton-invalid markdown → falls back, recording the
    same fallback_reason
  - Cache hit → second call doesn't invoke the LLM client
  - No rule_set seeded → skipped, no markdown produced
  - Unknown domain_profile → skipped
  - Empty record_body → skipped
- TTL cache evicts stale entries (verified by patching time).
"""
from __future__ import annotations

import json
import re
import time
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
from nexus_app.body_markdown import (
    RenderCache,
    RenderStrategy,
    SUPPORTED_DOMAIN_PROFILES,
    render_body_markdown,
)
from nexus_app.body_markdown.cache import CacheKey
from nexus_app.body_markdown.deterministic import (
    render_ability_analysis,
    render_job_demand,
)
from nexus_app.body_markdown.skeleton_validator import validate as validate_skeleton
from nexus_app.enums import PromptProfileStatus
from nexus_app.knowledge_extraction import seed_ai_analysis_rules


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _ScriptedLLM:
    """One-call-per-test LLM stub. Raises if reused."""
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_render(session):
    """Seed ai_analysis_rules + matching prompt profiles for both scenarios."""
    seed_ai_analysis_rules(session)
    profiles = [
        models.AIPromptProfile(
            profile_name="occupation.job_demand.body_markdown_render",
            profile_version=1, task_type="body_markdown_render",
            scenario="job_demand_body_markdown_render",
            domain="occupation", rules_object_type="ai_analysis_rules",
            rules_object_code="occupation.job_demand.body_markdown_render.rules:v1",
            status=PromptProfileStatus.ACTIVE,
            litellm_model_alias="internal/markdown-v1",
            prompt_version="1.0",
            prompt_template="render markdown body for job demand",
            temperature=0.0, max_input_tokens=8192,
            redaction_policy="masked_content", created_by="seed",
        ),
        models.AIPromptProfile(
            profile_name="occupation.ability_analysis.body_markdown_render",
            profile_version=1, task_type="body_markdown_render",
            scenario="ability_analysis_body_markdown_render",
            domain="occupation", rules_object_type="ai_analysis_rules",
            rules_object_code="occupation.ability_analysis.body_markdown_render.rules:v1",
            status=PromptProfileStatus.ACTIVE,
            litellm_model_alias="internal/markdown-v1",
            prompt_version="1.0",
            prompt_template="render markdown body for ability analysis",
            temperature=0.0, max_input_tokens=8192,
            redaction_policy="masked_content", created_by="seed",
        ),
    ]
    session.add_all(profiles)
    session.commit()
    return profiles


def _job_demand_body() -> dict[str, Any]:
    return {
        "dataset": {
            "source_channel": "excel_upload",
            "record_count": 2,
            "invalid_count": 0,
            "duplicate_count": 0,
        },
        "records": [
            {
                "source_record_key": "Sheet1#row2",
                "job_title": "数据分析师",
                "company_name": "字节跳动",
                "city": "北京",
                "salary_text": "15k-25k",
                "experience_requirement": "3-5年",
                "education_requirement": "本科",
                "enterprise_size": "1000人以上",
                "industry_name": "信息技术",
                "job_skill_text": "精通 Python、SQL",
                "job_description": "负责数据分析、建模、汇报。",
            },
        ],
    }


def _ability_analysis_body() -> dict[str, Any]:
    return {
        "analysis": {
            "major_name": "大数据技术应用",
            "analysis_model": "PGSD",
            "task_count": 1,
            "work_content_count": 1,
            "ability_item_count": 3,
        },
        "tasks": [
            {
                "task_code": "1",
                "task_name": "数据采集",
                "task_description": "①搭建采集系统 ②配置采集源",
                "work_contents": [
                    {
                        "content_code": "1.1",
                        "content_name": "日志系统数据采集",
                        "abilities": [
                            {
                                "ability_code": "P-1.1.1",
                                "ability_major_category_code": "P",
                                "ability_content": "能用工具采集日志数据",
                            },
                        ],
                    },
                ],
                "general_abilities": {
                    "G": [{"ability_code": "G-1.1", "ability_content": "团队协作"}],
                    "S": [{"ability_code": "S-1.1", "ability_content": "沟通能力"}],
                    "D": [],
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# Skeleton validator — unit
# ---------------------------------------------------------------------------


class TestSkeletonValidator:
    def test_empty_skeleton_passes(self):
        result = validate_skeleton("# X\n", {})
        assert result.passed

    def test_required_headings_list_matches(self):
        md = "# 岗位需求数据集\n\n## 数据集概要\n"
        result = validate_skeleton(md, {
            "required_headings": ["^# 岗位需求数据集", "^## 数据集概要"],
        })
        assert result.passed

    def test_missing_required_heading_flagged(self):
        md = "# X\n"
        result = validate_skeleton(md, {
            "required_headings": ["^# 岗位需求数据集"],
        })
        assert not result.passed
        assert any("missing_required_heading" in v for v in result.violations)

    def test_required_h1_substring_matches(self):
        md = "# 岗位需求数据集\n"
        result = validate_skeleton(md, {"required_h1": "岗位需求数据集"})
        assert result.passed

    def test_required_overview_keys_substring(self):
        md = "数据集 专业 默认行业 有效记录数 内容"
        result = validate_skeleton(md, {
            "required_overview_keys": ["专业", "默认行业", "有效记录数"],
        })
        assert result.passed

    def test_per_record_h2_pattern_at_least_one_match(self):
        md = "# X\n\n## 记录 1：数据分析师\n"
        result = validate_skeleton(md, {
            "per_record_h2_pattern": "^## 记录 \\d+：.+$",
        })
        assert result.passed

    def test_max_chars_breach_flagged(self):
        md = "x" * 11
        result = validate_skeleton(md, {"max_chars": 10})
        assert not result.passed
        assert any("exceeds_max_chars" in v for v in result.violations)

    def test_buggy_regex_does_not_raise(self):
        # Unbalanced paren — should produce a violation, not crash.
        result = validate_skeleton("hello", {"required_headings": ["("]})
        assert not result.passed

    def test_empty_markdown_fails(self):
        result = validate_skeleton("", {"required_headings": ["x"]})
        assert not result.passed
        assert "empty_or_non_string_markdown" in result.violations


# ---------------------------------------------------------------------------
# Deterministic templates pass the B0 seed skeleton
# ---------------------------------------------------------------------------


def _load_skeleton(scenario: str, session) -> dict[str, Any]:
    seed_ai_analysis_rules(session)
    session.commit()
    rule = session.scalars(
        select(models.AIAnalysisRules).where(
            models.AIAnalysisRules.scenario == scenario
        )
    ).first()
    assert rule is not None and rule.markdown_skeleton is not None
    return rule.markdown_skeleton


class TestDeterministicTemplatesPassSkeleton:
    def test_job_demand_template_passes_seed_skeleton(self, session):
        skeleton = _load_skeleton("job_demand_body_markdown_render", session)
        markdown, _, omitted = render_job_demand(_job_demand_body(), skeleton)
        assert omitted == 0
        result = validate_skeleton(markdown, skeleton)
        assert result.passed, f"violations: {result.violations}\nmd:\n{markdown}"

    def test_ability_analysis_template_passes_seed_skeleton(self, session):
        skeleton = _load_skeleton("ability_analysis_body_markdown_render", session)
        markdown, _, omitted = render_ability_analysis(_ability_analysis_body(), skeleton)
        assert omitted == 0
        result = validate_skeleton(markdown, skeleton)
        assert result.passed, f"violations: {result.violations}\nmd:\n{markdown}"

    def test_job_demand_overflow_appended_when_records_exceed_max_inline(self):
        body = _job_demand_body()
        # Inflate to 60 records; seed max_records_inline = 50.
        body["records"] = body["records"] * 60
        markdown, inline, omitted = render_job_demand(body, {"max_records_inline": 50})
        assert inline == 50
        assert omitted == 10
        assert "10" in markdown  # overflow notice mentions the omitted count

    def test_ability_overflow_per_work_content(self):
        body = _ability_analysis_body()
        wc = body["tasks"][0]["work_contents"][0]
        wc["abilities"] = [
            {"ability_code": f"P-1.1.{i}", "ability_content": "x"} for i in range(35)
        ]
        markdown, inline, omitted = render_ability_analysis(
            body, {"max_abilities_per_work_content_inline": 30}
        )
        # 30 P + G(1) + S(1) inlined; 5 P omitted.
        assert inline == 32
        assert omitted == 5

    def test_renderers_never_raise_on_missing_fields(self):
        # Empty body must still emit a valid (if sparse) heading hierarchy.
        md_jd, _, _ = render_job_demand({"dataset": {}, "records": []})
        assert md_jd.startswith("# 岗位需求数据集")
        md_aa, _, _ = render_ability_analysis({"analysis": {}, "tasks": []})
        assert "职业能力分析" in md_aa


# ---------------------------------------------------------------------------
# Service orchestrator
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_default_cache():
    """Reset the module-singleton cache so tests don't leak between cases."""
    from nexus_app.body_markdown.cache import get_default_cache
    get_default_cache().clear()
    yield
    get_default_cache().clear()


class TestRenderService:
    def test_skips_when_no_rule_set(self, session):
        result = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=_job_demand_body(),
            llm_client=_ScriptedLLM(responses=[]),
        )
        assert result.skipped is True
        assert result.skipped_reason == "rule_set_not_seeded"

    def test_skips_unknown_domain_profile(self, session, seeded_render):
        result = render_body_markdown(
            session, domain_profile="not.a.profile",
            record_body={"x": 1},
            llm_client=_ScriptedLLM(responses=[]),
        )
        assert result.skipped is True
        assert result.skipped_reason == "unsupported_domain_profile"

    def test_skips_empty_record_body(self, session, seeded_render):
        result = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body={},
            llm_client=_ScriptedLLM(responses=[]),
        )
        assert result.skipped is True
        assert result.skipped_reason == "empty_record_body"

    def test_llm_success_returns_llm_assisted(self, session, seeded_render):
        skeleton = _load_skeleton("job_demand_body_markdown_render", session)
        markdown, _, _ = render_job_demand(_job_demand_body(), skeleton)
        llm = _ScriptedLLM(responses=[markdown])
        result = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=_job_demand_body(), llm_client=llm,
        )
        # `_extract_markdown` strips surrounding whitespace from LLM
        # responses — compare the stripped form rather than byte-exact.
        assert result.body_markdown.strip() == markdown.strip()
        assert result.meta.render_strategy == RenderStrategy.LLM_ASSISTED
        assert result.meta.skeleton_validation.passed
        assert result.meta.fallback_reason is None
        assert len(llm.calls) == 1

    def test_llm_failure_falls_back_to_deterministic(self, session, seeded_render):
        llm = _ScriptedLLM(responses=[LiteLLMCallError("boom", LiteLLMErrorType.SERVER_ERROR)])
        result = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=_job_demand_body(), llm_client=llm,
        )
        assert result.meta.render_strategy == RenderStrategy.DETERMINISTIC_TEMPLATE_FALLBACK
        assert result.meta.fallback_reason == "llm_render_failed_or_skeleton_invalid"
        assert result.body_markdown.startswith("# 岗位需求数据集")
        # Fallback render must also satisfy the skeleton — otherwise the
        # validator would mark passed=False and downstream consumers would
        # see a flag they can't act on.
        assert result.meta.skeleton_validation.passed

    def test_skeleton_invalid_llm_output_triggers_fallback(self, session, seeded_render):
        llm = _ScriptedLLM(responses=["# Wrong heading\n\nno required blocks"])
        result = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=_job_demand_body(), llm_client=llm,
        )
        assert result.meta.render_strategy == RenderStrategy.DETERMINISTIC_TEMPLATE_FALLBACK
        assert result.meta.fallback_reason == "llm_render_failed_or_skeleton_invalid"

    def test_no_llm_client_falls_back_without_calling(self, session, seeded_render):
        result = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=_job_demand_body(), llm_client=None,
        )
        assert result.meta.render_strategy == RenderStrategy.DETERMINISTIC_TEMPLATE_FALLBACK
        assert result.meta.fallback_reason == "llm_client_unavailable"

    def test_cache_hit_skips_llm_on_second_call(self, session, seeded_render):
        skeleton = _load_skeleton("job_demand_body_markdown_render", session)
        markdown, _, _ = render_job_demand(_job_demand_body(), skeleton)
        llm = _ScriptedLLM(responses=[markdown])  # only ONE response queued
        body = _job_demand_body()
        r1 = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=body, llm_client=llm,
        )
        r2 = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=body, llm_client=llm,
        )
        assert r1.body_markdown == r2.body_markdown
        assert r1.meta.record_body_hash == r2.meta.record_body_hash
        assert len(llm.calls) == 1  # second call hit cache

    def test_cache_keyed_on_record_body_hash(self, session, seeded_render):
        skel = _load_skeleton("job_demand_body_markdown_render", session)
        md1, _, _ = render_job_demand(_job_demand_body(), skel)
        body2 = _job_demand_body()
        body2["records"][0]["job_title"] = "另一个岗位"
        md2, _, _ = render_job_demand(body2, skel)
        llm = _ScriptedLLM(responses=[md1, md2])
        render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=_job_demand_body(), llm_client=llm,
        )
        render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=body2, llm_client=llm,
        )
        assert len(llm.calls) == 2  # different hash → cache miss on second

    def test_ability_analysis_path_renders(self, session, seeded_render):
        result = render_body_markdown(
            session, domain_profile="ability_analysis.pgsd.v1",
            record_body=_ability_analysis_body(), llm_client=None,
        )
        assert result.body_markdown is not None
        assert "PGSD" in result.body_markdown
        assert result.meta.skeleton_validation.passed

    def test_supported_domain_profiles_matches_registry(self):
        assert SUPPORTED_DOMAIN_PROFILES == {
            "job_demand.v1", "ability_analysis.pgsd.v1",
        }


# ---------------------------------------------------------------------------
# Cache TTL
# ---------------------------------------------------------------------------


class TestRenderCacheTTL:
    def test_put_then_get_roundtrips(self):
        cache: RenderCache[str] = RenderCache(ttl_seconds=60)
        key = CacheKey("c", "v1", "p", "1.0", "h1")
        cache.put(key, "value")
        assert cache.get(key) == "value"

    def test_expiry_evicts_entry(self, monkeypatch):
        cache: RenderCache[str] = RenderCache(ttl_seconds=10)
        key = CacheKey("c", "v1", "p", "1.0", "h1")
        cache.put(key, "value")
        # Advance monotonic clock past the TTL.
        baseline = time.monotonic() + 100
        monkeypatch.setattr(time, "monotonic", lambda: baseline)
        assert cache.get(key) is None

    def test_clear_empties_store(self):
        cache: RenderCache[str] = RenderCache(ttl_seconds=60)
        cache.put(CacheKey("c", "v1", "p", "1.0", "h1"), "v")
        assert len(cache) == 1
        cache.clear()
        assert len(cache) == 0
