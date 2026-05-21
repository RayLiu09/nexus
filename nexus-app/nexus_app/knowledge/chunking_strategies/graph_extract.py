"""Tier-C: Graph extraction strategy for knowledge graphs."""
# P1 TODO: entity disambiguation, relation strength scoring, Neo4j integration

from __future__ import annotations

import re
from typing import Any

from nexus_app.enums import ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk
from nexus_app.knowledge.registry import register_strategy
from nexus_app.models import KnowledgeChunk


@register_strategy("graph_extract")
class GraphExtractStrategy:
    """Extract (subject, predicate, object) triples from content."""

    def __init__(self, config: dict[str, Any]):
        self.node_types = config.get("node_types", [])
        self.relation_types = config.get("relation_types", [])

    def chunk(
        self,
        content: str,
        emission: dict[str, Any],
        kt_config: Any,
        normalized_ref_id: str,
    ) -> list[KnowledgeChunk]:
        triples = self._extract_triples(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        for i, triple in enumerate(triples):
            if len(chunks) >= max_chunks:
                break
            chunks.append(build_chunk(
                normalized_ref_id, emission, kt_config,
                chunk_type=ChunkType.GRAPH_NODE,
                index=i,
                content=f"{triple['subject']} -[{triple['predicate']}]-> {triple['object']}",
                extra_metadata=triple,
            ))

        return chunks

    def _extract_triples(self, content: str) -> list[dict[str, str]]:
        """Heuristic triple extraction from structured text."""
        triples: list[dict[str, str]] = []
        patterns = [
            r"(.+?)\s*[-—→]+\s*\[(.+?)\]\s*[-—→]+\s*(.+)",
            r"(.+?)\s+(?:包含|依赖|先修|对应|应用)\s+(.+)",
        ]
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            for pat in patterns:
                m = re.match(pat, line)
                if m:
                    groups = m.groups()
                    if len(groups) == 3:
                        triples.append({
                            "subject": groups[0].strip(),
                            "predicate": groups[1].strip(),
                            "object": groups[2].strip(),
                        })
                    elif len(groups) == 2:
                        triples.append({
                            "subject": groups[0].strip(),
                            "predicate": "关联",
                            "object": groups[1].strip(),
                        })
                    break
        return triples
