"""Knowledge Pipeline service — entry point for processing emissions."""

from __future__ import annotations

from typing import Any

from nexus_app.knowledge.config_loader import get_knowledge_type_config
from nexus_app.knowledge.router import route_and_chunk
from nexus_app.models import KnowledgeChunk

import nexus_app.knowledge.chunking_strategies.structured_decompose  # noqa: F401
import nexus_app.knowledge.chunking_strategies.qa_extract  # noqa: F401
import nexus_app.knowledge.chunking_strategies.process_step_extract  # noqa: F401
import nexus_app.knowledge.chunking_strategies.indicator_decompose  # noqa: F401
import nexus_app.knowledge.chunking_strategies.case_decompose  # noqa: F401
import nexus_app.knowledge.chunking_strategies.graph_extract  # noqa: F401
import nexus_app.knowledge.chunking_strategies.tag_decompose  # noqa: F401
import nexus_app.knowledge.chunking_strategies.row_decompose  # noqa: F401


def run_knowledge_pipeline(
    content: str,
    knowledge_emissions: list[dict[str, Any]],
    normalized_ref_id: str,
    content_blocks: list[dict[str, Any]] | None = None,
    *,
    record_body: dict[str, Any] | list[Any] | None = None,
) -> list[KnowledgeChunk]:
    """Process all emissions for a normalized_asset_ref, return all produced chunks.

    Args:
        content_blocks: Optional list of ``normalized_document.blocks[]``. When
            provided, strategies that have not yet implemented block-level
            mapping (Stage 2) will pass the full list to ``build_chunk`` so
            each produced chunk carries at least a document-level locator
            (page span + raw_object jump-back). Pass None for record-pipeline
            inputs — chunks then carry no locator, matching the contract for
            ``normalized_type=record``.
        record_body: Optional ``payload.record_body`` for record-pipeline
            refs. Row-oriented strategies (``row_decompose``) read this
            directly because ``content`` may be the body_markdown rendering
            (B5.3) rather than the structured JSON. None for document
            pipelines — those strategies operate on ``content`` /
            ``content_blocks`` alone.
    """
    all_chunks: list[KnowledgeChunk] = []

    for emission in knowledge_emissions:
        code = emission["code"]
        kt_config = get_knowledge_type_config(code)
        chunks = route_and_chunk(
            content, emission, kt_config, normalized_ref_id,
            content_blocks=content_blocks,
            record_body=record_body,
        )
        all_chunks.extend(chunks)

    return all_chunks
