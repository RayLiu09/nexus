"""Tier-B: Process step extraction strategy."""

from __future__ import annotations

import re
from typing import Any

from nexus_app.enums import ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk, resolve_blocks_for_span
from nexus_app.knowledge.registry import register_strategy
from nexus_app.models import KnowledgeChunk


@register_strategy("process_step_extract")
class ProcessStepExtractStrategy:
    """Extract process steps from procedural documents."""

    def __init__(self, config: dict[str, Any]):
        self.step_indicators = config.get("step_indicators", ["步骤", "阶段", "Step"])

    def chunk(
        self,
        content: str,
        emission: dict[str, Any],
        kt_config: Any,
        normalized_ref_id: str,
        content_blocks: list[dict[str, Any]] | None = None,
    ) -> list[KnowledgeChunk]:
        steps = self._split_by_steps(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        for i, (title, text, span) in enumerate(steps):
            if len(chunks) >= max_chunks:
                break
            src = resolve_blocks_for_span(
                content_blocks, span, doc_fallback=content_blocks,
            )
            chunks.append(build_chunk(
                normalized_ref_id, emission, kt_config,
                chunk_type=ChunkType.PROCESS_STEP,
                index=i,
                content=text,
                extra_metadata={"step_title": title, "step_index": i},
                source_blocks=src,
            ))

        return chunks

    def _split_by_steps(
        self, content: str,
    ) -> list[tuple[str, str, tuple[int, int]]]:
        """Split content by step indicators; return (title, text, span).

        Span is the character range in ``content`` for reverse-mapping to
        normalized_document blocks via md_char_range.
        """
        pattern = "|".join(re.escape(ind) for ind in self.step_indicators)
        regex = rf"(?:^|\n)\s*(?:({pattern})\s*\d*[:：.、]?\s*)(.*?)(?=\n\s*(?:{pattern})\s*\d*[:：.、]|\Z)"
        out: list[tuple[str, str, tuple[int, int]]] = []
        for m in re.finditer(regex, content, re.DOTALL):
            title, text = m.group(1).strip(), m.group(2).strip()
            if text:
                out.append((title, text, m.span()))
        if out:
            return out
        # Paragraph fallback: span = location of each paragraph in content.
        fallback: list[tuple[str, str, tuple[int, int]]] = []
        cursor = 0
        idx = 0
        for raw in content.split("\n\n"):
            stripped = raw.strip()
            if stripped:
                # `raw` may start with whitespace stripped during strip(); locate
                # the actual stripped occurrence inside the raw fragment.
                offset = raw.find(stripped)
                start = cursor + offset
                end = start + len(stripped)
                fallback.append((f"段落{idx+1}", stripped, (start, end)))
                idx += 1
            cursor += len(raw) + 2  # +2 for the "\n\n" separator consumed by split
        return fallback
