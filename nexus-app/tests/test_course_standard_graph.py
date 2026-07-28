from nexus_app.capability_graph.builders import build_course_standard
from nexus_app.capability_graph.whitelists import EdgeType, NodeType
from nexus_app.teaching_standard.course_standard import extract_with_diagnostics


COURSE_CONTENT_TABLE = """| 课程模块 | 教学任务 | 技能要求 | 知识要求 |
| --- | --- | --- | --- |
| 模块一：O2O运营认知 | 任务一：分析零售O2O业务<br>任务二：识别平台生态 | 技能一：绘制业务流程<br>技能二：分析用户场景 | 知识一：O2O运营模式<br>知识二：零售平台生态 |
| 模块二：门店数字化管理 | 任务三：配置门店数字化工具 | 技能三：操作POS系统 | 知识三：库存管理基础 |"""


def _payload(table: str = COURSE_CONTENT_TABLE):
    return {
        "content_type": "document",
        "title": "《零售门店O2O运营》课程标准",
        "blocks": [
            {
                "block_id": "course-content-table",
                "block_type": "table",
                "content": table,
                "page": 5,
            }
        ],
    }


def test_extracts_course_content_requirement_rows_with_evidence():
    result = extract_with_diagnostics(_payload())

    assert result.payload is not None
    assert result.payload["schema_version"] == "course_standard.v1"
    assert len(result.payload["rows"]) == 2
    first = result.payload["rows"][0]
    assert first["course_module"] == "模块一：O2O运营认知"
    assert first["teaching_tasks"] == ["任务一：分析零售O2O业务", "任务二：识别平台生态"]
    assert first["skill_requirements"] == ["技能一：绘制业务流程", "技能二：分析用户场景"]
    assert first["knowledge_requirements"] == ["知识一：O2O运营模式", "知识二：零售平台生态"]
    assert first["evidence"]["source_block_ids"] == ["course-content-table"]
    assert first["evidence"]["locator"]["table_row_index"] == 1


def test_requires_all_four_course_content_columns():
    table = COURSE_CONTENT_TABLE.replace("| 知识要求 |", "| 教学重点 |", 1)

    result = extract_with_diagnostics(_payload(table))

    assert result.payload is None
    assert result.failure_reason == "course_content_headers_missing"


def test_builds_only_frozen_course_standard_topology():
    extracted = extract_with_diagnostics(_payload()).payload
    assert extracted is not None

    nodes, edges = build_course_standard(extracted)

    assert {node.node_type for node in nodes} == {
        NodeType.COURSE_MODULE,
        NodeType.WORK_TASK,
        NodeType.SKILL_REQUIREMENT,
        NodeType.KNOWLEDGE_REQUIREMENT,
    }
    assert {edge.edge_type for edge in edges} == {
        EdgeType.COURSE_MODULE_HAS_TEACHING_TASK,
        EdgeType.TEACHING_TASK_HAS_SKILL_REQUIREMENT,
        EdgeType.SKILL_REQUIREMENT_HAS_KNOWLEDGE_REQUIREMENT,
    }
    assert all(edge.evidence["source_block_ids"] == ["course-content-table"] for edge in edges)
