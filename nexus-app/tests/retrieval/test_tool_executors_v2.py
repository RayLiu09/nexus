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
    query_major_information,
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
        "internal.query_major_information",
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
# query_major_information
# ---------------------------------------------------------------------------


def test_query_major_information_prefers_profile_and_uses_per_unit_chunk_fallback(session):
    profile = models.MajorProfile(
        id="profile-major", normalized_ref_id="ref-profile", asset_version_id="version-profile",
        domain_profile="major_profile.v1", major_name="网络营销与直播电商", major_code="530704",
        education_level="高职", basic_study_duration="三年", training_goal="培养直播电商运营人才",
        extractor_version="test", evidence={"source_block_ids": ["block-profile"]},
    )
    occupation = models.MajorProfileOccupation(
        id="occupation-major", profile_id=profile.id, normalized_ref_id=profile.normalized_ref_id,
        item_index=1, text="互联网营销专业人员", normalized_name="互联网营销专业人员",
        occupation_type="职业", evidence_block_ids=["block-occupation"], locator={"page_start": 2},
    )
    fallback = _chunk(
        "chunk-admission", "ref-standard", 1,
        "网络营销与直播电商专业入学基本要求为普通高中毕业生。",
        heading_path=[{"title": "入学基本要求"}],
    )
    fallback.knowledge_type_code = "course_standard_authoring_process"
    fallback.locator = {"heading_path": [{"title": "入学基本要求"}], "page_start": 3}
    session.add_all([profile, occupation, fallback])
    session.flush()

    result = query_major_information(
        session=session,
        arguments={
            "major_name": "网络营销与直播电商",
            "units": ["basic_identity", "occupation_oriented", "admission_requirements"],
        },
        tool_call_id="tc", chart_registry=ChartRegistry(),
    )

    assert result["found_profile"] is True
    assert result["units"]["basic_identity"]["status"] == "structured"
    assert result["units"]["basic_identity"]["value"]["major_code"] == "530704"
    assert result["units"]["occupation_oriented"]["status"] == "structured"
    assert result["units"]["admission_requirements"]["status"] == "chunk_fallback"
    evidence = result["units"]["admission_requirements"]["evidence"]
    assert evidence[0]["chunk_id"] == fallback.id
    assert evidence[0]["knowledge_type_code"] == "course_standard_authoring_process"
    assert evidence[0]["locator"]["page_start"] == 3


def test_query_major_information_does_not_use_chunks_when_structured_unit_exists(session):
    profile = models.MajorProfile(
        id="profile-goal", normalized_ref_id="ref-profile", asset_version_id="version-profile",
        domain_profile="major_profile.v1", major_name="网络营销与直播电商", major_code="530704",
        training_goal="结构化培养目标", extractor_version="test", evidence={},
    )
    fallback = _chunk(
        "chunk-goal", "ref-standard", 1, "网络营销与直播电商培养目标。",
        heading_path=[{"title": "培养目标"}],
    )
    fallback.knowledge_type_code = "course_standard_authoring_process"
    session.add_all([profile, fallback])
    session.flush()

    result = query_major_information(
        session=session,
        arguments={"major_name": "网络营销与直播电商", "units": ["training_goal"]},
        tool_call_id="tc", chart_registry=ChartRegistry(),
    )

    assert result["units"]["training_goal"]["status"] == "structured"
    assert result["units"]["training_goal"]["value"] == "结构化培养目标"
    assert result["missing_structured_units"] == []


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


def test_search_chunks_builds_compact_answer_context_for_definition_method_query(session):
    root = models.KnowledgeOutlineNode(
        id="wb-root", normalized_ref_id="ref-wb", parent_id=None,
        level=0, order_index=0, title="教材", build_run_id="build-1",
        chunk_count=0, fallback_used=False, node_metadata={},
    )
    section = models.KnowledgeOutlineNode(
        id="wb-section", normalized_ref_id="ref-wb", parent_id=root.id,
        level=1, order_index=1, title="六、白平衡", build_run_id="build-1",
        chunk_count=5, fallback_used=False, node_metadata={},
    )
    definition = _chunk(
        "wb-definition", "ref-wb", 1,
        "白平衡是让不同光源下的白色物体还原为白色，用来校正色偏。",
        outline_id=section.id,
    )
    methods = _chunk(
        "wb-methods", "ref-wb", 2,
        "调节白平衡有三种方式：预置白平衡、手动调节白平衡和自动调节白平衡。",
        outline_id=section.id,
    )
    color_temperature = _chunk(
        "wb-temperature", "ref-wb", 3,
        "手动调节白平衡时可设置色温，色温值越高画面越偏黄，越低越偏蓝。",
        outline_id=section.id,
    )
    task_intro = _chunk(
        "task-intro", "ref-wb", 4,
        "任务实施：小李决定使用专业模式，手动设置测光方式、感光度、曝光补偿、对焦方式、白平衡等参数。其具体操作步骤如下。",
        outline_id=section.id,
    )
    sibling = _chunk(
        "iso-sibling", "ref-wb", 5,
        "步骤二：设置感光度。点击 ISO 按钮后拖动滑块选择合适数值。",
        outline_id=section.id,
    )
    exercise = _chunk(
        "exercise", "ref-wb", 6,
        "单项选择题：使用智能手机拍摄短视频的优点不包括什么？",
        outline_id=section.id,
    )
    session.add_all([root, section, definition, methods, color_temperature, task_intro, sibling, exercise])
    session.flush()

    class _Adapter:
        def search(self, *_args, **_kwargs):
            return [{
                "nexus_chunk_id": definition.id,
                "normalized_ref_id": "ref-wb",
                "score": 0.96,
            }]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session,
        arguments={"query": "什么是白平衡，如何调节"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )

    answer_context = result["answer_contexts"][0]
    assert answer_context["kind"] == "answer_span_context"
    assert answer_context["question_type"] == "definition_with_method"
    selected_ids = [item["chunk_id"] for item in answer_context["chunks"]]
    assert definition.id in selected_ids
    assert methods.id in selected_ids
    assert color_temperature.id in selected_ids
    assert task_intro.id not in selected_ids
    assert sibling.id not in selected_ids
    assert exercise.id not in selected_ids
    section_context = result["answer_contexts"][1]
    assert section_context["kind"] == "section_context"
    assert section_context["mode"] == "compact_answer"


def test_search_chunks_expands_top_three_distinct_hit_sections_with_full_content(session):
    root = models.KnowledgeOutlineNode(
        id="ranked-root", normalized_ref_id="ref-ranked", parent_id=None,
        level=0, order_index=0, title="教材", build_run_id="build-1",
        chunk_count=0, fallback_used=False, node_metadata={},
    )
    sections = [
        models.KnowledgeOutlineNode(
            id=f"ranked-section-{index}", normalized_ref_id="ref-ranked",
            parent_id=root.id, level=1, order_index=index,
            title=f"第{index}章", build_run_id="build-1", chunk_count=2,
            fallback_used=False, node_metadata={},
        )
        for index in range(1, 5)
    ]
    session.add_all([root, *sections])
    chunks = []
    for index, section in enumerate(sections, start=1):
        chunks.extend([
            _chunk(
                f"ranked-{index}-a", "ref-ranked", index * 10,
                f"第{index}章第一段完整内容", outline_id=section.id,
            ),
            _chunk(
                f"ranked-{index}-b", "ref-ranked", index * 10 + 1,
                f"第{index}章第二段完整内容", outline_id=section.id,
            ),
        ])
    session.add_all(chunks)
    session.flush()

    class _Adapter:
        def search(self, *_args, **_kwargs):
            # The second hit repeats section 1; the fourth section must be
            # excluded by the three-section response cap.
            return [
                {"nexus_chunk_id": chunks[0].id, "normalized_ref_id": "ref-ranked"},
                {"nexus_chunk_id": chunks[1].id, "normalized_ref_id": "ref-ranked"},
                {"nexus_chunk_id": chunks[2].id, "normalized_ref_id": "ref-ranked"},
                {"nexus_chunk_id": chunks[4].id, "normalized_ref_id": "ref-ranked"},
                {"nexus_chunk_id": chunks[6].id, "normalized_ref_id": "ref-ranked"},
            ]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session, arguments={"query": "用户的语义问题不包含章节标题"},
        tool_call_id="tc", chart_registry=ChartRegistry(),
    )

    contexts = result["answer_contexts"]
    assert [context["outline_node_id"] for context in contexts] == [
        sections[0].id, sections[1].id, sections[2].id,
    ]
    assert all(context["complete"] is True for context in contexts)
    assert [context["total_chunk_count"] for context in contexts] == [2, 2, 2]
    assert [
        [item["chunk_id"] for item in context["chunks"]]
        for context in contexts
    ] == [
        [chunks[0].id, chunks[1].id],
        [chunks[2].id, chunks[3].id],
        [chunks[4].id, chunks[5].id],
    ]


def test_search_chunks_auto_scopes_numbered_section_topic(session):
    """Chapter ordinals must not hide an otherwise exact topic match."""
    root = models.KnowledgeOutlineNode(
        id="numbered-root", normalized_ref_id="ref-numbered", parent_id=None,
        level=0, order_index=0, title="教材", build_run_id="build-1",
        chunk_count=0, fallback_used=False, node_metadata={},
    )
    target = models.KnowledgeOutlineNode(
        id="numbered-target", normalized_ref_id="ref-numbered", parent_id=root.id,
        level=1, order_index=1, title="一、拍摄设备", build_run_id="build-1",
        chunk_count=1, fallback_used=False, node_metadata={},
    )
    other = models.KnowledgeOutlineNode(
        id="numbered-other", normalized_ref_id="ref-numbered", parent_id=root.id,
        level=1, order_index=2, title="五、其他设备", build_run_id="build-1",
        chunk_count=1, fallback_used=False, node_metadata={},
    )
    target_chunk = _chunk(
        "numbered-target-chunk", "ref-numbered", 1, "智能手机和摄像机是常用拍摄设备。",
        outline_id=target.id, heading_path=[{"title": "一、拍摄设备"}],
    )
    other_chunk = _chunk(
        "numbered-other-chunk", "ref-numbered", 2, "摇臂和监视器属于其他设备。",
        outline_id=other.id, heading_path=[{"title": "五、其他设备"}],
    )
    session.add_all([root, target, other, target_chunk, other_chunk])
    session.flush()
    calls: list[dict] = []

    class _Adapter:
        def search(self, *_args, **kwargs):
            calls.append(kwargs)
            return [{"nexus_chunk_id": target_chunk.id, "score": 0.8}]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session, arguments={"query": "短视频拍摄设备有哪些"},
        tool_call_id="tc", chart_registry=ChartRegistry(),
    )

    assert calls[0]["chunk_ids"] == [target_chunk.id]
    assert result["scope"]["node_id"] == target.id
    assert [context["outline_node_id"] for context in result["answer_contexts"]] == [target.id]


def test_search_chunks_reranks_sections_over_prompt_like_first_hit(session):
    """Reranking selects relevant sections; display preserves document order."""
    root = models.KnowledgeOutlineNode(
        id="rerank-root", normalized_ref_id="ref-rerank", parent_id=None,
        level=0, order_index=0, title="教材", build_run_id="build-1",
        chunk_count=0, fallback_used=False, node_metadata={},
    )
    prompt_section = models.KnowledgeOutlineNode(
        id="rerank-prompt", normalized_ref_id="ref-rerank", parent_id=root.id,
        level=1, order_index=1, title="其他设备", build_run_id="build-1",
        chunk_count=1, fallback_used=False, node_metadata={},
    )
    answer_section = models.KnowledgeOutlineNode(
        id="rerank-answer", normalized_ref_id="ref-rerank", parent_id=root.id,
        level=1, order_index=2, title="一、拍摄设备", build_run_id="build-1",
        chunk_count=1, fallback_used=False, node_metadata={},
    )
    prompt_chunk = _chunk(
        "rerank-prompt-chunk", "ref-rerank", 1, "拍摄短视频时，还会用到哪些常见设备？",
        outline_id=prompt_section.id,
    )
    answer_chunk = _chunk(
        "rerank-answer-chunk", "ref-rerank", 2, "常用拍摄设备包括智能手机、单反相机和摄像机。",
        outline_id=answer_section.id,
    )
    session.add_all([root, prompt_section, answer_section, prompt_chunk, answer_chunk])
    session.flush()

    class _Adapter:
        def search(self, *_args, **_kwargs):
            return [
                {"nexus_chunk_id": prompt_chunk.id, "score": 0.90},
                {"nexus_chunk_id": answer_chunk.id, "score": 0.80},
            ]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session,
        # A non-textbook KB disables automatic scope so this exercises the
        # post-retrieval section reranker directly. Selected contexts are then
        # displayed in document order.
        arguments={"query": "短视频拍摄设备有哪些", "kb": "industry_research_kb"},
        tool_call_id="tc", chart_registry=ChartRegistry(),
    )

    assert [context["outline_node_id"] for context in result["answer_contexts"]] == [
        prompt_section.id, answer_section.id,
    ]
    assert result["answer_contexts"][0]["selection_reason"] == "section_relevance_rerank"


def test_search_chunks_reranks_sections_by_query_core_title_match(session):
    """A strong title/core-term match outranks a content-only dialogue hit."""
    root = models.KnowledgeOutlineNode(
        id="retail-root", normalized_ref_id="ref-retail", parent_id=None,
        level=0, order_index=0, title="现代零售行业的关键特征",
        build_run_id="build-1", chunk_count=0, fallback_used=False,
        node_metadata={},
    )
    dialogue_section = models.KnowledgeOutlineNode(
        id="retail-dialogue", normalized_ref_id="ref-retail", parent_id=root.id,
        level=1, order_index=1, title="门店互动", build_run_id="build-1",
        chunk_count=1, fallback_used=False, node_metadata={},
    )
    answer_section = models.KnowledgeOutlineNode(
        id="retail-answer", normalized_ref_id="ref-retail", parent_id=root.id,
        level=1, order_index=2, title="知识点1：现代零售行业的四大关键特征",
        build_run_id="build-1", chunk_count=2, fallback_used=False,
        node_metadata={},
    )
    dialogue = _chunk(
        "retail-dialogue-chunk", "ref-retail", 10,
        "老师：小优，我们已经掌握了现代零售行业的关键特征，那接下来我们该如何做呢？",
        outline_id=dialogue_section.id,
    )
    intro = _chunk(
        "retail-answer-intro", "ref-retail", 3,
        "现代零售以数字化为基础，以用户为中心，以全渠道融合为核心，提供即时化服务，其核心具备四大关键特征。",
        outline_id=answer_section.id,
    )
    feature = _chunk(
        "retail-answer-feature", "ref-retail", 4,
        "首先是全渠道深度融合。现代零售打破线上线下渠道壁垒，实现线上引流、线下体验、即时履约、全域复购。",
        outline_id=answer_section.id,
    )
    session.add_all([root, dialogue_section, answer_section, dialogue, intro, feature])
    session.flush()

    class _Adapter:
        def search(self, *_args, **_kwargs):
            return [
                {"nexus_chunk_id": dialogue.id, "normalized_ref_id": "ref-retail", "score": 0.99},
                {"nexus_chunk_id": intro.id, "normalized_ref_id": "ref-retail", "score": 0.75},
            ]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session,
        arguments={"query": "现代零售行业的关键特征是什么", "kb": "industry_research_kb"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )

    section_contexts = [
        context for context in result["answer_contexts"]
        if context["kind"] == "section_context"
    ]
    assert [context["outline_node_id"] for context in section_contexts[:2]] == [
        dialogue_section.id,
        answer_section.id,
    ]
    assert [item["chunk_id"] for item in section_contexts[1]["chunks"]] == [
        intro.id,
        feature.id,
    ]


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
    # The full chapter-context contract returns every chunk linked to the
    # stored outline node. Heading-path filtering remains limited to the
    # candidate scope used before vector ranking.
    assert [item["chunk_id"] for item in result["answer_contexts"][0]["chunks"]] == [
        chunk.id, stale_chunk.id,
    ]


def test_search_chunks_builds_document_section_context_for_industry_report(session):
    intro = _industry_chunk(
        "report-intro", "ref-report", 1, "直播电商市场规模持续增长。",
        heading_path=[{"level": 1, "title": "一、行业概况"}],
    )
    policy = _industry_chunk(
        "report-policy", "ref-report", 2, "监管政策要求平台强化主体责任。",
        heading_path=[{"level": 1, "title": "二、监管政策演进"}],
    )
    policy_table = _industry_chunk(
        "report-policy-table", "ref-report", 3, "政策名称：网络交易监督管理办法。",
        heading_path=[{"level": 1, "title": "二、监管政策演进"}],
    )
    trend = _industry_chunk(
        "report-trend", "ref-report", 4, "直播电商进入精细化运营阶段。",
        heading_path=[{"level": 1, "title": "三、发展趋势"}],
    )
    session.add_all([intro, policy, policy_table, trend])
    session.flush()

    class _Adapter:
        def search(self, *_args, **_kwargs):
            return [
                {
                    "nexus_chunk_id": policy.id,
                    "normalized_ref_id": policy.normalized_ref_id,
                    "score": 0.82,
                }
            ]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session,
        arguments={"query": "直播电商监管政策演进", "kb": "industry_research_kb"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )

    context = result["answer_contexts"][0]
    assert context["kind"] == "document_section_context"
    assert context["selection_reason"] == "document_section_relevance_rerank"
    assert context["title"] == "二、监管政策演进"
    assert context["section_type"] == "chapter"
    assert context["complete"] is True
    assert context["partial"] is False
    assert [item["chunk_id"] for item in context["chunks"]] == [
        policy.id, policy_table.id,
    ]


def test_document_section_contexts_display_in_document_order_after_ranking(session):
    overview = _industry_chunk(
        "report-overview", "ref-report-order", 1, "跨境电商总体保持增长。",
        heading_path=[{"level": 1, "title": "一、行业概况"}],
    )
    supply_chain = _industry_chunk(
        "report-supply-chain", "ref-report-order", 2, "海外仓提升供应链履约效率。",
        heading_path=[{"level": 1, "title": "二、供应链建设"}],
    )
    trend = _industry_chunk(
        "report-trend", "ref-report-order", 3, "跨境电商趋势包括品牌化和本地化。",
        heading_path=[{"level": 1, "title": "三、发展趋势"}],
    )
    session.add_all([overview, supply_chain, trend])
    session.flush()

    class _Adapter:
        def search(self, *_args, **_kwargs):
            return [
                {
                    "nexus_chunk_id": trend.id,
                    "normalized_ref_id": trend.normalized_ref_id,
                    "score": 0.93,
                },
                {
                    "nexus_chunk_id": supply_chain.id,
                    "normalized_ref_id": supply_chain.normalized_ref_id,
                    "score": 0.9,
                },
            ]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session,
        arguments={"query": "跨境电商供应链和发展趋势", "kb": "industry_research_kb"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )

    contexts = [
        context for context in result["answer_contexts"]
        if context["kind"] == "document_section_context"
    ]
    assert [context["title"] for context in contexts] == [
        "二、供应链建设",
        "三、发展趋势",
    ]


def test_document_section_context_marks_partial_missing_heading_path(session):
    headed = _industry_chunk(
        "report-headed", "ref-partial", 1, "跨境电商供应链持续优化。",
        heading_path=[{"level": 2, "title": "供应链趋势"}],
    )
    missing = _industry_chunk(
        "report-missing", "ref-partial", 2, "海外仓履约效率提升。",
        heading_path=[],
    )
    session.add_all([headed, missing])
    session.flush()

    class _Adapter:
        def search(self, *_args, **_kwargs):
            return [{
                "nexus_chunk_id": headed.id,
                "normalized_ref_id": headed.normalized_ref_id,
                "score": 0.8,
            }]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session,
        arguments={"query": "跨境电商供应链趋势是什么", "kb": "industry_research_kb"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )

    context = result["answer_contexts"][0]
    assert context["kind"] == "document_section_context"
    assert context["query_intent"] == "section_summary"
    assert context["title"] == "供应链趋势"
    assert context["partial"] is True
    assert "missing_heading_path" in context["quality_flags"]
    assert [item["chunk_id"] for item in context["chunks"]] == [
        headed.id, missing.id,
    ]


def test_document_section_context_not_returned_for_exact_fact_query(session):
    metric = _industry_chunk(
        "report-metric", "ref-exact", 1, "2024年网络零售额为15.5万亿元。",
        heading_path=[{"level": 1, "title": "一、网络零售规模"}],
    )
    sibling = _industry_chunk(
        "report-metric-sibling", "ref-exact", 2, "实物商品网上零售额保持增长。",
        heading_path=[{"level": 1, "title": "一、网络零售规模"}],
    )
    session.add_all([metric, sibling])
    session.flush()

    class _Adapter:
        def search(self, *_args, **_kwargs):
            return [{
                "nexus_chunk_id": metric.id,
                "normalized_ref_id": metric.normalized_ref_id,
                "score": 0.91,
            }]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session,
        arguments={"query": "2024年网络零售额是多少", "kb": "industry_research_kb"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )

    assert [
        context for context in result["answer_contexts"]
        if context["kind"] == "document_section_context"
    ] == []


def test_document_section_context_not_returned_for_existence_locator_query(session):
    chunk = _industry_chunk(
        "report-locator", "ref-locator", 1, "报告提到海外仓能够改善跨境履约效率。",
        heading_path=[{"level": 1, "title": "一、海外仓建设"}],
    )
    session.add(chunk)
    session.flush()

    class _Adapter:
        def search(self, *_args, **_kwargs):
            return [{
                "nexus_chunk_id": chunk.id,
                "normalized_ref_id": chunk.normalized_ref_id,
                "score": 0.88,
            }]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session,
        arguments={"query": "报告是否提到海外仓", "kb": "industry_research_kb"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )

    assert result["answer_contexts"] == []


def test_document_section_context_not_returned_for_asset_discovery_query(session):
    chunk = _industry_chunk(
        "report-discovery", "ref-discovery", 1, "跨境电商报告分析了海外仓趋势。",
        heading_path=[{"level": 1, "title": "一、报告概况"}],
    )
    session.add(chunk)
    session.flush()

    class _Adapter:
        def search(self, *_args, **_kwargs):
            return [{
                "nexus_chunk_id": chunk.id,
                "normalized_ref_id": chunk.normalized_ref_id,
                "score": 0.86,
            }]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session,
        arguments={"query": "找一下跨境电商相关报告", "kb": "industry_research_kb"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )

    assert result["answer_contexts"] == []


def test_document_section_context_not_returned_for_comparison_query(session):
    chunk = _industry_chunk(
        "report-comparison", "ref-comparison", 1, "2024年报告认为跨境电商更加重视品牌化。",
        heading_path=[{"level": 1, "title": "一、跨境电商发展判断"}],
    )
    session.add(chunk)
    session.flush()

    class _Adapter:
        def search(self, *_args, **_kwargs):
            return [{
                "nexus_chunk_id": chunk.id,
                "normalized_ref_id": chunk.normalized_ref_id,
                "score": 0.89,
            }]

    from nexus_app.retrieval.tool_executors_v2 import make_search_chunks_executor
    result = make_search_chunks_executor(_Adapter())(
        session=session,
        arguments={"query": "2022和2024跨境电商判断有什么不同", "kb": "industry_research_kb"},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )

    assert result["answer_contexts"] == []


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


def _industry_chunk(chunk_id, ref_id, index, content, *, heading_path):
    return models.KnowledgeChunk(
        id=chunk_id,
        normalized_ref_id=ref_id,
        knowledge_type_code="industry_research_kb",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=index,
        content=content,
        chunk_metadata={},
        embedding_status=EmbeddingStatus.EMBEDDED,
        source_block_ids=[f"block-{chunk_id}"],
        locator={"heading_path": heading_path, "page_start": index, "page_end": index},
        knowledge_outline_node_id=None,
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
        major_name=None, schema_version="v1",
    )
    rec1 = models.JobDemandRecord(
        id="r-1", dataset_id=ds.id, normalized_ref_id=ref_id,
        source_record_key="k1", job_title="跨境电商运营", city="上海",
        industry_name="电子商务", record_fingerprint="abc1",
    )
    rec2 = models.JobDemandRecord(
        id="r-2", dataset_id=ds.id, normalized_ref_id=ref_id,
        source_record_key="k2", job_title="电商推广", city="杭州",
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
    assert result["record_count"] == 2
    assert result["total_record_count"] == 2
    assert result["job_count_sum"] == 0
    dist = result["aggregations"]["industry_distribution"]
    # 电子商务 has 2 records, 教育 has 1 — desc order.
    assert dist[0] == {"industry_name": "电子商务", "count": 2}
    assert "教育" not in {row["industry_name"] for row in dist}
    assert result["matched_terms"] == ["跨境电商", "跨境", "外贸", "电商"]


def test_query_job_demand_relaxes_year_when_records_are_undated(session):
    ref_id = _seed_normalized_ref(session, ref_id="ref-year-relax")
    ds = models.JobDemandDataset(
        id="jdd-year-relax", normalized_ref_id=ref_id, asset_version_id="ver-year",
        source_channel="excel_upload", major_name=None, schema_version="v1",
    )
    session.add_all([
        ds,
        models.JobDemandRecord(
            id="r-year-1", dataset_id=ds.id, normalized_ref_id=ref_id,
            source_record_key="k1", job_title="电子商务运营", city="杭州滨江区",
            industry_name="电子商务", record_fingerprint="fp-year-1",
        ),
    ])
    session.flush()

    result = query_job_demand(
        session=session,
        arguments={"major": "电子商务", "province_name": "浙江省", "year": 2026},
        tool_call_id="tc",
        chart_registry=ChartRegistry(),
    )

    assert result["total_record_count"] == 1
    assert result["data_limitations"]["year_filter_requires_source_published_at"] is True
    assert result["data_limitations"]["year_filter_relaxed_due_to_missing_source_published_at"] is True


def test_query_job_demand_suppresses_distribution_when_fields_omit(session):
    ds = models.JobDemandDataset(
        id="jdd-2", normalized_ref_id="ref-suppress", asset_version_id="ver-2",
        source_channel="excel_upload",
        major_name=None, schema_version="v1",
    )
    session.add(ds)
    session.add(models.JobDemandRecord(
        id="r-9", dataset_id=ds.id, normalized_ref_id="ref-suppress",
        source_record_key="k1", job_title="跨境电商运营", record_fingerprint="fp",
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
    assert {node["display_name"] for node in result["graph_nodes"]} == {
        "AI销售专员", "沟通能力",
    }
    assert result["graph_edges"][0]["target_name"] == "沟通能力"
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
        province_name="上海市", region_scope="华东",
        major_name="跨境电商", major_code="5301",
        distribution_count=10,
    )
    rec2 = models.MajorDistributionRecord(
        id="mr-2", dataset_id=ds.id, normalized_ref_id=ref_id,
        source_record_key="2", year=2023,
        province_name="上海市", region_scope="华东",
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
    assert result["records"][0]["province_name"] == "上海市"


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
