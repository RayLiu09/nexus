"""Tier-B: Indicator decompose strategy for evaluation standards."""

from __future__ import annotations

import re
from typing import Any

from nexus_app.enums import ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk
from nexus_app.knowledge.registry import register_strategy
from nexus_app.models import KnowledgeChunk


@register_strategy("indicator_decompose")
class IndicatorDecomposeStrategy:
    """Decompose evaluation indicator systems into leaf indicators."""

    def __init__(self, config: dict[str, Any]):
        self.indicator_fields = config.get("indicator_fields", ["维度", "指标", "权重", "评分标准"])

    def chunk(
        self,
        content: str,
        emission: dict[str, Any],
        kt_config: Any,
        normalized_ref_id: str,
    ) -> list[KnowledgeChunk]:
        indicators = self._extract_indicators(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        for i, ind in enumerate(indicators):
            if len(chunks) >= max_chunks:
                break
            rendered = self._render_indicator(ind)
            chunks.append(build_chunk(
                normalized_ref_id, emission, kt_config,
                chunk_type=ChunkType.INDICATOR,
                index=i,
                content=rendered,
                extra_metadata=ind,
            ))

        return chunks

    def _extract_indicators(self, content: str) -> list[dict[str, Any]]:
        """Heuristic extraction of indicator entries from tabular or structured text."""
        indicators: list[dict[str, Any]] = []
        lines = content.split("\n")
        current: dict[str, Any] = {}

        for line in lines:
            line = line.strip()
            if not line:
                if current:
                    indicators.append(current)
                    current = {}
                continue
            for field in self.indicator_fields:
                match = re.match(rf"{re.escape(field)}\s*[:：]\s*(.+)", line)
                if match:
                    current[field] = match.group(1).strip()
                    break

        if current:
            indicators.append(current)

        if not indicators:
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
            for p in paragraphs:
                indicators.append({"content": p})

        return indicators

    def _render_indicator(self, ind: dict[str, Any]) -> str:
        if "content" in ind:
            return ind["content"]
        parts = [f"{k}: {v}" for k, v in ind.items()]
        return "\n".join(parts)
