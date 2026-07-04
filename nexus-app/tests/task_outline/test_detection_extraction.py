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


def _body_markdown_with_ranges(blocks: list[dict], overrides: dict[str, str] | None = None) -> str:
    overrides = overrides or {}
    parts: list[str] = []
    cursor = 0
    for block in blocks:
        if parts:
            cursor += 2
        part = overrides.get(block["block_id"], block["text"])
        parts.append(part)
        block["md_char_range"] = [cursor, cursor + len(part)]
        cursor += len(part)
    return "\n\n".join(parts)


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


def _projectized_theory_with_practice_blocks() -> list[dict]:
    return [
        _block("v1", "heading", "项目一 短视频认知", 1),
        _block("v2", "heading", "学习目标", 1),
        _block("v3", "paragraph", "掌握短视频的概念、特征、类型及平台传播机制。", 1),
        _block("v4", "heading", "知识准备", 2),
        _block("v5", "paragraph", "短视频是依托移动互联网平台传播的视频内容形态，其定义、分类和运营原理需要结合平台规则理解。", 2),
        _block("v6", "paragraph", "讲解类短视频、知识类短视频和剧情类短视频在内容结构、受众心理和传播机制方面存在差异。", 3),
        _block("v7", "heading", "任务实施", 4),
        _block("v8", "paragraph", "1. 分析不同主题类型短视频的特点。", 4),
        _block("v9", "paragraph", "2. 填写短视频主题类型分析表。", 4),
        _block("v10", "table", "| 短视频主题类型 | 分析内容 |\n| --- | --- |\n| 知识类短视频 |  |", 5),
        _block("v11", "heading", "项目二 短视频账号创建与矩阵搭建", 6),
        _block("v12", "heading", "学习目标", 6),
        _block("v13", "paragraph", "理解短视频账号定位的作用、原则、方法和账号矩阵的基础概念。", 6),
        _block("v14", "heading", "知识准备", 7),
        _block("v15", "paragraph", "账号定位体现内容领域、受众定位和账号差异化原则，是短视频运营的基础知识。", 7),
        _block("v16", "heading", "任务实施", 8),
        _block("v17", "paragraph", "1. 根据案例完成账号领域定位。", 8),
        _block("v18", "paragraph", "2. 设计账号名称、头像和简介。", 8),
        _block("v19", "heading", "任务思考", 9),
        _block("v20", "paragraph", "请结合所学知识说明短视频账号定位为什么要避免同质化。", 9),
    ]


def _work_task_textbook_blocks() -> list[dict]:
    return [
        _block("w1", "heading", "工作领域一 基础数据采集", 1),
        _block("w2", "heading", "工作任务一 市场数据采集", 2),
        _block("w3", "heading", "任务目标", 2),
        _block("w4", "paragraph", "能够完成市场数据指标体系设计。", 2),
        _block("w5", "heading", "任务导图", 2),
        _block("w6", "heading", "工作子任务一 市场行情数据采集", 3),
        _block("w7", "heading", "任务背景", 3),
        _block("w8", "paragraph", "需要理解搜索指数的概念和采集机制。", 3),
        _block("w9", "heading", "任务分析", 3),
        _block("w10", "paragraph", "根据指标体系确定采集范围。", 3),
        _block("w11", "heading", "任务操作", 4),
        _block("w12", "paragraph", "1. 确定采集渠道。", 4),
        _block("w13", "paragraph", "2. 明确采集指标。", 4),
        _block("w14", "paragraph", "3. 填写数据采集表。", 4),
        _block("w15", "heading", "任务思考", 5),
        _block("w16", "heading", "工作任务二 运营数据采集", 6),
        _block("w17", "heading", "任务目标", 6),
        _block("w18", "heading", "工作子任务一 客户成交数据采集", 7),
        _block("w19", "heading", "任务背景", 7),
        _block("w20", "heading", "任务分析", 7),
        _block("w21", "heading", "任务操作", 8),
        _block("w22", "paragraph", "1. 导出订单数据。", 8),
        _block("w23", "paragraph", "2. 清洗客户字段。", 8),
        _block("w24", "paragraph", "3. 生成运营数据采集表。", 8),
    ]


def test_detects_training_operation_textbook() -> None:
    result = detect_course_textbook_subtype(_training_blocks())

    assert result.textbook_subtype == "training_operation"
    assert result.processing_profile == "task_outline"
    assert result.evidence_graph_admission == "not_recommended"
    assert result.subtype_confidence >= 0.7
    assert "存在明确任务标题" in result.subtype_evidence
    assert result.source_block_ids


def test_detects_work_task_textbook_as_training_operation_despite_theory_keywords() -> None:
    result = detect_course_textbook_subtype(_work_task_textbook_blocks())

    assert result.textbook_subtype == "training_operation"
    assert result.processing_profile == "task_outline"
    assert result.evidence_graph_admission == "not_recommended"
    assert result.scores["task_score"] > 0
    assert result.scores["theory_score"] > 0


def test_ocr_damaged_work_field_heading_groups_following_tasks() -> None:
    blocks = [
        _block("w1", "paragraph", "工作领域 - - 基础数据採集", 1),
        _block("w2", "heading", "工作任务一 市场数据采集", 2),
        _block("w3", "heading", "任务目标", 2),
        _block("w4", "paragraph", "能够完成市场数据指标体系设计。", 2),
        _block("w5", "heading", "任务操作", 3),
        _block("w6", "paragraph", "步骤1，确定采集指标。", 3),
        _block("w7", "paragraph", "步骤2，确定数据来源。", 3),
    ]
    body_markdown = _body_markdown_with_ranges(blocks)

    extraction = extract_course_textbook_outline(
        normalized_ref_id="ref-training-ocr-field",
        asset_version_id="ver-training-ocr-field",
        title="电子商务数据分析实践",
        blocks=blocks,
        body_markdown=body_markdown,
    )

    project = next(node for node in extraction.nodes if node.node_type == "project")
    task = next(node for node in extraction.nodes if node.node_type == "task")

    assert project.title == "工作领域 - - 基础数据採集"
    assert task.parent_id == project.id
    assert task.depth == 2


def test_work_subtasks_are_nested_under_current_work_task() -> None:
    blocks = _work_task_textbook_blocks()
    body_markdown = _body_markdown_with_ranges(blocks)

    extraction = extract_course_textbook_outline(
        normalized_ref_id="ref-training-subtask-tree",
        asset_version_id="ver-training-subtask-tree",
        title="电子商务数据分析实践",
        blocks=blocks,
        body_markdown=body_markdown,
    )

    project = next(node for node in extraction.nodes if node.node_type == "project")
    work_task_one = next(node for node in extraction.nodes if node.title == "工作任务一 市场数据采集")
    market_subtask = next(node for node in extraction.nodes if node.title == "工作子任务一 市场行情数据采集")
    work_task_two = next(node for node in extraction.nodes if node.title == "工作任务二 运营数据采集")
    customer_subtask = next(node for node in extraction.nodes if node.title == "工作子任务一 客户成交数据采集")

    assert work_task_one.parent_id == project.id
    assert market_subtask.parent_id == work_task_one.id
    assert market_subtask.depth == work_task_one.depth + 1
    assert market_subtask.metadata["hierarchy_source"] == "task_numbering_fallback_after_mineru_level_tie"
    assert work_task_two.parent_id == project.id
    assert customer_subtask.parent_id == work_task_two.id


def test_mineru_heading_level_is_preferred_for_task_hierarchy() -> None:
    blocks = [
        _block("w1", "heading", "工作领域一 基础数据采集", 1),
        _block("w2", "heading", "工作任务一 市场数据采集", 2),
        _block("w3", "heading", "工作子任务一 市场行情数据采集", 3),
        _block("w4", "heading", "任务操作", 4),
        _block("w5", "paragraph", "步骤1，确定采集指标。", 4),
    ]
    blocks[0]["heading_level"] = 1
    blocks[1]["heading_level"] = 2
    blocks[2]["heading_level"] = 3
    blocks[3]["heading_level"] = 4
    body_markdown = _body_markdown_with_ranges(blocks)

    extraction = extract_course_textbook_outline(
        normalized_ref_id="ref-training-heading-level",
        asset_version_id="ver-training-heading-level",
        title="电子商务数据分析实践",
        blocks=blocks,
        body_markdown=body_markdown,
    )

    work_task = next(node for node in extraction.nodes if node.title == "工作任务一 市场数据采集")
    subtask = next(node for node in extraction.nodes if node.title == "工作子任务一 市场行情数据采集")

    assert subtask.parent_id == work_task.id
    assert subtask.metadata["hierarchy_source"] == "mineru_heading_level"


def test_detects_theory_knowledge_textbook() -> None:
    result = detect_course_textbook_subtype(_theory_blocks())

    assert result.textbook_subtype == "theory_knowledge"
    assert result.processing_profile == "evidence_graph"
    assert result.evidence_graph_admission == "recommended"
    assert result.subtype_confidence >= 0.65


def test_projectized_theory_textbook_with_practice_drills_uses_evidence_graph() -> None:
    result = detect_course_textbook_subtype(_projectized_theory_with_practice_blocks())

    assert result.textbook_subtype == "theory_knowledge"
    assert result.processing_profile == "evidence_graph"
    assert result.evidence_graph_admission == "recommended"
    assert result.scores["task_score"] > 0
    assert result.scores["theory_score"] > 0


def test_detects_hybrid_when_theory_and_task_signals_coexist() -> None:
    result = detect_course_textbook_subtype(_hybrid_blocks())

    assert result.textbook_subtype in {"hybrid", "training_operation"}
    assert result.processing_profile in {"hybrid", "task_outline"}
    assert result.scores["task_score"] > 0
    assert result.scores["theory_score"] > 0


def test_extracts_minimal_task_outline_for_training_textbook() -> None:
    blocks = _training_blocks()
    body_markdown = _body_markdown_with_ranges(blocks)
    extraction = extract_course_textbook_outline(
        normalized_ref_id="ref-training",
        asset_version_id="ver-training",
        title="电子商务数据分析实践",
        blocks=blocks,
        body_markdown=body_markdown,
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


def test_extracts_artifact_leaf_content_from_body_markdown_table_slice() -> None:
    blocks = _training_blocks()
    table_markdown = (
        "| 商品名称 | 链接 | 价格 | 月销量 |\n"
        "| --- | --- | --- | --- |\n"
        "| A款智能门锁 | https://example.test/a | 899 | 320 |"
    )
    body_markdown = _body_markdown_with_ranges(blocks, {"b10": table_markdown})

    extraction = extract_course_textbook_outline(
        normalized_ref_id="ref-training-table",
        asset_version_id="ver-training-table",
        title="电子商务数据分析实践",
        blocks=blocks,
        body_markdown=body_markdown,
    )

    artifact = next(node for node in extraction.nodes if node.node_type == "task_artifact")
    assert artifact.content == table_markdown
    assert "| 商品名称 | 链接 | 价格 | 月销量 |" in artifact.content
    assert artifact.title.startswith("图1-2")


def test_skips_empty_visual_artifact_leaf_nodes() -> None:
    blocks = _training_blocks()
    blocks.append({
        "block_id": "img-empty",
        "block_type": "image",
        "caption": "",
        "text": "",
        "page": 17,
        "bbox": [10, 10, 20, 20],
        "md_char_range": None,
    })
    body_markdown = _body_markdown_with_ranges(blocks[:-1])

    extraction = extract_course_textbook_outline(
        normalized_ref_id="ref-training-empty-image",
        asset_version_id="ver-training-empty-image",
        title="电子商务数据分析实践",
        blocks=blocks,
        body_markdown=body_markdown,
    )

    assert all("img-empty" not in node.source_block_ids for node in extraction.nodes)


def test_preface_numbered_items_do_not_create_implicit_task() -> None:
    blocks = [
        _block("p1", "paragraph", "1．科学构建知识技能体系，实现课程标准覆盖。", 5),
        _block("p2", "paragraph", "2．创新教材形式，配套开发数字化教学资源。", 5),
        *_training_blocks(),
    ]
    body_markdown = _body_markdown_with_ranges(blocks)

    extraction = extract_course_textbook_outline(
        normalized_ref_id="ref-training-preface",
        asset_version_id="ver-training-preface",
        title="电子商务数据分析实践",
        blocks=blocks,
        body_markdown=body_markdown,
    )

    task_titles = [node.title for node in extraction.nodes if node.node_type == "task"]
    assert "未命名任务" not in task_titles
    assert task_titles[0] == "任务一 市场数据采集"
    assert all("p1" not in node.source_block_ids for node in extraction.nodes)
    assert all("p2" not in node.source_block_ids for node in extraction.nodes)


def test_task_map_heading_stops_objective_content_noise() -> None:
    blocks = [
        _block("w1", "heading", "工作任务一 市场数据采集", 1),
        _block("w2", "heading", "任务目标", 1),
        _block("w3", "paragraph", "能够根据需求确定数据采集渠道", 1),
        _block("w4", "paragraph", "能够根据需求明确数据采集指标", 1),
        _block("w5", "heading", "任务导图", 1),
        _block("w6", "paragraph", "市场行情数据采集渠道", 1),
        _block("w7", "paragraph", "确定市场数据采集渠道及指标", 1),
        _block("w8", "heading", "知识回顾", 2),
        _block("w9", "paragraph", "请学员在回顾知识内容后，回答以下问题：", 2),
        _block("w10", "heading", "任务操作", 3),
        _block("w11", "paragraph", "1. 确定采集指标。", 3),
    ]
    body_markdown = _body_markdown_with_ranges(blocks)

    extraction = extract_course_textbook_outline(
        normalized_ref_id="ref-training-objective-noise",
        asset_version_id="ver-training-objective-noise",
        title="电子商务数据分析实践",
        blocks=blocks,
        body_markdown=body_markdown,
    )

    objective = next(node for node in extraction.nodes if node.section_type == "task_objective")
    assert "能够根据需求确定数据采集渠道" in (objective.content or "")
    assert "确定市场数据采集渠道及指标" not in (objective.content or "")


def test_numbered_review_and_reflection_questions_stay_in_their_sections() -> None:
    blocks = [
        _block("w1", "heading", "工作任务一 市场数据采集", 1),
        _block("w2", "heading", "知识回顾", 1),
        _block("w3", "paragraph", "请学员在回顾知识内容后，回答以下问题：", 1),
        _block("w4", "paragraph", "1. 市场数据采集渠道有哪些?", 1),
        _block("w5", "paragraph", "2. 常用的数据采集工具有哪些?", 1),
        _block("w6", "heading", "任务操作", 2),
        _block("w7", "paragraph", "1. 确定采集指标。", 2),
        _block("w8", "paragraph", "2. 确定数据来源。", 2),
        _block("w9", "heading", "任务思考", 3),
        _block("w10", "paragraph", "通过以上操作，请回答以下问题：", 3),
        _block("w11", "paragraph", "1. 还可以通过哪些渠道完成采集?", 3),
    ]
    body_markdown = _body_markdown_with_ranges(blocks)

    extraction = extract_course_textbook_outline(
        normalized_ref_id="ref-training-numbered-review",
        asset_version_id="ver-training-numbered-review",
        title="电子商务数据分析实践",
        blocks=blocks,
        body_markdown=body_markdown,
    )

    review = next(node for node in extraction.nodes if node.section_type == "knowledge_prepare")
    reflection = next(node for node in extraction.nodes if node.section_type == "task_reflection")
    steps = [node for node in extraction.nodes if node.node_type == "operation_step"]

    assert "1. 市场数据采集渠道有哪些?" in (review.content or "")
    assert "2. 常用的数据采集工具有哪些?" in (review.content or "")
    assert "1. 还可以通过哪些渠道完成采集?" in (reflection.content or "")
    assert [node.metadata["step_no"] for node in steps] == [1, 2]
    assert all("市场数据采集渠道有哪些" not in node.title for node in steps)
    assert all("还可以通过哪些渠道" not in node.title for node in steps)


def test_chinese_step_label_keeps_following_body_with_step() -> None:
    blocks = [
        _block("w1", "heading", "工作任务一 市场数据采集", 1),
        _block("w2", "heading", "任务操作", 1),
        _block("w3", "paragraph", "步骤1，确定采集指标。", 1),
        _block("w4", "paragraph", "此任务中数据指标为关键词指数及对应日期。", 1),
        _block("w5", "paragraph", "步骤2，确定数据来源。", 1),
        _block("w6", "paragraph", "百度指数数据可以作为数据来源。", 1),
    ]
    body_markdown = _body_markdown_with_ranges(blocks)

    extraction = extract_course_textbook_outline(
        normalized_ref_id="ref-training-chinese-steps",
        asset_version_id="ver-training-chinese-steps",
        title="电子商务数据分析实践",
        blocks=blocks,
        body_markdown=body_markdown,
    )

    steps = [node for node in extraction.nodes if node.node_type == "operation_step"]
    operation = next(node for node in extraction.nodes if node.section_type == "operation_steps")

    assert [node.metadata["step_no"] for node in steps] == [1, 2]
    assert "此任务中数据指标" in (steps[0].content or "")
    assert "百度指数数据" in (steps[1].content or "")
    assert not operation.content


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
