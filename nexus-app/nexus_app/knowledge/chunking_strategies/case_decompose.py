"""Tier-C: Case decompose strategy for case libraries."""
# P1 TODO: multi-modal case support (images/video), deeper section parsing

from __future__ import annotations

import re
from typing import Any

from nexus_app.enums import ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk, resolve_blocks_for_span
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
        content_blocks: list[dict[str, Any]] | None = None,
    ) -> list[KnowledgeChunk]:
        sectioned = self._split_by_sections(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        for section_name, section_text, span in sectioned:
            if not section_text.strip():
                continue
            if len(chunks) >= max_chunks:
                break
            src = resolve_blocks_for_span(
                content_blocks, span, doc_fallback=content_blocks,
            )
            chunks.append(build_chunk(
                normalized_ref_id, emission, kt_config,
                chunk_type=ChunkType.CASE_SECTION,
                index=len(chunks),
                content=section_text[:self.section_chunk_size],
                extra_metadata={"section_name": section_name},
                source_blocks=src,
            ))

        return chunks

    def _split_by_sections(
        self, content: str,
    ) -> list[tuple[str, str, tuple[int, int]]]:
        """Locate configured section headings via finditer, then derive each
        section body as the slice between consecutive heading starts.

        Returns ``[(section_name, section_text, (body_start, body_end))]``.
        Sections without a heading match are omitted; intro text before the
        first heading is dropped (mirrors the prior re.split-based behaviour).
        """
        if not self.sections:
            return []
        pattern = "|".join(re.escape(s) for s in self.sections)
        regex = rf"(?:^|\n)\s*({pattern})\s*[:：]?\s*\n?"
        heads: list[tuple[str, int, int]] = []  # (name, body_start, head_match_start)
        for m in re.finditer(regex, content):
            heads.append((m.group(1).strip(), m.end(), m.start()))

        out: list[tuple[str, str, tuple[int, int]]] = []
        for i, (name, body_start, _) in enumerate(heads):
            body_end = heads[i + 1][2] if i + 1 < len(heads) else len(content)
            body = content[body_start:body_end].strip()
            out.append((name, body, (body_start, body_end)))
        return out
