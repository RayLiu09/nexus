"""Tier-B: QA pair extraction strategy."""

from __future__ import annotations

import re
from typing import Any

from nexus_app.enums import ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk
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
    ) -> list[KnowledgeChunk]:
        pairs = self._extract_qa_pairs(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        for i, (q, a) in enumerate(pairs):
            if len(chunks) >= max_chunks:
                break
            chunks.append(build_chunk(
                normalized_ref_id, emission, kt_config,
                chunk_type=ChunkType.QA_PAIR,
                index=i,
                content=f"Q: {q}\nA: {a}",
                extra_metadata={"question": q, "answer": a},
            ))

        return chunks

    def _extract_qa_pairs(self, content: str) -> list[tuple[str, str]]:
        """Heuristic QA extraction using common patterns."""
        patterns = [
            r"[问Q][:：]\s*(.+?)\n[答A][:：]\s*(.+?)(?=\n[问Q][:：]|\Z)",
            r"(?:问题|Question)\s*\d*[:：]\s*(.+?)\n(?:答案|Answer)\s*\d*[:：]\s*(.+?)(?=\n(?:问题|Question)|\Z)",
        ]
        pairs: list[tuple[str, str]] = []
        for pattern in patterns:
            matches = re.findall(pattern, content, re.DOTALL)
            for q, a in matches:
                q, a = q.strip(), a.strip()
                if len(q) >= self.min_question_length and len(a) >= self.min_answer_length:
                    pairs.append((q, a))
            if pairs:
                break
        return pairs
