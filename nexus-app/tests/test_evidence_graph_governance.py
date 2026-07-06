from __future__ import annotations

from nexus_app.evidence_graph import GraphChunkCandidate, GraphFactCandidate, govern_graph_candidates


def _chunk(chunk_id: str, index: int, heading: str = "第一章") -> GraphChunkCandidate:
    return GraphChunkCandidate(
        chunk_id=chunk_id,
        normalized_ref_id="ref-governance",
        chunk_index=index,
        knowledge_type_code="document_semantic_chunk",
        anchor_role="body",
        extractor_name="BodyLLMExtractor",
        extraction_method="llm",
        content=f"{heading} 内容 {index}",
        source_block_ids=[f"b{index}"],
        locator={
            "page_start": index,
            "page_end": index,
            "heading_path": [{"level": 1, "title": heading}],
            "blocks": [{"block_id": f"b{index}", "page": index}],
        },
        chunk_metadata={"anchor_role": "body", "heading_path": [heading]},
    )


def _fact(
    *,
    chunk_id: str,
    fact_type: str = "policy_fact",
    subject_name: str = "政策A",
    predicate: str = "REQUIRES",
    object_literal: str = "重点任务",
    confidence: float = 0.88,
    qualifiers=None,
) -> GraphFactCandidate:
    return GraphFactCandidate.model_validate({
        "source_chunk_id": chunk_id,
        "profile": "policy_document",
        "anchor_role": "body",
        "extractor_name": "BodyLLMExtractor",
        "extraction_method": "llm",
        "fact_type": fact_type,
        "subject": {"type": "Policy", "name": subject_name},
        "predicate": predicate,
        "object_literal": object_literal,
        "qualifiers": qualifiers or {},
        "evidence_text": f"{subject_name}{predicate}{object_literal}",
        "confidence": confidence,
    })


def test_govern_graph_candidates_filters_weak_local_mentions():
    chunk = _chunk("chunk-1", 1)
    strong = _fact(
        chunk_id=chunk.chunk_id,
        fact_type="requirement_fact",
        predicate="REQUIRES",
        object_literal="建设重点任务体系",
    )
    weak = _fact(
        chunk_id=chunk.chunk_id,
        fact_type="entity_mention",
        subject_name="电子商务",
        predicate="MENTIONS",
        object_literal="发展",
        confidence=0.8,
    )

    result = govern_graph_candidates([strong, weak], chunk_candidates=[chunk])

    assert [item.subject.name for item in result.accepted] == ["政策A"]
    assert len(result.rejected) == 1
    assert result.quality_summary["weak_local_mention_candidates"] == 1
    assert result.quality_summary["rejected_by_reason"]["weak_local_mention"] == 1


def test_govern_graph_candidates_enriches_context_qualifiers_and_metrics():
    chunk1 = _chunk("chunk-1", 1)
    chunk2 = _chunk("chunk-2", 2)
    fact = _fact(
        chunk_id=chunk1.chunk_id,
        fact_type="finding_fact",
        predicate="SUPPORTS",
        object_literal="政策A提出重点任务并由后续章节展开",
        qualifiers={
            "evidence_chunk_ids": [chunk1.chunk_id, chunk2.chunk_id],
            "context_for_chunk_ids": [chunk1.chunk_id, chunk2.chunk_id],
            "context_role": "finding",
        },
        confidence=0.91,
    )

    result = govern_graph_candidates([fact], chunk_candidates=[chunk1, chunk2])

    assert len(result.accepted) == 1
    accepted = result.accepted[0]
    assert accepted.qualifiers["graph_context_role"] == "finding"
    assert accepted.qualifiers["graph_context_relation"] == "summary_of"
    assert accepted.qualifiers["graph_context_priority"] >= accepted.qualifiers["graph_salience"]
    assert accepted.qualifiers["graph_context_reason"].startswith("finding fact provides")
    assert accepted.qualifiers["graph_salience"] >= 0.7
    assert accepted.qualifiers["context_for_chunk_ids"] == ["chunk-1", "chunk-2"]
    assert accepted.qualifiers["context_heading_paths"] == [["第一章"]]
    assert result.quality_summary["multi_chunk_fact_ratio"] == 1.0
    assert result.quality_summary["single_chunk_fact_ratio"] == 0.0
    assert result.quality_summary["context_link_count"] == 1
    assert result.quality_summary["facts_per_source_chunk_avg"] == 0.5
    assert result.quality_summary["chunk_context_links"] == [
        {
            "chunk_id": "chunk-1",
            "source_chunk_id": "chunk-1",
            "candidate_id": accepted.candidate_id,
            "fact_type": "finding_fact",
            "subject": "政策A",
            "predicate": "SUPPORTS",
            "context_role": "finding",
            "context_relation": "summary_of",
            "priority": accepted.qualifiers["graph_context_priority"],
            "reason": accepted.qualifiers["graph_context_reason"],
            "evidence_chunk_ids": ["chunk-1", "chunk-2"],
        },
        {
            "chunk_id": "chunk-2",
            "source_chunk_id": "chunk-1",
            "candidate_id": accepted.candidate_id,
            "fact_type": "finding_fact",
            "subject": "政策A",
            "predicate": "SUPPORTS",
            "context_role": "finding",
            "context_relation": "summary_of",
            "priority": accepted.qualifiers["graph_context_priority"],
            "reason": accepted.qualifiers["graph_context_reason"],
            "evidence_chunk_ids": ["chunk-1", "chunk-2"],
        },
    ]


def test_govern_graph_candidates_limits_over_fragmented_single_chunk_output():
    chunk = _chunk("chunk-1", 1)
    facts = [
        _fact(
            chunk_id=chunk.chunk_id,
            subject_name=f"政策{i}",
            predicate="REQUIRES",
            object_literal=f"重点任务{i}",
        )
        for i in range(5)
    ]

    result = govern_graph_candidates(
        facts,
        chunk_candidates=[chunk],
        max_facts_per_source_chunk=2,
    )

    assert len(result.accepted) == 2
    assert len(result.rejected) == 3
    assert result.quality_summary["per_chunk_overrun_candidates"] == 3
    assert result.quality_summary["top_chunks_by_fact_count"] == [
        {"chunk_id": "chunk-1", "fact_count": 2},
    ]
