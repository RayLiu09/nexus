from __future__ import annotations

from nexus_app.task_outline.detector import detect_course_textbook_subtype
from nexus_app.task_outline.extractor import extract_course_textbook_outline


def _block(block_id: str, block_type: str, text: str, page: int) -> dict:
    idx = int("".join(ch for ch in block_id if ch.isdigit()) or "1")
    return {
        "block_id": block_id,
        "block_type": block_type,
        "text": text,
        "page": page,
        "bbox": [72.0, 100.0 + idx, 520.0, 130.0 + idx],
        "md_char_range": [idx * 100, idx * 100 + len(text)],
    }


def _training_blocks() -> list[dict]:
    return [
        _block("b1", "heading", "项目一 基础数据采集", 10),
        _block("b2", "heading", "任务一 市场数据采集", 11),
        _block("b3", "paragraph", "任务目标：能够根据需求确定数据采集渠道并设计采集指标。", 11),
        _block("b4", "paragraph", "任务背景：企业需要对智能门锁市场数据进行采集和分析。", 12),
        _block("b5", "paragraph", "任务分析：需要明确采集渠道、采集指标和采集表结构。", 12),
        _block("b6", "paragraph", "任务实施", 13),
        _block("b7", "paragraph", "1. 确定采集渠道，选择电商平台和关键词。", 13),
        _block("b8", "paragraph", "2. 明确采集指标，包括商品名称、链接、价格、月销量。", 14),
        _block("b9", "paragraph", "3. 制作关键词搜索指数月均值数据采集表。", 14),
        _block("b10", "table", "图1-2 智能门锁竞争数据采集表\n商品名称 | 链接 | 价格 | 月销量", 15),
        _block("b11", "paragraph", "任务思考：如何保证采集数据合法合规？", 16),
    ]


def _theory_blocks() -> list[dict]:
    return [
        _block("t1", "heading", "第一章 电子商务数据分析基础", 1),
        _block("t2", "heading", "第一节 数据分析的概念", 2),
        _block("t3", "paragraph", "数据分析是指运用统计方法对数据进行整理、解释和建模的过程。", 2),
        _block("t4", "paragraph", "其基本原理包括数据采集、数据清洗、指标体系构建和结果解释。", 3),
        _block("t5", "paragraph", "影响因素包括数据质量、业务场景、分析模型和组织机制。", 3),
        _block("t6", "paragraph", "常见分类包括描述性分析、诊断性分析和预测性分析。", 4),
    ]


def _hybrid_blocks() -> list[dict]:
    return [
        *_theory_blocks(),
        _block("h1", "heading", "项目一 基础数据采集", 10),
        _block("h2", "heading", "任务一 市场数据采集", 11),
        _block("h3", "paragraph", "任务目标：能够设计采集指标。", 11),
        _block("h4", "paragraph", "任务实施", 12),
        _block("h5", "paragraph", "1. 确定采集渠道。", 12),
    ]


def test_detects_training_operation_textbook() -> None:
    result = detect_course_textbook_subtype(_training_blocks())

    assert result.textbook_subtype == "training_operation"
    assert result.processing_profile == "task_outline"
    assert result.evidence_graph_admission == "not_recommended"
    assert result.subtype_confidence >= 0.7
    assert "存在明确任务标题" in result.subtype_evidence
    assert result.source_block_ids


def test_detects_theory_knowledge_textbook() -> None:
    result = detect_course_textbook_subtype(_theory_blocks())

    assert result.textbook_subtype == "theory_knowledge"
    assert result.processing_profile == "evidence_graph"
    assert result.evidence_graph_admission == "recommended"
    assert result.subtype_confidence >= 0.65


def test_detects_hybrid_when_theory_and_task_signals_coexist() -> None:
    result = detect_course_textbook_subtype(_hybrid_blocks())

    assert result.textbook_subtype in {"hybrid", "training_operation"}
    assert result.processing_profile in {"hybrid", "task_outline"}
    assert result.scores["task_score"] > 0
    assert result.scores["theory_score"] > 0


def test_extracts_minimal_task_outline_for_training_textbook() -> None:
    blocks = _training_blocks()
    extraction = extract_course_textbook_outline(
        normalized_ref_id="ref-training",
        asset_version_id="ver-training",
        title="电子商务数据分析实践",
        blocks=blocks,
    )

    assert extraction.profile.textbook_subtype == "training_operation"
    assert extraction.profile.processing_profile == "task_outline"
    assert extraction.profile.task_profile == "textbook_training_operation"
    assert extraction.profile.evidence_graph_admission == "not_recommended"
    assert extraction.nodes

    by_type: dict[str, list] = {}
    for node in extraction.nodes:
        by_type.setdefault(node.node_type, []).append(node)

    assert by_type["project"][0].title == "项目一 基础数据采集"
    assert by_type["task"][0].title == "任务一 市场数据采集"
    assert {node.section_type for node in by_type["task_section"]} >= {
        "task_objective",
        "task_background",
        "task_analysis",
        "operation_steps",
        "task_reflection",
    }
    assert [node.metadata["step_no"] for node in by_type["operation_step"]] == [1, 2, 3]
    assert by_type["task_artifact"][0].title.startswith("图1-2")

    high_value = [
        node for node in extraction.nodes
        if node.node_type in {"task", "task_section", "operation_step", "task_artifact"}
    ]
    assert all(node.source_block_ids for node in high_value)
    assert all(node.locator is not None for node in high_value)
    assert by_type["operation_step"][0].locator["page_start"] == 13
    assert by_type["operation_step"][0].locator["bbox_union"] is not None

    quality = extraction.quality
    assert quality["task_count"] == 1
    assert quality["operation_step_count"] == 3
    assert quality["artifact_count"] == 1
    assert quality["locator_coverage"] == 1.0
    assert quality["chunk_projection_coverage"] == 1.0
    assert quality["artifact_binding_rate"] == 1.0
    assert quality["orphan_block_ratio"] < 0.3


def test_theory_textbook_does_not_generate_outline_nodes() -> None:
    extraction = extract_course_textbook_outline(
        normalized_ref_id="ref-theory",
        asset_version_id="ver-theory",
        title="电子商务数据分析基础",
        blocks=_theory_blocks(),
    )

    assert extraction.profile.textbook_subtype == "theory_knowledge"
    assert extraction.profile.processing_profile == "evidence_graph"
    assert extraction.nodes == []
    assert extraction.quality["task_count"] == 0

