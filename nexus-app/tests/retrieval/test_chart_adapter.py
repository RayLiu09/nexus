"""A4 (§10 阶段 A + §1.15 §7.3) — chart adapter + chart_id + placeholder replacement."""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from nexus_app.retrieval.chart_adapter import (
    ChartMeta,
    ChartNode,
    ChartPayload,
    ChartRegistry,
    _PLACEHOLDER_RE,
    _fence_for,
    capability_graph_to_chart,
    knowledge_graph_to_chart,
    make_chart_id,
    replace_chart_placeholders,
)


# ---------------------------------------------------------------------------
# Lightweight row stand-ins — mimic the SQLAlchemy attributes read by the
# adapters without pulling the DB in for a pure unit test.
# ---------------------------------------------------------------------------


@dataclass
class _CGSNode:
    id: str
    node_type: str
    display_name: str


@dataclass
class _CGSEdge:
    source_node_id: str
    target_node_id: str
    edge_type: str


@dataclass
class _KGNode:
    id: str
    node_type: str
    name: str


@dataclass
class _KGEdge:
    source_node_id: str
    target_node_id: str
    relation_type: str


# ---------------------------------------------------------------------------
# capability_graph_to_chart
# ---------------------------------------------------------------------------


def test_capability_graph_to_chart_maps_nodes_and_edges():
    nodes = [
        _CGSNode(id="n1", node_type="MAJOR", display_name="电子商务"),
        _CGSNode(id="n2", node_type="OCCUPATIONAL_DOMAIN", display_name="市场策划"),
    ]
    edges = [
        _CGSEdge(source_node_id="n1", target_node_id="n2",
                 edge_type="MAJOR_HAS_OCCUPATIONAL_DOMAIN"),
    ]
    payload = capability_graph_to_chart(
        nodes=nodes, edges=edges,
        title="电子商务 教学标准",
        source_ref="build-abc",
    )
    j = payload.to_json()
    assert j["type"] == "graph"
    assert len(j["nodes"]) == 2
    assert j["nodes"][0] == {"id": "n1", "name": "电子商务", "category": "major"}
    assert j["nodes"][1]["category"] == "occupational_domain"
    assert j["edges"] == [{
        "source": "n1", "target": "n2",
        "relation": "MAJOR_HAS_OCCUPATIONAL_DOMAIN",
    }]
    assert j["meta"] == {"title": "电子商务 教学标准", "source_ref": "build-abc"}


def test_capability_graph_to_chart_normalises_camel_case_node_types():
    nodes = [
        _CGSNode(id="n1", node_type="Major", display_name="网络营销与直播电商"),
        _CGSNode(id="n2", node_type="OccupationalDomain", display_name="市场策划"),
        _CGSNode(id="n3", node_type="TypicalWorkTask", display_name="产品策划"),
        _CGSNode(
            id="n4",
            node_type="SkillKnowledgeRequirement",
            display_name="市场定位分析",
        ),
    ]
    payload = capability_graph_to_chart(nodes=nodes, edges=[], title="t")

    assert [node["category"] for node in payload.to_json()["nodes"]] == [
        "major",
        "occupational_domain",
        "typical_work_task",
        "skill_knowledge_requirement",
    ]


def test_capability_graph_to_chart_drops_dangling_edges():
    """Defence-in-depth: an edge whose endpoint is missing from the node
    list gets silently dropped. Composer can't render a graph with
    dangling arrows and Composer prompts don't need to know."""
    nodes = [_CGSNode(id="n1", node_type="MAJOR", display_name="电子商务")]
    edges = [
        _CGSEdge(source_node_id="n1", target_node_id="ghost", edge_type="X"),
        _CGSEdge(source_node_id="phantom", target_node_id="n1", edge_type="Y"),
    ]
    payload = capability_graph_to_chart(nodes=nodes, edges=edges, title="t")
    assert payload.edges == []


def test_capability_graph_to_chart_empty_source_ref_meta_key_omitted():
    payload = capability_graph_to_chart(nodes=[], edges=[], title="empty")
    j = payload.to_json()
    assert j["nodes"] == []
    assert j["edges"] == []
    assert j["meta"] == {"title": "empty"}
    assert "source_ref" not in j["meta"]


def test_capability_graph_to_chart_normalises_missing_node_type_to_unknown():
    payload = capability_graph_to_chart(
        nodes=[_CGSNode(id="n1", node_type="", display_name="X")],
        edges=[],
        title="t",
    )
    assert payload.to_json()["nodes"][0]["category"] == "unknown"


# ---------------------------------------------------------------------------
# knowledge_graph_to_chart (evidence-grounded KG)
# ---------------------------------------------------------------------------


def test_knowledge_graph_to_chart_uses_name_and_relation_type():
    nodes = [
        _KGNode(id="k1", node_type="CONCEPT", name="市场营销"),
        _KGNode(id="k2", node_type="CONCEPT", name="4P 理论"),
    ]
    edges = [
        _KGEdge(source_node_id="k1", target_node_id="k2",
                relation_type="INCLUDES"),
    ]
    payload = knowledge_graph_to_chart(
        nodes=nodes, edges=edges, title="市场营销章节图",
        source_ref="ref-xyz",
    )
    j = payload.to_json()
    assert j["nodes"][0] == {"id": "k1", "name": "市场营销", "category": "concept"}
    assert j["edges"][0]["relation"] == "INCLUDES"
    assert j["meta"]["source_ref"] == "ref-xyz"


# ---------------------------------------------------------------------------
# make_chart_id
# ---------------------------------------------------------------------------


def test_make_chart_id_is_deterministic():
    a = make_chart_id("tc_abc")
    b = make_chart_id("tc_abc", 0)
    assert a == b == "tc_abc:0"


def test_make_chart_id_indexed_multi_chart():
    assert make_chart_id("tc_xyz", 3) == "tc_xyz:3"


def test_make_chart_id_rejects_empty_tool_call_id():
    with pytest.raises(ValueError):
        make_chart_id("", 0)


def test_make_chart_id_rejects_negative_index():
    with pytest.raises(ValueError):
        make_chart_id("tc", -1)


# ---------------------------------------------------------------------------
# ChartRegistry
# ---------------------------------------------------------------------------


def _sample_payload(title: str = "t") -> ChartPayload:
    return ChartPayload(
        nodes=[ChartNode(id="n1", name="X", category="c")],
        edges=[],
        meta=ChartMeta(title=title),
    )


def test_registry_register_and_get_roundtrip():
    reg = ChartRegistry()
    cid = reg.register(tool_call_id="tc1", payload=_sample_payload("first"))
    assert cid == "tc1:0"
    assert reg.get(cid) is not None
    assert reg.get(cid).meta.title == "first"


def test_registry_repeated_registration_last_write_wins():
    reg = ChartRegistry()
    reg.register(tool_call_id="tc1", payload=_sample_payload("first"))
    reg.register(tool_call_id="tc1", payload=_sample_payload("second"))
    assert reg.get("tc1:0").meta.title == "second"
    assert len(reg) == 1


def test_registry_multiple_charts_indexed():
    reg = ChartRegistry()
    a = reg.register(tool_call_id="tc1", payload=_sample_payload("a"), chart_index=0)
    b = reg.register(tool_call_id="tc1", payload=_sample_payload("b"), chart_index=1)
    assert a == "tc1:0"
    assert b == "tc1:1"
    assert reg.registered_ids() == {"tc1:0", "tc1:1"}


# ---------------------------------------------------------------------------
# replace_chart_placeholders (§7.3 timing)
# ---------------------------------------------------------------------------


def test_replace_swaps_registered_placeholder_for_fenced_block():
    reg = ChartRegistry()
    reg.register(tool_call_id="tc", payload=_sample_payload("figure"))

    md = "以下是能力图：\n\n[[CHART:tc:0]]\n\n继续阅读。"
    result = replace_chart_placeholders(md, reg)

    assert "[[CHART:" not in result.text
    assert "```chart:echarts" in result.text
    # Extract the JSON body to confirm structure survived the round-trip.
    body_start = result.text.index("```chart:echarts\n") + len("```chart:echarts\n")
    body_end = result.text.index("\n```", body_start)
    body = json.loads(result.text[body_start:body_end])
    assert body["meta"]["title"] == "figure"
    assert body["type"] == "graph"
    assert result.hallucination_ids == []
    assert result.unused_ids == []


def test_replace_records_hallucination_when_chart_id_unregistered():
    """Composer emitting a chart_id we never staged is treated as a
    hallucination (§7.3): placeholder kept verbatim, id recorded."""
    reg = ChartRegistry()
    reg.register(tool_call_id="tc", payload=_sample_payload("real"))

    md = "参考图 [[CHART:tc:0]] 与 [[CHART:ghost:0]]。"
    result = replace_chart_placeholders(md, reg)

    assert "[[CHART:ghost:0]]" in result.text  # kept for review
    assert "```chart:echarts" in result.text   # real chart still replaced
    assert result.hallucination_ids == ["ghost:0"]
    # A registered chart that WAS referenced doesn't count as unused.
    assert result.unused_ids == []


def test_replace_records_unused_registered_charts():
    reg = ChartRegistry()
    reg.register(tool_call_id="tc", payload=_sample_payload("used"), chart_index=0)
    reg.register(tool_call_id="tc", payload=_sample_payload("unused"), chart_index=1)

    md = "只引用第一张：[[CHART:tc:0]]"
    result = replace_chart_placeholders(md, reg)

    assert result.hallucination_ids == []
    assert result.unused_ids == ["tc:1"]


def test_replace_deduplicates_repeated_hallucinations():
    reg = ChartRegistry()
    md = "[[CHART:ghost:0]] and again [[CHART:ghost:0]]"
    result = replace_chart_placeholders(md, reg)
    assert result.hallucination_ids == ["ghost:0"]  # not ["ghost:0", "ghost:0"]


def test_placeholder_regex_matches_only_bracketed_form():
    """CHART: prefix without brackets shouldn't accidentally match — the
    Composer prompt controls the exact form, but the regex must be strict
    so free-form Composer text mentioning `CHART:` doesn't get parsed."""
    assert _PLACEHOLDER_RE.findall("CHART:x") == []
    assert _PLACEHOLDER_RE.findall("[[CHART:x:0]]") == ["x:0"]
    assert _PLACEHOLDER_RE.findall("[[chart:x:0]]") == []  # lowercase not matched


def test_fence_for_uses_utf8_and_indented_json():
    payload = _sample_payload("跨境电商图")
    fence = _fence_for("tc:0", payload)
    assert fence.startswith("```chart:echarts\n")
    assert fence.endswith("\n```")
    assert "跨境电商图" in fence  # ensure_ascii=False path
