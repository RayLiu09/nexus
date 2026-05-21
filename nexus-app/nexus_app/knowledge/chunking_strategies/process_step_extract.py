"""Tier-B: Process step extraction strategy."""

from __future__ import annotations

import re
from typing import Any

from nexus_app.enums import ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk
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
    ) -> list[KnowledgeChunk]:
        steps = self._split_by_steps(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        for i, (title, text) in enumerate(steps):
            if len(chunks) >= max_chunks:
                break
            chunks.append(build_chunk(
                normalized_ref_id, emission, kt_config,
                chunk_type=ChunkType.PROCESS_STEP,
                index=i,
                content=text,
                extra_metadata={"step_title": title, "step_index": i},
            ))

        return chunks

    def _split_by_steps(self, content: str) -> list[tuple[str, str]]:
        """Split content by step indicator patterns."""
        pattern = "|".join(re.escape(ind) for ind in self.step_indicators)
        regex = rf"(?:^|\n)\s*(?:({pattern})\s*\d*[:：.、]?\s*)(.*?)(?=\n\s*(?:{pattern})\s*\d*[:：.、]|\Z)"
        matches = re.findall(regex, content, re.DOTALL)
        if matches:
            return [(m[0].strip(), m[1].strip()) for m in matches if m[1].strip()]
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        return [(f"段落{i+1}", p) for i, p in enumerate(paragraphs)]
