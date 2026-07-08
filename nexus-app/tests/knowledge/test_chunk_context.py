from nexus_app import models
from nexus_app.enums import ChunkType, ChunkingStrategy, EmbeddingStatus, SourceKind
from nexus_app.knowledge.chunk_context import hierarchy_context


def _tree_titles(nodes):
    out = []

    def visit(node):
        out.append(node["display_title"])
        for child in node["children"]:
            visit(child)

    for item in nodes:
        visit(item)
    return out


def _chunk(
    *,
    chunk_id: str,
    ref_id: str = "ref-textbook",
    index: int,
    content: str,
    block_id: str,
) -> models.KnowledgeChunk:
    return models.KnowledgeChunk(
        id=chunk_id,
        normalized_ref_id=ref_id,
        knowledge_type_code="course_textbook",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=index,
        content=content,
        chunk_metadata={"anchor_role": "body"},
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=[block_id],
        locator={
            "page_start": 11,
            "page_end": 11,
            "blocks": [{"block_id": block_id, "page": 11, "bbox": None}],
        },
    )


def test_hierarchy_context_recovers_textbook_parent_and_knowledge_points_from_flat_headings():
    current = _chunk(
        chunk_id="9a6b9f76-895c-4084-a237-0ccfc5105929",
        index=36,
        content="短视频通过将图像、声音、文字等多种表达方式相结合...",
        block_id="block-p11-107",
    )
    chunks = [
        _chunk(
            chunk_id="ctx-section-overview",
            index=35,
            content="短视频作为新媒体时代较受欢迎的内容传播形式，主要具有以下五个特点。",
            block_id="block-p11-105",
        ),
        current,
        _chunk(chunk_id="ctx-kp-2", index=37, content="简短精练正文", block_id="block-p11-109"),
        _chunk(chunk_id="ctx-kp-3", index=38, content="社交性强正文", block_id="block-p11-111"),
        _chunk(chunk_id="ctx-kp-4", index=39, content="内容丰富正文", block_id="block-p11-113"),
        _chunk(chunk_id="ctx-kp-5", index=40, content="传播更快正文", block_id="block-p11-115"),
    ]
    blocks = [
        {"block_id": "block-p11-103", "seq_no": 103, "block_type": "heading", "heading_level": 1, "text": "短视频认知"},
        {"block_id": "block-p11-104", "seq_no": 104, "block_type": "heading", "heading_level": 2, "text": "二、短视频的特点"},
        {"block_id": "block-p11-105", "seq_no": 105, "block_type": "paragraph", "text": "短视频作为新媒体时代较受欢迎的内容传播形式，主要具有以下五个特点。"},
        {"block_id": "block-p11-106", "seq_no": 106, "block_type": "heading", "heading_level": 2, "text": "1.  立体生动"},
        {"block_id": "block-p11-107", "seq_no": 107, "block_type": "paragraph", "text": "短视频通过将图像、声音、文字等多种表达方式相结合..."},
        {"block_id": "block-p11-108", "seq_no": 108, "block_type": "heading", "heading_level": 2, "text": "2.  简短精练"},
        {"block_id": "block-p11-109", "seq_no": 109, "block_type": "paragraph", "text": "简短精练正文"},
        {"block_id": "block-p11-110", "seq_no": 110, "block_type": "heading", "heading_level": 2, "text": "3.  社交性强"},
        {"block_id": "block-p11-111", "seq_no": 111, "block_type": "paragraph", "text": "社交性强正文"},
        {"block_id": "block-p11-112", "seq_no": 112, "block_type": "heading", "heading_level": 2, "text": "4.  内容丰富"},
        {"block_id": "block-p11-113", "seq_no": 113, "block_type": "paragraph", "text": "内容丰富正文"},
        {"block_id": "block-p11-114", "seq_no": 114, "block_type": "heading", "heading_level": 2, "text": "5.  传播更快"},
        {"block_id": "block-p11-115", "seq_no": 115, "block_type": "paragraph", "text": "传播更快正文"},
        {"block_id": "block-p11-116", "seq_no": 116, "block_type": "heading", "heading_level": 2, "text": "三、常见的短视频类型"},
    ]

    context = hierarchy_context(chunks, current, normalized_blocks=blocks)

    assert context["source"] == "normalized_blocks"
    assert [item["display_title"] for item in context["path"]] == [
        "短视频认知",
        "短视频的特点",
        "立体生动",
    ]
    assert context["parent_scope"]["display_title"] == "短视频的特点"
    assert context["parent_scope"]["overview_chunks"][0]["id"] == "ctx-section-overview"
    assert [item["display_title"] for item in context["parent_scope"]["knowledge_points"]] == [
        "立体生动",
        "简短精练",
        "社交性强",
        "内容丰富",
        "传播更快",
    ]
    assert context["parent_scope"]["knowledge_points"][0]["is_current"] is True
    assert context["parent_scope"]["knowledge_points"][0]["chunks"][0]["is_current"] is True
    assert context["parent_scope"]["chunk_range"] == [35, 40]


def test_hierarchy_context_builds_tree_leaf_nodes_from_learning_goal_list_items():
    current = _chunk(
        chunk_id="learning-goal-current",
        index=1,
        content="1. 认识视觉营销及短视频的定义。",
        block_id="block-p08-057",
    )
    chunks = [
        current,
        _chunk(
            chunk_id="learning-goal-2",
            index=2,
            content="2. 了解短视频的特点。",
            block_id="block-p08-058",
        ),
        _chunk(
            chunk_id="learning-goal-3",
            index=3,
            content="3. 熟悉常见的短视频类型。",
            block_id="block-p08-059",
        ),
    ]
    blocks = [
        {"block_id": "block-p08-055", "seq_no": 55, "block_type": "heading", "heading_level": 1, "text": "短视频认知"},
        {"block_id": "block-p08-056", "seq_no": 56, "block_type": "heading", "heading_level": 2, "text": "学习目标"},
        {"block_id": "block-p08-057", "seq_no": 57, "block_type": "paragraph", "text": "1. 认识视觉营销及短视频的定义。"},
        {"block_id": "block-p08-058", "seq_no": 58, "block_type": "paragraph", "text": "2. 了解短视频的特点。"},
        {"block_id": "block-p08-059", "seq_no": 59, "block_type": "paragraph", "text": "3. 熟悉常见的短视频类型。"},
        {"block_id": "block-p08-066", "seq_no": 66, "block_type": "heading", "heading_level": 2, "text": "学习导图"},
    ]

    context = hierarchy_context(chunks, current, normalized_blocks=blocks)

    assert [item["display_title"] for item in context["path"]] == [
        "短视频认知",
        "学习目标",
        "认识视觉营销及短视频的定义",
    ]
    assert context["parent_scope"]["display_title"] == "学习目标"
    assert [item["display_title"] for item in context["parent_scope"]["knowledge_points"]] == [
        "认识视觉营销及短视频的定义",
        "了解短视频的特点",
        "熟悉常见的短视频类型",
    ]
    assert context["parent_scope"]["knowledge_points"][0]["node_type"] == "knowledge_point"
    assert context["parent_scope"]["knowledge_points"][0]["source_block_id"] == "block-p08-057"
    assert context["parent_scope"]["knowledge_points"][0]["is_current"] is True
    assert [item["display_title"] for item in context["tree"]] == ["短视频认知"]
    assert _tree_titles(context["tree"]) == [
        "短视频认知",
        "学习目标",
        "认识视觉营销及短视频的定义",
        "了解短视频的特点",
        "熟悉常见的短视频类型",
    ]


def test_hierarchy_context_promotes_summary_content_chunks_under_structural_parent():
    current = _chunk(
        chunk_id="summary-current",
        index=2,
        content="本书内容新颖、逻辑清晰、实用性强，不仅将理论与实践相结合。",
        block_id="block-p01-009",
    )
    chunks = [
        _chunk(
            chunk_id="summary-first",
            index=1,
            content="本书依据职业教育专业教学标准编写，形成了 7 个项目。",
            block_id="block-p01-008",
        ),
        current,
    ]
    blocks = [
        {"block_id": "block-p00-003", "seq_no": 3, "block_type": "heading", "heading_level": 1, "text": "短视频拍摄与剪辑"},
        {"block_id": "block-p01-007", "seq_no": 7, "block_type": "heading", "heading_level": 2, "text": "内容提要"},
        {"block_id": "block-p01-008", "seq_no": 8, "block_type": "paragraph", "text": "本书依据职业教育专业教学标准编写，形成了 7 个项目。"},
        {"block_id": "block-p01-009", "seq_no": 9, "block_type": "paragraph", "text": "本书内容新颖、逻辑清晰、实用性强，不仅将理论与实践相结合。"},
    ]

    context = hierarchy_context(chunks, current, normalized_blocks=blocks)

    assert [item["display_title"] for item in context["path"]] == [
        "短视频拍摄与剪辑",
        "内容提要",
        "本书内容新颖、逻辑清晰、实用性强，不仅将理论与实践相结合",
    ]
    assert context["parent_scope"]["display_title"] == "内容提要"
    assert context["parent_scope"]["node_type"] == "section"
    assert [item["display_title"] for item in context["parent_scope"]["knowledge_points"]] == [
        "本书依据职业教育专业教学标准编写，形成了 7 个项目",
        "本书内容新颖、逻辑清晰、实用性强，不仅将理论与实践相结合",
    ]
    assert context["parent_scope"]["knowledge_points"][1]["is_current"] is True
    assert _tree_titles(context["tree"]) == [
        "短视频拍摄与剪辑",
        "内容提要",
        "本书依据职业教育专业教学标准编写，形成了 7 个项目",
        "本书内容新颖、逻辑清晰、实用性强，不仅将理论与实践相结合",
    ]


def test_hierarchy_context_treats_generic_heading_leaf_nodes_as_knowledge_points():
    current = _chunk(
        chunk_id="current-derivative",
        index=12,
        content="导数表示函数在某一点附近的瞬时变化率。",
        block_id="math-p2-006",
    )
    chunks = [
        _chunk(
            chunk_id="calculus-overview",
            index=10,
            content="本节介绍导数的定义、几何意义和计算方法。",
            block_id="math-p2-004",
        ),
        current,
        _chunk(
            chunk_id="derivative-geometry",
            index=13,
            content="导数的几何意义是曲线切线斜率。",
            block_id="math-p2-008",
        ),
    ]
    blocks = [
        {"block_id": "math-p2-001", "seq_no": 1, "block_type": "heading", "heading_level": 1, "text": "微积分基础"},
        {"block_id": "math-p2-002", "seq_no": 2, "block_type": "heading", "heading_level": 2, "text": "导数"},
        {"block_id": "math-p2-004", "seq_no": 4, "block_type": "paragraph", "text": "本节介绍导数的定义、几何意义和计算方法。"},
        {"block_id": "math-p2-005", "seq_no": 5, "block_type": "heading", "heading_level": 3, "text": "导数的定义"},
        {"block_id": "math-p2-006", "seq_no": 6, "block_type": "paragraph", "text": "导数表示函数在某一点附近的瞬时变化率。"},
        {"block_id": "math-p2-007", "seq_no": 7, "block_type": "heading", "heading_level": 3, "text": "导数的几何意义"},
        {"block_id": "math-p2-008", "seq_no": 8, "block_type": "paragraph", "text": "导数的几何意义是曲线切线斜率。"},
    ]

    context = hierarchy_context(chunks, current, normalized_blocks=blocks)

    assert [item["display_title"] for item in context["path"]] == [
        "微积分基础",
        "导数",
        "导数的定义",
    ]
    assert context["parent_scope"]["display_title"] == "导数"
    assert [item["display_title"] for item in context["parent_scope"]["knowledge_points"]] == [
        "导数的定义",
        "导数的几何意义",
    ]
    assert context["parent_scope"]["knowledge_points"][0]["node_type"] == "knowledge_point"
    assert context["parent_scope"]["knowledge_points"][0]["is_current"] is True


def test_hierarchy_context_supports_project_task_step_knowledge_structure():
    current = _chunk(
        chunk_id="current-firewall-step",
        index=22,
        content="配置入站规则时需要限定端口、源地址和协议。",
        block_id="ops-p4-006",
    )
    chunks = [
        _chunk(chunk_id="task-overview", index=20, content="本任务完成服务器安全基线配置。", block_id="ops-p4-004"),
        current,
        _chunk(chunk_id="audit-step", index=23, content="审计日志需要开启保留策略。", block_id="ops-p4-008"),
    ]
    blocks = [
        {"block_id": "ops-p4-001", "seq_no": 1, "block_type": "heading", "heading_level": 1, "text": "项目二 服务器运维"},
        {"block_id": "ops-p4-002", "seq_no": 2, "block_type": "heading", "heading_level": 2, "text": "任务一 安全基线配置"},
        {"block_id": "ops-p4-004", "seq_no": 4, "block_type": "paragraph", "text": "本任务完成服务器安全基线配置。"},
        {"block_id": "ops-p4-005", "seq_no": 5, "block_type": "heading", "heading_level": 3, "text": "步骤一 配置防火墙"},
        {"block_id": "ops-p4-006", "seq_no": 6, "block_type": "paragraph", "text": "配置入站规则时需要限定端口、源地址和协议。"},
        {"block_id": "ops-p4-007", "seq_no": 7, "block_type": "heading", "heading_level": 3, "text": "步骤二 开启审计日志"},
        {"block_id": "ops-p4-008", "seq_no": 8, "block_type": "paragraph", "text": "审计日志需要开启保留策略。"},
    ]

    context = hierarchy_context(chunks, current, normalized_blocks=blocks)

    assert [item["display_title"] for item in context["path"]] == [
        "服务器运维",
        "安全基线配置",
        "配置防火墙",
    ]
    assert context["parent_scope"]["display_title"] == "安全基线配置"
    assert [item["display_title"] for item in context["parent_scope"]["knowledge_points"]] == [
        "配置防火墙",
        "开启审计日志",
    ]
    assert context["parent_scope"]["chunk_range"] == [20, 23]
