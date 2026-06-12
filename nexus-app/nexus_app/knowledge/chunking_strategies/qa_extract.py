"""Tier-B: QA pair extraction strategy."""

from __future__ import annotations

import re
from typing import Any

from nexus_app.enums import ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk, resolve_blocks_for_span
from nexus_app.knowledge.registry import register_strategy
from nexus_app.models import KnowledgeChunk


@register_strategy("qa_extract")
class QaExtractStrategy:
    """Extract question-answer pairs from content using heuristic patterns."""

    def __init__(self, config: dict[str, Any]):
        self.min_question_length = config.get("min_question_length", 5)
        self.min_answer_length = config.get("min_answer_length", 10)

    def chunk(
        self,
        content: str,
        emission: dict[str, Any],
        kt_config: Any,
        normalized_ref_id: str,
        content_blocks: list[dict[str, Any]] | None = None,
    ) -> list[KnowledgeChunk]:
        pairs = self._extract_qa_pairs(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        # Stage 2.2: each Q/A pair reverse-maps to source blocks via the
        # regex match span and the block md_char_range. Falls back to
        # document-level when no block overlaps (e.g. content_blocks is the
        # record-pipeline None).
        for i, (q, a, span) in enumerate(pairs):
            if len(chunks) >= max_chunks:
                break
            src = resolve_blocks_for_span(
                content_blocks, span, doc_fallback=content_blocks,
            )
            chunks.append(build_chunk(
                normalized_ref_id, emission, kt_config,
                chunk_type=ChunkType.QA_PAIR,
                index=i,
                content=f"Q: {q}\nA: {a}",
                extra_metadata={"question": q, "answer": a},
                source_blocks=src,
            ))

        return chunks

    def _extract_qa_pairs(self, content: str) -> list[tuple[str, str, tuple[int, int]]]:
        """Heuristic QA extraction with body_markdown spans.

        Each tuple is ``(question, answer, (match_start, match_end))`` where
        the span refers to character offsets in ``content`` — the same
        coordinate system the block md_char_range indexes into.
        """
        patterns = [
            r"[问Q][:：]\s*(.+?)\n[答A][:：]\s*(.+?)(?=\n[问Q][:：]|\Z)",
            r"(?:问题|Question)\s*\d*[:：]\s*(.+?)\n(?:答案|Answer)\s*\d*[:：]\s*(.+?)(?=\n(?:问题|Question)|\Z)",
        ]
        pairs: list[tuple[str, str, tuple[int, int]]] = []
        for pattern in patterns:
            for m in re.finditer(pattern, content, re.DOTALL):
                q, a = m.group(1).strip(), m.group(2).strip()
                if len(q) >= self.min_question_length and len(a) >= self.min_answer_length:
                    pairs.append((q, a, m.span()))
            if pairs:
                break
        return pairs
