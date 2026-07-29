from nexus_app.capability_graph.builders import build_course_standard
from nexus_app.capability_graph.whitelists import EdgeType, NodeType
from nexus_app.teaching_standard.course_standard import extract_with_diagnostics


COURSE_CONTENT_TABLE = """| 项目 | 教学任务 | 课程内容方向 | 课程内容方向 | 学时分配 |
| --- | --- | --- | --- | --- |
| 项目 | 教学任务 | 技能内容与要求 | 知识内容与要求 | 实训 |
| 模块一：O2O运营认知 | 任务一：分析零售O2O业务 | 1.技能一：绘制业务流程<br>2.技能二：分析用户场景 | 1.知识一：O2O运营模式<br>2.知识二：零售平台生态 | 2 |
|  | 学习单元：配置门店数字化工具 | 技能三：操作POS系统 | 知识三：库存管理基础 | 4 |
| 合计 | 合计 | 合计 | 合计 | 6 |"""


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
    assert result.payload["course_title"] == "零售门店O2O运营"
    assert result.payload["source_title"] == "《零售门店O2O运营》课程标准"
    assert len(result.payload["rows"]) == 2
    first = result.payload["rows"][0]
    assert first["course_module"] == "模块一：O2O运营认知"
    assert first["course_contents"] == ["任务一：分析零售O2O业务"]
    assert first["skill_requirements"] == ["技能一：绘制业务流程", "技能二：分析用户场景"]
    assert first["knowledge_requirements"] == ["知识一：O2O运营模式", "知识二：零售平台生态"]
    assert result.payload["rows"][1]["course_module"] == "模块一：O2O运营认知"
    assert first["evidence"]["source_block_ids"] == ["course-content-table"]
    assert first["evidence"]["locator"]["table_row_index"] == 1


def test_requires_all_four_course_content_columns():
    table = COURSE_CONTENT_TABLE.replace("知识内容与要求", "教学重点", 1)

    result = extract_with_diagnostics(_payload(table))

    assert result.payload is None
    assert result.failure_reason == "course_content_headers_missing"


def test_accepts_reordered_columns_and_grouped_header_aliases():
    table = """| 课程内容方向 | 工作模块 | 课程内容方向 | 课程内容方向 | 学时 |
| --- | --- | --- | --- | --- |
| 知识内容 | 项目 | 工作任务 | 技能内容 | 课时 |
| 知识一 | 模块一 | 任务一 | 技能一 | 2 |
"""

    result = extract_with_diagnostics(_payload(table))

    assert result.payload is not None
    row = result.payload["rows"][0]
    assert row["course_module"] == "模块一"
    assert row["course_contents"] == ["任务一"]
    assert row["skill_requirements"] == ["技能一"]
    assert row["knowledge_requirements"] == ["知识一"]


def test_builds_only_frozen_course_standard_topology():
    extracted = extract_with_diagnostics(_payload()).payload
    assert extracted is not None

    nodes, edges = build_course_standard(extracted)

    assert {node.node_type for node in nodes} == {
        NodeType.COURSE,
        NodeType.COURSE_MODULE,
        NodeType.COURSE_CONTENT,
        NodeType.SKILL_REQUIREMENT,
        NodeType.KNOWLEDGE_REQUIREMENT,
    }
    assert {edge.edge_type for edge in edges} == {
        EdgeType.COURSE_HAS_COURSE_MODULE,
        EdgeType.COURSE_MODULE_HAS_COURSE_CONTENT,
        EdgeType.COURSE_CONTENT_HAS_SKILL_REQUIREMENT,
        EdgeType.SKILL_REQUIREMENT_HAS_KNOWLEDGE_REQUIREMENT,
    }
    assert all(edge.evidence["source_block_ids"] == ["course-content-table"] for edge in edges)
    course = next(node for node in nodes if node.node_type == NodeType.COURSE)
    assert course.display_name == "零售门店O2O运营"
    assert course.properties["source_title"] == "《零售门店O2O运营》课程标准"
    assert all(symbol not in course.display_name for symbol in "《》：")


def test_rejects_course_standard_without_a_usable_title():
    payload = _payload()
    payload["title"] = "《课程标准》"

    result = extract_with_diagnostics(payload)

    assert result.payload is None
    assert result.failure_reason == "course_title_missing"


def test_removes_file_extension_before_course_standard_title_suffix():
    payload = _payload()
    payload["title"] = "《零售门店O2O运营》课程标准.pdf"

    result = extract_with_diagnostics(payload)

    assert result.payload is not None
    assert result.payload["course_title"] == "零售门店O2O运营"
