from __future__ import annotations

from nexus_app.evidence_graph import GraphChunkCandidate, group_graph_extraction_units


def _candidate(
    *,
    chunk_id: str,
    chunk_index: int,
    anchor_role: str = "body",
    extractor_name: str = "BodyLLMExtractor",
    extraction_method: str = "llm",
    content: str | None = None,
    heading_path=None,
) -> GraphChunkCandidate:
    locator = {"page_start": 1, "page_end": 1}
    metadata = {"anchor_role": anchor_role}
    if heading_path is not None:
        metadata["heading_path"] = heading_path
    return GraphChunkCandidate(
        chunk_id=chunk_id,
        normalized_ref_id="ref-1",
        chunk_index=chunk_index,
        knowledge_type_code="document_semantic_chunk",
        anchor_role=anchor_role,
        extractor_name=extractor_name,
        extraction_method=extraction_method,
        content=content or f"第 {chunk_index} 段内容。",
        source_block_ids=[f"b{chunk_index}"],
        locator=locator,
        chunk_metadata=metadata,
    )


def test_groups_body_llm_chunks_by_heading_path_from_metadata():
    units = group_graph_extraction_units(
        [
            _candidate(
                chunk_id="chunk-1",
                chunk_index=1,
                heading_path=[{"level": 1, "title": "第一章"}, {"level": 2, "title": "概念"}],
            ),
            _candidate(
                chunk_id="chunk-2",
                chunk_index=2,
                heading_path=[{"level": 1, "title": "第一章"}, {"level": 2, "title": "概念"}],
            ),
            _candidate(
                chunk_id="chunk-3",
                chunk_index=3,
                heading_path=[{"level": 1, "title": "第一章"}, {"level": 2, "title": "概念"}],
            ),
        ],
        graph_profile="report_document",
    )

    assert len(units) == 1
    unit = units[0]
    assert unit.unit_type == "section"
    assert unit.chunk_ids == ("chunk-1", "chunk-2", "chunk-3")
    assert unit.primary_chunk_id == "chunk-1"
    assert unit.heading_path == ("第一章", "概念")
    assert "[chunk_id=chunk-1; chunk_index=1; anchor_role=body]" in unit.content


def test_splits_long_body_sections_with_overlap():
    units = group_graph_extraction_units(
        [
            _candidate(chunk_id=f"chunk-{index}", chunk_index=index, heading_path=["章节"])
            for index in range(1, 27)
        ],
        graph_profile="report_document",
    )

    assert len(units) == 2
    assert units[0].chunk_ids == tuple(f"chunk-{index}" for index in range(1, 25))
    assert units[1].chunk_ids == tuple(f"chunk-{index}" for index in range(24, 27))
    assert units[1].unit_type == "sliding_window"


def test_body_grouping_requires_adjacent_chunks_even_with_same_heading():
    units = group_graph_extraction_units(
        [
            _candidate(chunk_id="chunk-1", chunk_index=1, heading_path=["章节"]),
            _candidate(chunk_id="chunk-3", chunk_index=3, heading_path=["章节"]),
        ],
        graph_profile="report_document",
    )

    assert len(units) == 2
    assert units[0].chunk_ids == ("chunk-1",)
    assert units[1].chunk_ids == ("chunk-3",)
    assert all(unit.unit_type == "section" for unit in units)


def test_non_body_rule_candidate_stays_single_chunk_with_raw_content():
    content = "发布时间: 2024.01\n部门: 商务部\n文件名: 政策A"
    units = group_graph_extraction_units(
        [
            _candidate(
                chunk_id="row-1",
                chunk_index=1,
                anchor_role="table_row",
                extractor_name="TableRowPolicyExtractor",
                extraction_method="rule",
                content=content,
            )
        ],
        graph_profile="policy_document",
    )

    assert len(units) == 1
    assert units[0].unit_type == "table_row"
    assert units[0].chunk_ids == ("row-1",)
    assert units[0].content == content
