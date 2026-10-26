from datetime import datetime, timezone
import pytest
from nexus_app import models
from nexus_app.retrieval.executors.major_distribution import MajorDistributionRetrievalExecutor
from nexus_app.retrieval.schemas import RetrievalSubQuery
from nexus_app.retrieval.sql_guardrails import StructuredPlanGuardrailError


def seed(session):
    plan = models.DataSyncConfig(
        id="plan-md",
        name="MOE",
        provider_code="moe_major_offering",
        frequency="1_year",
        query_config={},
        created_by="admin",
        idempotency_key="plan",
        request_hash="q",
    )
    run = models.DataSyncRun(
        id="run-md",
        data_sync_config_id=plan.id,
        provider_code=plan.provider_code,
        adapter_version="1",
        query_snapshot={},
        query_hash="q",
        trace_id="test",
        status="succeeded",
    )
    session.add_all([plan, run])
    session.flush()
    for i, year in enumerate([2025, 2026, 2026]):
        session.add(
            models.MajorOfferingRecord(
                id=f"record-{i}",
                sync_run_id=run.id,
                provider_code=plan.provider_code,
                year=year,
                province_code="BJ",
                province_name="北京市",
                major_code="530701",
                major_name="电子商务",
                school_name=f"学校{i}",
                school_name_key=f"学校{i}",
                study_duration="3",
                source_url="https://zwfw.moe.gov.cn/zyyxzy/result.html",
                fetched_at=datetime.now(timezone.utc),
            )
        )
    session.commit()


def query(profile="trend_by_year", **plan):
    return RetrievalSubQuery.model_validate(
        {
            "query_id": "q1",
            "channel": "structured",
            "domain": "major_distribution",
            "purpose": "查询",
            "query_text": "专业布点",
            "structured_plan": {
                "table_profile": "major_offering.v1",
                "query_profile": "major_distribution." + profile,
                **plan,
            },
        }
    )


def test_count_facts_and_trace_direct_source(session):
    seed(session)
    result = MajorDistributionRetrievalExecutor().execute(
        session, query(group_by=["year"], metrics=[{"field": "record", "function": "count"}])
    )
    assert result.aggregations[0].series == [
        {"year": 2025, "value": 1, "record_count": 1},
        {"year": 2026, "value": 2, "record_count": 2},
    ]
    assert all(ref.normalized_ref_id is None for ref in result.source_refs)
    assert result.source_refs[0].metadata["sync_run_id"] == "run-md"
    assert "ingested_coverage_only" in result.warnings


def test_school_filter_and_sort(session):
    seed(session)
    result = MajorDistributionRetrievalExecutor().execute(
        session,
        query(
            "record_list",
            filters={"school_name": "学校1"},
            order_by=[{"field": "year", "direction": "asc"}],
        ),
    )
    assert [r["school_name"] for r in result.records] == ["学校1"]
    assert result.source_refs[0].record_ref == "major_offering_record:record-1"


def test_old_table_and_unsupported_fields_fail_closed(session):
    for plan in (
        {"table_profile": "major_distribution.v1"},
        {"filters": {"education_level": "本科"}},
        {"filters": {"sql": "DROP"}},
    ):
        q = query("record_list")
        q.structured_plan = q.structured_plan.model_copy(update=plan)
        with pytest.raises(StructuredPlanGuardrailError):
            MajorDistributionRetrievalExecutor().execute(session, q)
