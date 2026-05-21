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


def run_knowledge_pipeline(
    content: str,
    knowledge_emissions: list[dict[str, Any]],
    normalized_ref_id: str,
) -> list[KnowledgeChunk]:
    """Process all emissions for a normalized_asset_ref, return all produced chunks."""
    all_chunks: list[KnowledgeChunk] = []

    for emission in knowledge_emissions:
        code = emission["code"]
        kt_config = get_knowledge_type_config(code)
        chunks = route_and_chunk(content, emission, kt_config, normalized_ref_id)
        all_chunks.extend(chunks)

    return all_chunks
