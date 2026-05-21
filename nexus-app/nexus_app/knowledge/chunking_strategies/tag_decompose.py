"""Tier-C: Tag decompose strategy for skill tag libraries."""
# P1 TODO: tag hierarchy merging, synonym normalization

from __future__ import annotations

import re
from typing import Any

from nexus_app.enums import ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk
from nexus_app.knowledge.registry import register_strategy
from nexus_app.models import KnowledgeChunk


@register_strategy("tag_decompose")
class TagDecomposeStrategy:
    """Decompose tag/skill libraries into individual tag entries."""

    def __init__(self, config: dict[str, Any]):
        self.tag_fields = config.get("tag_fields", ["标签名", "同义词", "分类", "层级", "描述"])

    def chunk(
        self,
        content: str,
        emission: dict[str, Any],
        kt_config: Any,
        normalized_ref_id: str,
    ) -> list[KnowledgeChunk]:
        tags = self._extract_tags(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        for i, tag in enumerate(tags):
            if len(chunks) >= max_chunks:
                break
            name = tag.get("标签名", tag.get("name", f"tag_{i}"))
            chunks.append(build_chunk(
                normalized_ref_id, emission, kt_config,
                chunk_type=ChunkType.TAG,
                index=i,
                content=name,
                extra_metadata=tag,
            ))

        return chunks

    def _extract_tags(self, content: str) -> list[dict[str, str]]:
        """Heuristic tag extraction from structured text."""
        tags: list[dict[str, str]] = []
        current: dict[str, str] = {}

        for line in content.split("\n"):
            line = line.strip()
            if not line:
                if current:
                    tags.append(current)
                    current = {}
                continue
            for field in self.tag_fields:
                match = re.match(rf"{re.escape(field)}\s*[:：]\s*(.+)", line)
                if match:
                    current[field] = match.group(1).strip()
                    break
            else:
                if not current:
                    current["标签名"] = line

        if current:
            tags.append(current)

        return tags
