"""B5.5 — end-to-end B5 chain validation.

Verifies the three B5 services compose correctly against realistic
synthetic datasets that mirror the structure of samples 1 / 2:

- B5.2 → job_demand requirement extraction
- B5.3 → body_markdown render + skeleton validation + TTL cache
- B5.4 → task_description_structured fill

Plus the failure / fallback / cache scenarios called out in
`docs/pipeline_b_implementation_plan.md §B5 acceptance`:
- LLM failure → deterministic_template fallback for markdown
- LLM failure → audit emitted, items_persisted=0 for extraction
- Re-run with unchanged `record_body` → cache hit, no second LLM call

Service-level integration: we exercise the public service surface
(extract / render / structure) directly against a SQLite session seeded
the same way the alembic migrations + worker would. The worker-level
wiring is covered by the per-service unit tests; here we focus on the
**cross-service interactions** B5.5 acceptance demands.
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
from nexus_app.body_markdown import (
    RenderStrategy,
    render_body_markdown,
)
from nexus_app.body_markdown.cache import get_default_cache
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
    structure_task_descriptions_for_analysis,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _ScriptedLLM:
    """LLM stub with optional scenario-keyed responses.

    `responses` is a flat queue (used by extraction / structuring tests).
    `by_scenario_keyword` lets the body_markdown test fan out to the right
    response based on the system message — necessary because render +
    extract + structure all share one LLM but want different outputs.
    """
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
# Synthetic data builders — mirror the shape produced by B1/B2/B3/B4/B6
# ---------------------------------------------------------------------------


def _job_demand_record_body() -> dict[str, Any]:
    """Three records — enough to validate per-record extraction loop."""
    return {
        "dataset": {
            "source_channel": "excel_upload",
            "record_count": 3,
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
                "job_skill_text": "精通 Python、SQL；熟悉 Spark",
                "job_description": "负责数据分析、建模、汇报。",
            },
            {
                "source_record_key": "Sheet1#row3",
                "job_title": "数据工程师",
                "company_name": "美团",
                "city": "上海",
                "salary_text": "20k-35k",
                "education_requirement": "硕士",
                "job_skill_text": "Kafka、Hadoop、Flink",
                "job_description": "负责数据平台建设。",
            },
            {
                "source_record_key": "Sheet1#row4",
                "job_title": "BI 分析师",
                "company_name": "阿里",
                "city": "杭州",
                "salary_text": "25k-40k",
                "education_requirement": "本科",
                "job_skill_text": "Tableau、SQL；具备 CDA 证书更佳",
                "job_description": "负责报表、看板、业务洞察。",
            },
        ],
    }


def _ability_record_body() -> dict[str, Any]:
    return {
        "analysis": {
            "major_name": "大数据技术应用",
            "analysis_model": "PGSD",
            "task_count": 2,
            "work_content_count": 2,
            "ability_item_count": 6,
        },
        "tasks": [
            {
                "task_code": "1",
                "task_name": "数据采集",
                "task_description": "①使用采集工具搭建系统 ②配置 Kafka 与 Flume",
                "work_contents": [
                    {
                        "content_code": "1.1",
                        "content_name": "日志系统数据采集",
                        "abilities": [
                            {"ability_code": "P-1.1.1",
                             "ability_major_category_code": "P",
                             "ability_content": "能用采集工具采集日志"},
                        ],
                    },
                ],
                "general_abilities": {
                    "G": [{"ability_code": "G-1.1", "ability_content": "团队协作"}],
                    "S": [{"ability_code": "S-1.1", "ability_content": "沟通能力"}],
                    "D": [],
                },
            },
            {
                "task_code": "2",
                "task_name": "数据清洗",
                "task_description": "使用 Spark 在大数据集群完成数据清洗",
                "work_contents": [
                    {
                        "content_code": "2.1",
                        "content_name": "异常值清洗",
                        "abilities": [
                            {"ability_code": "P-2.1.1",
                             "ability_major_category_code": "P",
                             "ability_content": "能识别并清洗异常值"},
                        ],
                    },
                ],
                "general_abilities": {"G": [], "S": [], "D": []},
            },
        ],
    }


def _llm_extraction_response(record_title: str) -> str:
    """Deterministic per-record items shaped like a real LLM JSON-mode reply."""
    base = [
        {"item_type": "professional_skill", "item_name": "Python",
         "raw_text": "精通 Python", "confidence": 0.92,
         "evidence_field": "job_skill_text"},
        {"item_type": "tool", "item_name": "SQL",
         "raw_text": "熟悉 SQL", "confidence": 0.90,
         "evidence_field": "job_skill_text"},
        {"item_type": "professional_literacy", "item_name": "团队协作",
         "raw_text": "团队协作能力强", "confidence": 0.88,
         "evidence_field": "job_description"},
    ]
    if "BI" in record_title:
        # CDA 证书 satisfies the cert qualifier guardrail.
        base.append({
            "item_type": "certificate", "item_name": "CDA 证书",
            "raw_text": "具备 CDA 证书更佳", "confidence": 0.95,
            "evidence_field": "job_skill_text",
        })
    return json.dumps({"items": base})


# ---------------------------------------------------------------------------
# Fixtures — seed rules + dataset / analysis rows
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_render_cache():
    get_default_cache().clear()
    yield
    get_default_cache().clear()


@pytest.fixture
def seeded_b5(session):
    """All four B5 prompt profiles + the ai_analysis_rules rows."""
    seed_ai_analysis_rules(session)
    profiles = [
        ("occupation.job_demand.requirement_extraction",
         "knowledge_extraction", "job_demand_requirement_extraction",
         "occupation.job_demand.requirement_extraction.rules:v1",
         "extract requirements as items[]"),
        ("occupation.task_description_structuring",
         "knowledge_extraction", "occupational_task_description_structuring",
         "occupation.task_description_structuring.rules:v1",
         "structure task into 4 buckets"),
        ("occupation.job_demand.body_markdown_render",
         "body_markdown_render", "job_demand_body_markdown_render",
         "occupation.job_demand.body_markdown_render.rules:v1",
         "render markdown for job_demand"),
        ("occupation.ability_analysis.body_markdown_render",
         "body_markdown_render", "ability_analysis_body_markdown_render",
         "occupation.ability_analysis.body_markdown_render.rules:v1",
         "render markdown for ability_analysis"),
    ]
    for name, task_type, scenario, rules_code, template in profiles:
        session.add(models.AIPromptProfile(
            profile_name=name, profile_version=1, task_type=task_type,
            scenario=scenario, domain="occupation",
            rules_object_type="ai_analysis_rules",
            rules_object_code=rules_code,
            status=PromptProfileStatus.ACTIVE,
            litellm_model_alias="internal/test-v1",
            prompt_version="1.0", prompt_template=template,
            temperature=0.0, max_input_tokens=4096,
            redaction_policy="masked_content", created_by="seed",
        ))
    session.commit()


@pytest.fixture
def job_demand_setup(session, seeded_b5):
    """B4 writer output: dataset + 3 records, ready for B5.2 / B5.3."""
    asset = models.Asset(
        id="a-jd", asset_kind=AssetKind.RECORD, title="t",
        data_source_id="src", source_object_key="key-jd",
    )
    raw = models.RawObject(
        id="r-jd", data_source_id="src", batch_id="b-jd",
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://b/jd", checksum="cs",
        size_bytes=1, status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={},
    )
    version = models.AssetVersion(
        id="v-jd", asset_id="a-jd", raw_object_id="r-jd",
        version_no=1, source_checksum="cs",
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id="ref-jd", version_id="v-jd",
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://b/payload-jd.json",
        schema_version="normalized-record.v2",
        checksum="cs",
        status=NormalizedAssetRefStatus.GENERATED,
    )
    dataset = models.JobDemandDataset(
        id="ds-jd", normalized_ref_id="ref-jd", asset_version_id="v-jd",
        source_channel="excel_upload", record_count=3,
        schema_version="job_demand.v1",
    )
    session.add_all([asset, raw, version, ref, dataset])
    session.flush()
    records = [
        models.JobDemandRecord(
            id=f"rec-{i+1}", dataset_id="ds-jd", normalized_ref_id="ref-jd",
            source_record_key=r["source_record_key"],
            job_title=r["job_title"], company_name=r["company_name"],
            city=r["city"], salary_text=r.get("salary_text"),
            experience_requirement=r.get("experience_requirement"),
            education_requirement=r.get("education_requirement"),
            enterprise_size=r.get("enterprise_size"),
            industry_name=r.get("industry_name"),
            job_skill_text=r.get("job_skill_text"),
            job_description=r.get("job_description"),
            record_fingerprint=f"fp-{i+1}",
        )
        for i, r in enumerate(_job_demand_record_body()["records"])
    ]
    session.add_all(records)
    session.commit()
    return dataset


@pytest.fixture
def ability_setup(session, seeded_b5):
    """B6 writer output: analysis + 2 tasks (with empty structured), ready for B5.4 / B5.3."""
    asset = models.Asset(
        id="a-aa", asset_kind=AssetKind.RECORD, title="t",
        data_source_id="src", source_object_key="key-aa",
    )
    raw = models.RawObject(
        id="r-aa", data_source_id="src", batch_id="b-aa",
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://b/aa", checksum="cs",
        size_bytes=1, status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={},
    )
    version = models.AssetVersion(
        id="v-aa", asset_id="a-aa", raw_object_id="r-aa",
        version_no=1, source_checksum="cs",
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id="ref-aa", version_id="v-aa",
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://b/payload-aa.json",
        schema_version="normalized-record.v2",
        checksum="cs",
        status=NormalizedAssetRefStatus.GENERATED,
    )
    profile = models.AbilityAnalysisProfile(
        id="prof-pgsd", model_code="PGSD", model_name="PGSD",
        schema_version="ability_analysis.pgsd.v1",
        category_schema=[], code_pattern={},
        is_active=True, is_builtin=True,
    )
    analysis = models.OccupationalAbilityAnalysis(
        id="ana-1", normalized_ref_id="ref-aa", asset_version_id="v-aa",
        profile_id="prof-pgsd", analysis_model="PGSD",
        major_name="大数据技术应用",
        schema_version="ability_analysis.pgsd.v1",
    )
    session.add_all([asset, raw, version, ref, profile, analysis])
    session.flush()
    tasks = [
        models.OccupationalWorkTask(
            id="task-1", analysis_id="ana-1",
            task_code="1", task_name="数据采集",
            task_description="①使用采集工具搭建系统 ②配置 Kafka 与 Flume",
            task_description_structured={},
            display_order=1,
        ),
        models.OccupationalWorkTask(
            id="task-2", analysis_id="ana-1",
            task_code="2", task_name="数据清洗",
            task_description="使用 Spark 在大数据集群完成数据清洗",
            task_description_structured={},
            display_order=2,
        ),
    ]
    session.add_all(tasks)
    session.commit()
    return analysis


# ---------------------------------------------------------------------------
# Scenario 1 — sample-1-like flow: B5.2 extraction + B5.3 render
# ---------------------------------------------------------------------------


class TestSample1JobDemandChain:
    def test_extraction_produces_at_least_three_item_types(
        self, session, job_demand_setup
    ):
        # B5 acceptance: 样本 1 中 3 条岗位记录经抽取后落出 requirement_item，
        # 至少覆盖 professional_skill / tool / professional_literacy 三类。
        records = list(session.scalars(select(models.JobDemandRecord).order_by(
            models.JobDemandRecord.source_record_key
        )))
        responses = [_llm_extraction_response(r.job_title) for r in records]
        llm = _ScriptedLLM(responses=responses)

        result = extract_requirements_for_dataset(
            session, job_demand_setup, llm_client=llm,
        )
        session.commit()

        assert result.skipped is False
        assert result.items_persisted >= 9  # 3 records × 3 base items
        rows = list(session.scalars(select(models.JobDemandRequirementItem)))
        item_types = {r.item_type for r in rows}
        # Acceptance criterion — three distinct kinds at minimum.
        assert {"professional_skill", "tool", "professional_literacy"} <= item_types

    def test_body_markdown_renders_and_validates_for_job_demand(
        self, session, seeded_b5
    ):
        # Render flow needs no DB rows beyond seed (it consumes record_body
        # directly), so we don't reuse job_demand_setup here.
        body = _job_demand_record_body()
        result = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=body, llm_client=None,  # forces deterministic path
        )
        assert result.skipped is False
        assert result.meta.render_strategy == RenderStrategy.DETERMINISTIC_TEMPLATE_FALLBACK
        assert result.meta.skeleton_validation.passed, (
            f"violations: {result.meta.skeleton_validation.violations}"
        )
        # Sanity-check the rendered content has the records' titles.
        assert "数据分析师" in result.body_markdown
        assert "BI 分析师" in result.body_markdown


# ---------------------------------------------------------------------------
# Scenario 2 — sample-2-like flow: B5.4 structuring + B5.3 render
# ---------------------------------------------------------------------------


class TestSample2AbilityAnalysisChain:
    def test_task_structuring_fills_both_tasks(self, session, ability_setup):
        llm = _ScriptedLLM(responses=[
            json.dumps({
                "target_roles": ["数据采集工程师"],
                "tools": ["Kafka", "Flume"],
                "environment": ["大数据集群"],
                "work_modes": ["持续采集"],
            }),
            json.dumps({
                "target_roles": ["数据工程师"],
                "tools": ["Spark"],
                "environment": ["大数据集群"],
                "work_modes": ["批处理"],
            }),
        ])
        result = structure_task_descriptions_for_analysis(
            session, ability_setup, llm_client=llm,
        )
        session.commit()

        assert result.tasks_structured == 2
        rows = {t.task_code: t for t in session.scalars(
            select(models.OccupationalWorkTask)
        )}
        assert rows["1"].task_description_structured["tools"] == ["Kafka", "Flume"]
        assert rows["2"].task_description_structured["tools"] == ["Spark"]

    def test_body_markdown_renders_and_validates_for_ability_analysis(
        self, session, seeded_b5
    ):
        body = _ability_record_body()
        result = render_body_markdown(
            session, domain_profile="ability_analysis.pgsd.v1",
            record_body=body, llm_client=None,
        )
        assert result.skipped is False
        assert result.meta.skeleton_validation.passed, (
            f"violations: {result.meta.skeleton_validation.violations}"
        )
        # PGSD heading + every task code show up.
        assert "PGSD" in result.body_markdown
        assert "任务 1：数据采集" in result.body_markdown
        assert "任务 2：数据清洗" in result.body_markdown


# ---------------------------------------------------------------------------
# LLM failure path — deterministic fallback + extraction safe-skip
# ---------------------------------------------------------------------------


class TestLLMFailureFallback:
    def test_llm_failure_renders_deterministic_markdown(self, session, seeded_b5):
        # B5 acceptance: 模拟 LLM 失败 → deterministic template 兜底生效。
        body = _job_demand_record_body()
        llm = _ScriptedLLM(responses=[
            LiteLLMCallError("upstream down", LiteLLMErrorType.SERVER_ERROR),
        ])
        result = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=body, llm_client=llm,
        )
        assert result.skipped is False
        assert result.meta.render_strategy == RenderStrategy.DETERMINISTIC_TEMPLATE_FALLBACK
        assert result.meta.fallback_reason == "llm_render_failed_or_skeleton_invalid"
        # Fallback must still satisfy the skeleton, otherwise downstream
        # readers would see body_markdown_meta.skeleton_validation.passed=False.
        assert result.meta.skeleton_validation.passed
        # quality_flags.body_markdown_fallback is a downstream concern; the
        # render metadata is the audit-side equivalent — fallback_reason
        # populated proves the path took the fallback branch.
        assert result.body_markdown.startswith("# 岗位需求数据集")

    def test_llm_failure_during_extraction_persists_nothing_for_that_record(
        self, session, job_demand_setup
    ):
        records = list(session.scalars(select(models.JobDemandRecord).order_by(
            models.JobDemandRecord.source_record_key
        )))
        # Fail record 1, succeed records 2 + 3.
        llm = _ScriptedLLM(responses=[
            LiteLLMCallError("upstream down", LiteLLMErrorType.SERVER_ERROR),
            _llm_extraction_response(records[1].job_title),
            _llm_extraction_response(records[2].job_title),
        ])

        result = extract_requirements_for_dataset(
            session, job_demand_setup, llm_client=llm,
        )
        session.commit()

        # Persistence proceeded for the other two records.
        assert result.items_persisted >= 6
        assert result.quality_summary.get("extraction_llm_call_failed") == 1
        # Records 2 + 3 both have items; record 1 has none.
        records_with_items = {
            r.record_id for r in session.scalars(
                select(models.JobDemandRequirementItem)
            )
        }
        assert records[0].id not in records_with_items
        assert {records[1].id, records[2].id} <= records_with_items


# ---------------------------------------------------------------------------
# Cache behavior on rerun — B5.3 hits cache, no LLM call on second render
# ---------------------------------------------------------------------------


class TestCacheHitOnRerun:
    def test_rerun_with_unchanged_record_body_hits_cache(
        self, session, seeded_b5
    ):
        # B5 acceptance: 缓存命中：record_body 不变时重跑 normalize 不触发 LLM 调用。
        body = _job_demand_record_body()
        # First call uses the LLM. Build a successful skeleton-passing
        # markdown by reusing the deterministic template output the seed
        # renderer would have produced.
        from nexus_app.body_markdown.deterministic import render_job_demand

        skeleton = session.scalar(select(models.AIAnalysisRules).where(
            models.AIAnalysisRules.scenario == "job_demand_body_markdown_render"
        )).markdown_skeleton
        good_md, _, _ = render_job_demand(body, skeleton)

        llm = _ScriptedLLM(responses=[good_md])  # only ONE response queued

        first = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=body, llm_client=llm,
        )
        second = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=body, llm_client=llm,
        )

        # Both calls succeed with identical output...
        assert first.body_markdown == second.body_markdown
        assert first.meta.record_body_hash == second.meta.record_body_hash
        # ...but the LLM was only consulted once.
        assert len(llm.calls) == 1

    def test_changed_record_body_misses_cache(self, session, seeded_b5):
        from nexus_app.body_markdown.deterministic import render_job_demand
        skeleton = session.scalar(select(models.AIAnalysisRules).where(
            models.AIAnalysisRules.scenario == "job_demand_body_markdown_render"
        )).markdown_skeleton
        body1 = _job_demand_record_body()
        body2 = _job_demand_record_body()
        body2["records"][0]["job_title"] = "另一个岗位"

        md1, _, _ = render_job_demand(body1, skeleton)
        md2, _, _ = render_job_demand(body2, skeleton)
        llm = _ScriptedLLM(responses=[md1, md2])

        r1 = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=body1, llm_client=llm,
        )
        r2 = render_body_markdown(
            session, domain_profile="job_demand.v1",
            record_body=body2, llm_client=llm,
        )

        assert r1.meta.record_body_hash != r2.meta.record_body_hash
        assert len(llm.calls) == 2  # cache miss → LLM consulted both times


# ---------------------------------------------------------------------------
# Provenance — extracted items carry rules_version_id + prompt_template_id
# ---------------------------------------------------------------------------


class TestProvenanceFields:
    def test_requirement_items_carry_audit_fields(self, session, job_demand_setup):
        records = list(session.scalars(select(models.JobDemandRecord).order_by(
            models.JobDemandRecord.source_record_key
        )))
        llm = _ScriptedLLM(responses=[
            _llm_extraction_response(r.job_title) for r in records
        ])
        result = extract_requirements_for_dataset(
            session, job_demand_setup, llm_client=llm,
        )
        session.commit()
        # B5 acceptance: 审计日志可追溯到 prompt_template_id / rules_version_id /
        # ai_model_alias. Each persisted item carries all three so consumers
        # don't need to JOIN audit + items separately.
        items = list(session.scalars(select(models.JobDemandRequirementItem)))
        assert items
        for item in items:
            assert item.rules_version_id == result.rule_set_id
            assert item.prompt_template_id == result.prompt_profile_id
            assert item.ai_model_alias == "internal/test-v1"
            assert item.extractor_version == "1.0"
