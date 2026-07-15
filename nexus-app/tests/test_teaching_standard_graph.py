from nexus_app.capability_graph.builders import build_teaching_standard
from nexus_app.capability_graph.whitelists import EdgeType, NodeType
import json

from nexus_app.ai_governance.litellm_client import FakeLiteLLMClient
from nexus_app.teaching_standard import extract
from nexus_app.teaching_standard.llm_fallback import extract as llm_fallback


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


def test_supports_name_first_identity_and_real_work_content_enumeration():
    payload = _payload()
    payload["title"] = "电子商务专业教学标准"
    payload["blocks"].insert(0, {"block_id": "identity", "block_type": "paragraph", "text": "电子商务（530701）"})
    payload["blocks"][1]["content"] = TABLE.replace("工作内容包括产品策划、行业定位分析、销售渠道策划", "工作内容主要有运营规划、商品选品与定价、供应链管理")
    result = extract(payload)
    assert result is not None
    assert result["major_code"] == "530701"
    assert result["rows"][0]["typical_work_tasks"] == ["运营规划", "商品选品与定价", "供应链管理"]
    assert len(result["rows"][0]["skill_knowledge_requirements"]) == 3


def _fallback_payload():
    payload = _payload()
    payload["title"] = "电子商务专业教学标准"
    payload["blocks"].insert(0, {"block_id": "identity", "block_type": "paragraph", "text": "电子商务（530701）"})
    payload["blocks"][1]["content"] = TABLE.replace("课程涉及的主要领域", "涉及领域")
    return payload


def _fallback_response(*, text="市场策划", confidence=0.92, block_id="table-1"):
    raw_row = "| 1 | 市场策划 | 典型工作任务为市场策划，工作内容包括产品策划、行业定位分析、销售渠道策划 | ① 掌握市场策划的流程和方法。<br>② 能够分析行业定位，选择目标市场。<br>③ 设计分销渠道和营销活动。 |"
    return {
        "schema_version": "teaching_standard.llm_fallback.v1",
        "major": {"name": "电子商务", "code": "530701", "evidence_block_ids": ["identity"], "evidence_text": "电子商务（530701）"},
        "rows": [{
            "source_block_id": block_id, "table_row_index": 1, "confidence": confidence,
            "occupational_domain": {"text": text, "evidence_text": raw_row},
            "typical_work_tasks": [{"text": "产品策划", "evidence_text": raw_row}],
            "skill_knowledge_requirements": [{"text": "掌握市场策划的流程和方法", "evidence_text": raw_row}],
        }],
    }


def test_llm_fallback_adopts_evidence_bound_payload_with_extraction_alias():
    client = FakeLiteLLMClient(response_override=json.dumps(_fallback_response(), ensure_ascii=False))
    result = llm_fallback(_fallback_payload(), llm_client=client, model_alias="test-extraction-alias", rule_failure_reason="header_alias_unmapped")
    assert result.payload is not None
    assert result.payload["major_code"] == "530701"
    assert result.payload["extractor"]["strategy"] == "llm_fallback"
    assert result.payload["extractor"]["model_alias"] == "test-extraction-alias"
    nodes, edges = build_teaching_standard(result.payload)
    assert nodes and {edge.edge_type for edge in edges} <= {
        EdgeType.MAJOR_HAS_OCCUPATIONAL_DOMAIN,
        EdgeType.OCCUPATIONAL_DOMAIN_HAS_TYPICAL_WORK_TASK,
        EdgeType.OCCUPATIONAL_DOMAIN_HAS_SKILL_KNOWLEDGE_REQUIREMENT,
    }


def test_llm_fallback_rejects_hallucinated_or_low_confidence_output():
    hallucinated = llm_fallback(_fallback_payload(), llm_client=FakeLiteLLMClient(response_override=json.dumps(_fallback_response(text="虚构职业领域"), ensure_ascii=False)), model_alias="alias", rule_failure_reason="header_alias_unmapped")
    assert hallucinated.payload is None
    assert hallucinated.metadata["reason"] == "row_evidence_invalid"

    low_confidence = llm_fallback(_fallback_payload(), llm_client=FakeLiteLLMClient(response_override=json.dumps(_fallback_response(confidence=0.7), ensure_ascii=False)), model_alias="alias", rule_failure_reason="header_alias_unmapped")
    assert low_confidence.payload is None
    assert low_confidence.metadata["reason"] == "row_confidence_low"

    unknown_block = llm_fallback(
        _fallback_payload(),
        llm_client=FakeLiteLLMClient(
            response_override=json.dumps(
                _fallback_response(block_id="unknown-table"), ensure_ascii=False
            )
        ),
        model_alias="alias",
        rule_failure_reason="header_alias_unmapped",
    )
    assert unknown_block.payload is None
    assert unknown_block.metadata["reason"] == "row_locator_invalid"


def test_llm_fallback_skips_without_client_or_valid_json():
    unavailable = llm_fallback(_fallback_payload(), llm_client=None, model_alias="alias", rule_failure_reason="header_alias_unmapped")
    assert unavailable.payload is None
    assert unavailable.metadata["reason"] == "llm_client_unavailable"
    invalid = llm_fallback(_fallback_payload(), llm_client=FakeLiteLLMClient(response_override="not-json"), model_alias="alias", rule_failure_reason="header_alias_unmapped")
    assert invalid.payload is None
    assert invalid.metadata["reason"] == "llm_schema_invalid"
