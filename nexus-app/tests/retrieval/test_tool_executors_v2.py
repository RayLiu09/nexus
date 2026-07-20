"""B6/B7 — smoke tests for tool_executors_v2 real in-process executors.

Each executor gets a happy-path test that seeds the minimum data and
verifies the executor returns the expected shape. These are not
integration tests of the entire endpoint contract — they defend the
tool-registry-side of the wiring.

The chart-producing executors additionally verify that a chart is
registered on the shared ``ChartRegistry`` and the returned
``chart_id`` matches what the registry has.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from nexus_app import models
from nexus_app.enums import ChunkType, ChunkingStrategy, EmbeddingStatus, SourceKind
from nexus_app.evidence_graph.service import KnowledgeGraphBuildStatus
from nexus_app.retrieval.chart_adapter import ChartRegistry
from nexus_app.retrieval.tool_executors_v2 import (
    default_v2_executor_registry,
    get_evidence_graph_by_ref,
    get_outline_subtree,
    query_ability_analysis,
    query_capability_graph_by_major,
    query_job_demand,
    query_major_distribution,
)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_normalized_ref(session, *, ref_id: str = "ref-1") -> str:
    """SQLite tests don't enforce FKs — return a synthetic ref_id so
    child tables (JobDemandRecord, OutlineNode, etc.) can reference it
    without needing the full ingestion chain seeded.
    """
    return ref_id


# ---------------------------------------------------------------------------
# default_v2_executor_registry
# ---------------------------------------------------------------------------


def test_default_registry_has_all_tools():
    reg = default_v2_executor_registry(
        pgvector_adapter=SimpleNamespace(search=lambda *_, **__: []),
    )
    expected = {
        "internal.search_chunks_by_semantic",
        "internal.query_capability_graph_by_major",
        "internal.get_evidence_graph_by_ref",
        "internal.query_job_demand",
        "internal.get_job_demand_role_graph",
        "internal.query_ability_analysis",
        "internal.query_major_distribution",
        "internal.get_outline_subtree",
    }
    assert set(reg.executors.keys()) == expected


# ---------------------------------------------------------------------------
# search_chunks_by_semantic
# ---------------------------------------------------------------------------


def test_search_chunks_delegates_to_adapter(session):
    calls: list[dict] = []

    class _Adapter:
        def search(self, session_arg, **kwargs):
            calls.append(kwargs)
            return [{"nexus_chunk_id": "c1", "score": 0.9}]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    executor = make_search_chunks_executor(_Adapter())
    result = executor(
        session=session,
        arguments={"query": "跨境电商", "kb": "industry_research_kb", "top_k": 5},
        tool_call_id="tc-1",
        chart_registry=ChartRegistry(),
    )
    assert result["hits"] == [{"nexus_chunk_id": "c1", "score": 0.9}]
    assert result["kb"] == "industry_research_kb"
    assert result["kb_widened_to_all"] is False
    assert calls[0]["query"] == "跨境电商"
    assert calls[0]["top_k"] == 5


def test_search_chunks_widens_kb_on_empty_result(session):
    """Regression guard: LLM picking the wrong kb enum value must
    NOT crater recall — executor retries with kb=None and records
    the widen for Composer / audit."""
    calls: list[dict] = []

    class _Adapter:
        def search(self, session_arg, **kwargs):
            calls.append(kwargs)
            # First call (kb=practical_training_kb) → empty.
            # Second call (kb=None) → hit.
            if kwargs.get("knowledge_type_code") is None:
                return [{"nexus_chunk_id": "c2", "score": 0.8}]
            return []

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    executor = make_search_chunks_executor(_Adapter())
    result = executor(
        session=session,
        arguments={"query": "短视频平台的规则",
                    "kb": "practical_training_kb"},
        tool_call_id="tc-1",
        chart_registry=ChartRegistry(),
    )
    assert result["hits"] == [{"nexus_chunk_id": "c2", "score": 0.8}]
    assert result["kb"] == "practical_training_kb"
    assert result["kb_widened_to_all"] is True
    assert len(calls) == 2
    assert calls[0]["knowledge_type_code"] == "practical_training_kb"
    assert calls[1]["knowledge_type_code"] is None


def test_search_chunks_does_not_widen_when_kb_hits(session):
    """If the LLM's kb pick returns hits, don't do a second call."""
    calls: list[dict] = []

    class _Adapter:
        def search(self, session_arg, **kwargs):
            calls.append(kwargs)
            return [{"nexus_chunk_id": "c1", "score": 0.85}]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    executor = make_search_chunks_executor(_Adapter())
    result = executor(
        session=session,
        arguments={"query": "q", "kb": "course_textbook"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert result["kb_widened_to_all"] is False
    assert len(calls) == 1


def test_search_chunks_does_not_widen_when_kb_none(session):
    """If the caller didn't specify kb, the initial call already
    spans everything — no second query needed."""
    calls: list[dict] = []

    class _Adapter:
        def search(self, session_arg, **kwargs):
            calls.append(kwargs)
            return []

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    executor = make_search_chunks_executor(_Adapter())
    result = executor(
        session=session,
        arguments={"query": "q"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert result["kb_widened_to_all"] is False
    assert len(calls) == 1


def test_search_chunks_default_threshold_is_0_5(session):
    """Default similarity threshold was raised from 0.7 to 0.5 for
    wider recall on knowledge / concept queries."""
    seen: list[float] = []

    class _Adapter:
        def search(self, session_arg, *, similarity_threshold, **kwargs):
            seen.append(similarity_threshold)
            return []

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    executor = make_search_chunks_executor(_Adapter())
    executor(
        session=session, arguments={"query": "q"},
        tool_call_id="tc", chart_registry=ChartRegistry(),
    )
    assert seen[0] == 0.5


def test_search_chunks_expands_matching_theory_section_not_learning_goal(session):
    """A learning objective can be the vector hit without becoming the answer."""
    root = models.KnowledgeOutlineNode(
        id="outline-root", normalized_ref_id="ref-theory", parent_id=None,
        level=0, order_index=0, title="教材", build_run_id="build-1",
        chunk_count=0, fallback_used=False, node_metadata={},
    )
    wrong = models.KnowledgeOutlineNode(
        id="outline-wrong", normalized_ref_id="ref-theory", parent_id=root.id,
        level=1, order_index=1, title="视觉营销和短视频的定义", build_run_id="build-1",
        chunk_count=1, fallback_used=False, node_metadata={},
    )
    correct = models.KnowledgeOutlineNode(
        id="outline-platform", normalized_ref_id="ref-theory", parent_id=root.id,
        level=1, order_index=2, title="短视频平台的类型", build_run_id="build-1",
        chunk_count=2, fallback_used=False, node_metadata={},
    )
    session.add_all([root, wrong, correct])
    objective = _chunk(
        "objective", "ref-theory", 1, "4. 了解短视频平台的类型。",
        outline_id=wrong.id, heading_path=[{"title": "学习目标"}],
    )
    social = _chunk("social", "ref-theory", 2, "社交媒体类短视频平台侧重互动和社交功能。", outline_id=correct.id)
    commerce = _chunk("commerce", "ref-theory", 3, "电商推广类短视频平台用于产品展示和销售推广。", outline_id=correct.id)
    session.add_all([objective, social, commerce])
    session.flush()

    calls: list[dict] = []

    class _Adapter:
        def search(self, *_args, **_kwargs):
            calls.append(_kwargs)
            return [{"nexus_chunk_id": objective.id, "normalized_ref_id": "ref-theory", "score": 0.95}]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session, arguments={"query": "短视频平台的类型"},
        tool_call_id="tc", chart_registry=ChartRegistry(),
    )

    assert result["weak_evidence_chunk_ids"] == [objective.id]
    context = result["answer_contexts"][0]
    assert context["kind"] == "section_context"
    assert context["outline_node_id"] == correct.id
    assert [item["chunk_id"] for item in context["chunks"]] == [social.id, commerce.id]
    assert calls[0]["chunk_ids"] == [commerce.id, social.id]
    assert result["scope"]["source"] == "auto_outline_resolution"


def test_search_chunks_explicit_outline_node_is_mandatory_pre_ranking_scope(session):
    root = models.KnowledgeOutlineNode(
        id="explicit-root", normalized_ref_id="ref-explicit", parent_id=None,
        level=0, order_index=0, title="教材", build_run_id="build-1",
        chunk_count=0, fallback_used=False, node_metadata={},
    )
    section = models.KnowledgeOutlineNode(
        id="explicit-section", normalized_ref_id="ref-explicit", parent_id=root.id,
        level=1, order_index=1, title="目标章节", build_run_id="build-1",
        chunk_count=1, fallback_used=False, node_metadata={},
    )
    chunk = _chunk("explicit-chunk", "ref-explicit", 1, "目标章节正文", outline_id=section.id)
    session.add_all([root, section, chunk])
    session.flush()
    calls: list[dict] = []

    class _Adapter:
        def search(self, *_args, **kwargs):
            calls.append(kwargs)
            return []

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session,
        arguments={"query": "任意问题", "outline_node": section.id},
        tool_call_id="tc", chart_registry=ChartRegistry(),
    )

    assert calls[0]["chunk_ids"] == [chunk.id]
    assert len(calls) == 1
    assert result["scope"] == {
        "applied": True,
        "mandatory": True,
        "source": "explicit_outline_node",
        "kind": "knowledge_outline",
        "node_id": section.id,
        "title": section.title,
        "candidate_chunk_count": 1,
        "match_reason": "caller_selected_node",
        "fallback_to_unscoped": False,
    }


def test_search_chunks_auto_scope_fails_open_when_scoped_search_is_empty(session):
    root = models.KnowledgeOutlineNode(
        id="fallback-root", normalized_ref_id="ref-fallback", parent_id=None,
        level=0, order_index=0, title="教材", build_run_id="build-1",
        chunk_count=0, fallback_used=False, node_metadata={},
    )
    section = models.KnowledgeOutlineNode(
        id="fallback-section", normalized_ref_id="ref-fallback", parent_id=root.id,
        level=1, order_index=1, title="目标章节", build_run_id="build-1",
        chunk_count=1, fallback_used=False, node_metadata={},
    )
    chunk = _chunk("fallback-chunk", "ref-fallback", 1, "目标章节正文", outline_id=section.id)
    session.add_all([root, section, chunk])
    session.flush()
    calls: list[dict] = []

    class _Adapter:
        def search(self, *_args, **kwargs):
            calls.append(kwargs)
            return [] if kwargs.get("chunk_ids") else [{"nexus_chunk_id": "wide", "normalized_ref_id": "other"}]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session, arguments={"query": "目标章节"},
        tool_call_id="tc", chart_registry=ChartRegistry(),
    )

    assert calls[0]["chunk_ids"] == [chunk.id]
    assert calls[1].get("chunk_ids") is None
    assert result["scope"]["fallback_to_unscoped"] is True


def test_search_chunks_does_not_auto_scope_industry_kb(session):
    root = models.KnowledgeOutlineNode(
        id="industry-guard-root", normalized_ref_id="ref-industry-guard", parent_id=None,
        level=0, order_index=0, title="教材", build_run_id="build-1",
        chunk_count=0, fallback_used=False, node_metadata={},
    )
    section = models.KnowledgeOutlineNode(
        id="industry-guard-section", normalized_ref_id="ref-industry-guard", parent_id=root.id,
        level=1, order_index=1, title="产业平台类型", build_run_id="build-1",
        chunk_count=0, fallback_used=False, node_metadata={},
    )
    session.add_all([root, section])
    session.flush()
    calls: list[dict] = []

    class _Adapter:
        def search(self, *_args, **kwargs):
            calls.append(kwargs)
            return []

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session,
        arguments={"query": "产业平台类型", "kb": "industry_research_kb"},
        tool_call_id="tc", chart_registry=ChartRegistry(),
    )

    assert calls[0]["chunk_ids"] is None
    assert result["scope"]["applied"] is False
    assert result["scope"]["match_reason"] == "auto_scope_not_allowed_for_domain"


def test_search_chunks_expands_training_task_to_ordered_operation_steps(session):
    task = models.TaskOutlineNode(
        id="task-market", normalized_ref_id="ref-task", profile_id="profile-1",
        parent_id=None, node_type="task", section_type=None,
        title="工作任务一 市场数据采集", content=None, summary=None,
        order_no=1, depth=0, source_block_ids=[], locator=None, node_metadata={},
    )
    section = models.TaskOutlineNode(
        id="task-market-steps", normalized_ref_id="ref-task", profile_id="profile-1",
        parent_id=task.id, node_type="task_section", section_type="operation_steps",
        title="任务操作", content=None, summary=None, order_no=2, depth=1,
        source_block_ids=[], locator=None, node_metadata={},
    )
    step_one = models.TaskOutlineNode(
        id="task-market-step-1", normalized_ref_id="ref-task", profile_id="profile-1",
        parent_id=section.id, node_type="operation_step", section_type="operation_steps",
        title="步骤1", content="确定数据来源", summary=None, order_no=3, depth=2,
        source_block_ids=[], locator=None, node_metadata={"step_no": 1},
    )
    step_two = models.TaskOutlineNode(
        id="task-market-step-2", normalized_ref_id="ref-task", profile_id="profile-1",
        parent_id=section.id, node_type="operation_step", section_type="operation_steps",
        title="步骤2", content="确定采集范围", summary=None, order_no=4, depth=2,
        source_block_ids=[], locator=None, node_metadata={"step_no": 2},
    )
    session.add_all([task, section, step_one, step_two])
    hit = _chunk("task-hit", "ref-task", 1, "任务：工作任务一 市场数据采集", task_node_id=task.id)
    chunk_one = _chunk("task-step-1", "ref-task", 2, "操作步骤 1：步骤1，确定数据来源。步骤1，确定数据来源。补充说明。", task_node_id=step_one.id)
    chunk_two = _chunk("task-step-2", "ref-task", 3, "操作步骤 2：确定采集范围", task_node_id=step_two.id)
    session.add_all([hit, chunk_one, chunk_two])
    session.flush()

    calls: list[dict] = []

    class _Adapter:
        def search(self, *_args, **_kwargs):
            calls.append(_kwargs)
            return [{"nexus_chunk_id": hit.id, "normalized_ref_id": "ref-task", "score": 0.94}]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session, arguments={"query": "市场数据采集流程是什么"},
        tool_call_id="tc", chart_registry=ChartRegistry(),
    )

    context = result["answer_contexts"][0]
    assert context["kind"] == "task_context"
    assert context["task_node_id"] == task.id
    assert [(item["step_no"], item["chunk_id"]) for item in context["chunks"]] == [
        (1, chunk_one.id), (2, chunk_two.id),
    ]
    assert context["chunks"][0]["content"] == "确定数据来源。补充说明。"
    assert calls[0]["chunk_ids"] == [chunk_one.id, chunk_two.id]
    assert result["scope"]["match_reason"] == "query_title_containment_operation_steps"


def test_search_chunks_scopes_compact_query_to_decorated_outline_title(session):
    root = models.KnowledgeOutlineNode(
        id="rules-root", normalized_ref_id="ref-rules", parent_id=None,
        level=0, order_index=0, title="短视频", build_run_id="build-1",
        chunk_count=0, fallback_used=False, node_metadata={},
    )
    section = models.KnowledgeOutlineNode(
        id="rules-section", normalized_ref_id="ref-rules", parent_id=root.id,
        level=1, order_index=1, title="二、短视频平台的相关规则", build_run_id="build-1",
        chunk_count=1, fallback_used=False, node_metadata={},
    )
    chunk = _chunk(
        "rules-chunk", "ref-rules", 1, "短视频平台应遵守内容发布相关规则。",
        outline_id=section.id,
    )
    stale_chunk = _chunk(
        "stale-rules-chunk", "ref-rules", 2, "课后训练不属于平台规则正文。",
        outline_id=section.id,
    )
    chunk.locator = {"heading_path": [{"level": 2, "title": "二、短视频平台的相关规则"}]}
    stale_chunk.locator = {"heading_path": [{"level": 2, "title": "课后训练"}]}
    session.add_all([root, section, chunk, stale_chunk])
    session.flush()
    calls: list[dict] = []

    class _Adapter:
        def search(self, *_args, **kwargs):
            calls.append(kwargs)
            return [{"nexus_chunk_id": chunk.id, "normalized_ref_id": chunk.normalized_ref_id}]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session, arguments={"query": "短视频平台规则"},
        tool_call_id="tc", chart_registry=ChartRegistry(),
    )

    assert calls[0]["chunk_ids"] == [chunk.id]
    assert result["scope"]["title"] == "二、短视频平台的相关规则"
    assert result["answer_contexts"][0]["title"] == "二、短视频平台的相关规则"
    assert [item["chunk_id"] for item in result["answer_contexts"][0]["chunks"]] == [chunk.id]


def _chunk(
    chunk_id, ref_id, index, content, *, outline_id=None, task_node_id=None, heading_path=None,
):
    metadata = {"heading_path": heading_path or []}
    if task_node_id:
        metadata.update({"domain_model": "task_outline.v1", "outline_node_id": task_node_id})
    return models.KnowledgeChunk(
        id=chunk_id, normalized_ref_id=ref_id, knowledge_type_code="course_textbook",
        chunk_type=ChunkType.SEMANTIC_BLOCK, chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED, chunk_index=index, content=content,
        chunk_metadata=metadata, embedding_status=EmbeddingStatus.EMBEDDED,
        source_block_ids=[], locator={}, knowledge_outline_node_id=outline_id,
    )


# ---------------------------------------------------------------------------
# query_capability_graph_by_major
# ---------------------------------------------------------------------------


def test_capability_graph_by_major_returns_and_registers_chart(session):
    ref_id = _seed_normalized_ref(session)
    build = models.CapabilityGraphStagingBuild(
        id="b-1", normalized_ref_id=ref_id,
        domain="job", build_type="ability_analysis",
        status="GENERATED", schema_version="v1",
        major_name="跨境电商", major_code="5301",
    )
    node = models.CapabilityGraphStagingNode(
        id="n-1", build_id=build.id,
        node_type="position", node_key="pos-1",
        display_name="新媒体运营",
    )
    session.add_all([build, node])
    session.flush()

    registry = ChartRegistry()
    result = query_capability_graph_by_major(
        session=session,
        arguments={"major_name": "跨境电商", "build_type": "ability_analysis"},
        tool_call_id="tc-1",
        chart_registry=registry,
    )
    assert result["found"] is True
    assert result["node_count"] == 1
    assert result["chart_id"] in registry.registered_ids()


def test_capability_graph_by_major_returns_not_found(session):
    result = query_capability_graph_by_major(
        session=session,
        arguments={"major_name": "不存在", "build_type": "teaching_standard"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert result["found"] is False


# ---------------------------------------------------------------------------
# query_job_demand
# ---------------------------------------------------------------------------


def test_query_job_demand_returns_records_and_industry_distribution(session):
    ref_id = _seed_normalized_ref(session)
    ds = models.JobDemandDataset(
        id="jdd-1", normalized_ref_id=ref_id, asset_version_id="ver-1",
        source_channel="excel_upload",
        major_name="跨境电商", schema_version="v1",
    )
    rec1 = models.JobDemandRecord(
        id="r-1", dataset_id=ds.id, normalized_ref_id=ref_id,
        source_record_key="k1", job_title="运营", city="上海",
        industry_name="电子商务", record_fingerprint="abc1",
    )
    rec2 = models.JobDemandRecord(
        id="r-2", dataset_id=ds.id, normalized_ref_id=ref_id,
        source_record_key="k2", job_title="推广", city="杭州",
        industry_name="电子商务", record_fingerprint="abc2",
    )
    rec3 = models.JobDemandRecord(
        id="r-3", dataset_id=ds.id, normalized_ref_id=ref_id,
        source_record_key="k3", job_title="客服", city="深圳",
        industry_name="教育", record_fingerprint="abc3",
    )
    session.add_all([ds, rec1, rec2, rec3])
    session.flush()

    result = query_job_demand(
        session=session,
        arguments={"major": "跨境电商"},  # default fields → include aggregation
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert result["record_count"] == 3
    dist = result["aggregations"]["industry_distribution"]
    # 电子商务 has 2 records, 教育 has 1 — desc order.
    assert dist[0] == {"industry_name": "电子商务", "count": 2}
    assert dist[1] == {"industry_name": "教育", "count": 1}


def test_query_job_demand_suppresses_distribution_when_fields_omit(session):
    ds = models.JobDemandDataset(
        id="jdd-2", normalized_ref_id="ref-suppress", asset_version_id="ver-2",
        source_channel="excel_upload",
        major_name="跨境电商", schema_version="v1",
    )
    session.add(ds)
    session.add(models.JobDemandRecord(
        id="r-9", dataset_id=ds.id, normalized_ref_id="ref-suppress",
        source_record_key="k1", job_title="x", record_fingerprint="fp",
    ))
    session.flush()

    result = query_job_demand(
        session=session,
        arguments={"major": "跨境电商", "fields": ["count"]},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert "industry_distribution" not in result["aggregations"]


# ---------------------------------------------------------------------------
# query_ability_analysis
# ---------------------------------------------------------------------------


def test_query_ability_analysis_with_include(session):
    ref_id = _seed_normalized_ref(session)
    profile = models.AbilityAnalysisProfile(
        id="prof-1", model_code="PGSD", model_name="PGSD",
        schema_version="v1",
    )
    session.add(profile)
    session.flush()
    analysis = models.OccupationalAbilityAnalysis(
        id="a-1", normalized_ref_id=ref_id, asset_version_id="ver-1",
        profile_id=profile.id, analysis_model="PGSD",
        major_name="跨境电商", schema_version="v1",
    )
    task = models.OccupationalWorkTask(
        id="t-1", analysis_id=analysis.id,
        task_code="T01", task_name="订单管理",
    )
    item = models.OccupationalAbilityItem(
        id="i-1", analysis_id=analysis.id, task_id=task.id,
        ability_code="G01", ability_major_category_code="G",
        ability_major_category_name="通用能力",
        ability_sequence="1", ability_content="沟通能力",
    )
    session.add_all([analysis, task, item])
    session.flush()

    # Schema-canonical arg name is `major_name`. Executor still accepts
    # the historical `major` alias for hand-crafted tool_calls.
    result = query_ability_analysis(
        session=session,
        arguments={"major_name": "跨境电商",
                    "include": ["tasks", "ability_items"]},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert result["count"] == 1
    assert result["major_name"] == "跨境电商"
    a = result["analyses"][0]
    assert a["major_name"] == "跨境电商"
    assert len(a["tasks"]) == 1
    assert a["tasks"][0]["task_name"] == "订单管理"
    assert len(a["ability_items"]) == 1
    assert a["ability_items"][0]["ability_content"] == "沟通能力"


def test_query_ability_analysis_accepts_legacy_major_alias(session):
    """Guards the alias path — a hand-crafted / older tool_call that
    passes `major` instead of `major_name` should still resolve."""
    ref_id = _seed_normalized_ref(session, ref_id="ref-alias")
    profile = models.AbilityAnalysisProfile(
        id="prof-alias", model_code="PGSD", model_name="PGSD",
        schema_version="v1",
    )
    session.add(profile)
    session.flush()
    session.add(models.OccupationalAbilityAnalysis(
        id="a-alias", normalized_ref_id=ref_id, asset_version_id="ver-alias",
        profile_id=profile.id, analysis_model="PGSD",
        major_name="电子商务", schema_version="v1",
    ))
    session.flush()
    result = query_ability_analysis(
        session=session,
        arguments={"major": "电子商务"},  # legacy alias
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert result["count"] == 1
    assert result["major_name"] == "电子商务"


def test_query_ability_analysis_missing_major_returns_error_marker(session):
    """Neither key present → return a structured error marker so the
    dispatcher can surface it without crashing the request."""
    result = query_ability_analysis(
        session=session,
        arguments={},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert result["analyses"] == []
    assert "major_name" in result.get("error", "")


def test_query_ability_analysis_empty_result(session):
    result = query_ability_analysis(
        session=session,
        arguments={"major_name": "不存在"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert result["analyses"] == []


# ---------------------------------------------------------------------------
# get_job_demand_role_graph — B0.2 cross-dataset by job_title
# ---------------------------------------------------------------------------


def test_get_job_demand_role_graph_cross_dataset_merges_builds(session):
    """Two builds each carrying a JOB_ROLE with the same job_title
    substring — executor merges their subgraphs, dedups nodes/edges,
    and returns one chart covering the union."""
    from nexus_app.retrieval.tool_executors_v2 import get_job_demand_role_graph
    from nexus_app.capability_graph.whitelists import (
        BuildStatus, BuildType, EdgeType, NodeType,
    )

    ref_a = _seed_normalized_ref(session, ref_id="ref-a")
    ref_b = _seed_normalized_ref(session, ref_id="ref-b")
    ds_a = models.JobDemandDataset(
        id="jdd-a", normalized_ref_id=ref_a, asset_version_id="ver-a",
        source_channel="excel_upload", major_name="电子商务", schema_version="v1",
    )
    ds_b = models.JobDemandDataset(
        id="jdd-b", normalized_ref_id=ref_b, asset_version_id="ver-b",
        source_channel="excel_upload", major_name="市场营销", schema_version="v1",
    )
    build_a = models.CapabilityGraphStagingBuild(
        id="b-a", normalized_ref_id=ref_a, domain="job",
        build_type=BuildType.JOB_DEMAND, status=BuildStatus.GENERATED,
        schema_version="v1",
    )
    build_b = models.CapabilityGraphStagingBuild(
        id="b-b", normalized_ref_id=ref_b, domain="job",
        build_type=BuildType.JOB_DEMAND, status=BuildStatus.GENERATED,
        schema_version="v1",
    )
    role_a = models.CapabilityGraphStagingNode(
        id="role-a", build_id=build_a.id,
        node_type=NodeType.JOB_ROLE, node_key="role-a",
        display_name="AI销售专员",
    )
    role_b = models.CapabilityGraphStagingNode(
        id="role-b", build_id=build_b.id,
        node_type=NodeType.JOB_ROLE, node_key="role-b",
        display_name="AI销售专员",
    )
    skill_a = models.CapabilityGraphStagingNode(
        id="skill-a", build_id=build_a.id,
        node_type="Skill", node_key="skill-a",
        display_name="沟通能力",
    )
    edge_a = models.CapabilityGraphStagingEdge(
        id="e-a", build_id=build_a.id,
        source_node_id=role_a.id, target_node_id=skill_a.id,
        edge_type=EdgeType.JOB_ROLE_REQUIRES_SKILL,
    )
    session.add_all([ds_a, ds_b, build_a, build_b, role_a, role_b, skill_a, edge_a])
    session.flush()

    registry = ChartRegistry()
    result = get_job_demand_role_graph(
        session=session,
        arguments={"job_title": "AI销售"},
        tool_call_id="tc",
        chart_registry=registry,
    )
    assert result["found"] is True
    assert result["match_count"] == 2
    build_ids = {b["build_id"] for b in result["builds"]}
    assert build_ids == {"b-a", "b-b"}
    # Merged subgraph includes both role nodes + the one skill node.
    assert result["node_count"] == 3
    # Only one capability edge exists (skill on build_a).
    assert result["edge_count"] == 1
    # One chart registered for the union.
    assert result["chart_id"] in registry.registered_ids()


def test_get_job_demand_role_graph_returns_not_found_when_no_match(session):
    from nexus_app.retrieval.tool_executors_v2 import get_job_demand_role_graph
    result = get_job_demand_role_graph(
        session=session,
        arguments={"job_title": "不存在的岗位"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert result["found"] is False
    assert result["match_count"] == 0


# ---------------------------------------------------------------------------
# query_major_distribution
# ---------------------------------------------------------------------------


def test_query_major_distribution_filters_by_year_and_province(session):
    ref_id = _seed_normalized_ref(session)
    ds = models.MajorDistributionDataset(
        id="mdd-1", normalized_ref_id=ref_id, asset_version_id="ver-1",
        source_channel="excel", major_scope="scope",
        major_name="跨境电商", major_code="5301",
        year_min=2024, year_max=2024, schema_version="v1",
    )
    rec1 = models.MajorDistributionRecord(
        id="mr-1", dataset_id=ds.id, normalized_ref_id=ref_id,
        source_record_key="1", year=2024,
        province_name="上海", region_scope="华东",
        major_name="跨境电商", major_code="5301",
        distribution_count=10,
    )
    rec2 = models.MajorDistributionRecord(
        id="mr-2", dataset_id=ds.id, normalized_ref_id=ref_id,
        source_record_key="2", year=2023,
        province_name="上海", region_scope="华东",
        major_name="跨境电商", major_code="5301",
        distribution_count=8,
    )
    session.add_all([ds, rec1, rec2])
    session.flush()

    result = query_major_distribution(
        session=session,
        arguments={"major_name": "跨境电商", "year": 2024, "province_name": "上海"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert result["count"] == 1
    assert result["records"][0]["year"] == 2024


# ---------------------------------------------------------------------------
# get_outline_subtree
# ---------------------------------------------------------------------------


def test_get_outline_subtree_bfs_expansion(session):
    ref_id = _seed_normalized_ref(session)
    build_run_id = "br-1"
    root = models.KnowledgeOutlineNode(
        id="o-root", normalized_ref_id=ref_id, parent_id=None,
        level=0, order_index=0, title="Book", build_run_id=build_run_id,
    )
    l1 = models.KnowledgeOutlineNode(
        id="o-l1", normalized_ref_id=ref_id, parent_id=root.id,
        level=1, order_index=0, title="Chapter 1", build_run_id=build_run_id,
    )
    l2 = models.KnowledgeOutlineNode(
        id="o-l2", normalized_ref_id=ref_id, parent_id=l1.id,
        level=2, order_index=0, title="Section 1.1", build_run_id=build_run_id,
    )
    session.add_all([root, l1, l2])
    session.flush()

    result = get_outline_subtree(
        session=session,
        arguments={"node_id": root.id},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert result["root_id"] == root.id
    assert result["node_count"] == 3
    ids = {n["id"] for n in result["nodes"]}
    assert ids == {root.id, l1.id, l2.id}

    # Schema-driven max_depth honoured: depth=1 keeps root + one BFS
    # layer only (root + l1, drops l2 grandchild).
    shallow = get_outline_subtree(
        session=session,
        arguments={"node_id": root.id, "max_depth": 1},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert shallow["node_count"] == 2
    assert {n["id"] for n in shallow["nodes"]} == {root.id, l1.id}
    assert shallow["effective_depth"] == 1


def test_get_outline_subtree_missing_node(session):
    result = get_outline_subtree(
        session=session,
        arguments={"node_id": "does-not-exist"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )
    assert result["found"] is False
