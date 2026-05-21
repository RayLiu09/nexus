"""Tier-C: Case decompose strategy for case libraries."""
# P1 TODO: multi-modal case support (images/video), deeper section parsing

from __future__ import annotations

import re
from typing import Any

from nexus_app.enums import ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk
from nexus_app.knowledge.registry import register_strategy
from nexus_app.models import KnowledgeChunk


@register_strategy("case_decompose")
class CaseDecomposeStrategy:
    """Decompose case documents by predefined section headings."""

    def __init__(self, config: dict[str, Any]):
        self.sections = config.get("case_sections", ["背景", "问题", "解决方案", "效果", "反思"])
        self.section_chunk_size = config.get("section_chunk_size", 384)
        self.section_overlap = config.get("section_overlap", 32)

    def chunk(
        self,
        content: str,
        emission: dict[str, Any],
        kt_config: Any,
        normalized_ref_id: str,
    ) -> list[KnowledgeChunk]:
        sectioned = self._split_by_sections(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        for section_name, section_text in sectioned.items():
            if not section_text.strip():
                continue
            if len(chunks) >= max_chunks:
                break
            chunks.append(build_chunk(
                normalized_ref_id, emission, kt_config,
                chunk_type=ChunkType.CASE_SECTION,
                index=len(chunks),
                content=section_text[:self.section_chunk_size],
                extra_metadata={"section_name": section_name},
            ))

        return chunks

    def _split_by_sections(self, content: str) -> dict[str, str]:
        pattern = "|".join(re.escape(s) for s in self.sections)
        parts = re.split(rf"(?:^|\n)\s*({pattern})\s*[:：]?\s*\n?", content)
        result: dict[str, str] = {}
        current = "_intro"
        for part in parts:
            stripped = part.strip()
            if stripped in self.sections:
                current = stripped
                result.setdefault(current, "")
            else:
                result.setdefault(current, "")
                result[current] += part
        result.pop("_intro", None)
        return result
