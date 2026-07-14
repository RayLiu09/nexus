from nexus_app.capability_graph.builders import build_teaching_standard
from nexus_app.capability_graph.whitelists import EdgeType, NodeType
from nexus_app.teaching_standard import extract


TABLE = """| 序号 | 课程涉及的主要领域 | 典型工作任务描述 | 主要教学内容与要求 |
| ---- | ---- | ---- | ---- |
| 1 | 市场策划 | 典型工作任务为市场策划，工作内容包括产品策划、行业定位分析、销售渠道策划 | ① 掌握市场策划的流程和方法。<br>② 能够分析行业定位，选择目标市场。<br>③ 设计分销渠道和营销活动。 |
| 2 | 网络推广 | 典型工作任务为网络推广，工作内容包括目标人群画像分析、推广预算、广告投放 | ① 掌握网络推广平台投放特点。<br>② 能够绘制目标人群画像，选择推广渠道。 |"""


def _payload():
    return {
        "content_type": "document", "title": "5307 电子商务专业教学标准",
        "blocks": [{"block_id": "table-1", "block_type": "table", "content": TABLE, "page": 12, "bbox": [1, 2, 3, 4]}],
    }


def test_extracts_table_rows_with_evidence_and_bullets():
    result = extract(_payload())
    assert result is not None
    assert result["major_code"] == "5307"
    assert result["major_name"] == "电子商务专业教学标准"
    assert len(result["rows"]) == 2
    first = result["rows"][0]
    assert first["occupational_domain"] == "市场策划"
    assert len(first["typical_work_tasks"]) >= 3
    assert len(first["skill_knowledge_requirements"]) == 3
    assert first["evidence"]["source_block_ids"] == ["table-1"]
    assert first["evidence"]["locator"]["table_row_index"] == 1


def test_builds_only_the_frozen_radial_graph_relations():
    payload = extract(_payload())
    assert payload is not None
    nodes, edges = build_teaching_standard(payload)
    assert NodeType.MAJOR in {node.node_type for node in nodes}
    assert NodeType.OCCUPATIONAL_DOMAIN in {node.node_type for node in nodes}
    assert NodeType.TYPICAL_WORK_TASK in {node.node_type for node in nodes}
    assert NodeType.SKILL_KNOWLEDGE_REQUIREMENT in {node.node_type for node in nodes}
    assert "Course" not in {node.node_type for node in nodes}
    assert {edge.edge_type for edge in edges} == {
        EdgeType.MAJOR_HAS_OCCUPATIONAL_DOMAIN,
        EdgeType.OCCUPATIONAL_DOMAIN_HAS_TYPICAL_WORK_TASK,
        EdgeType.OCCUPATIONAL_DOMAIN_HAS_SKILL_KNOWLEDGE_REQUIREMENT,
    }
    assert all(edge.evidence.get("source_block_ids") == ["table-1"] for edge in edges if edge.edge_type != EdgeType.MAJOR_HAS_OCCUPATIONAL_DOMAIN)
