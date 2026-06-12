"""Tier-B: Indicator decompose strategy for evaluation standards."""

from __future__ import annotations

import re
from typing import Any

from nexus_app.enums import ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk, resolve_blocks_for_span
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
        content_blocks: list[dict[str, Any]] | None = None,
    ) -> list[KnowledgeChunk]:
        indicators = self._extract_indicators(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        for i, (ind, span) in enumerate(indicators):
            if len(chunks) >= max_chunks:
                break
            rendered = self._render_indicator(ind)
            src = resolve_blocks_for_span(
                content_blocks, span, doc_fallback=content_blocks,
            )
            chunks.append(build_chunk(
                normalized_ref_id, emission, kt_config,
                chunk_type=ChunkType.INDICATOR,
                index=i,
                content=rendered,
                extra_metadata=ind,
                source_blocks=src,
            ))

        return chunks

    def _extract_indicators(
        self, content: str,
    ) -> list[tuple[dict[str, Any], tuple[int, int]]]:
        """Heuristic extraction with per-indicator content spans.

        Walks ``content`` line-by-line maintaining a running byte cursor so
        each indicator carries the span covering its contributing lines —
        sufficient for reverse-mapping to source blocks via md_char_range.
        """
        indicators: list[tuple[dict[str, Any], tuple[int, int]]] = []
        current: dict[str, Any] = {}
        current_start: int | None = None
        current_end: int | None = None

        cursor = 0
        for line_no, raw_line in enumerate(content.split("\n")):
            line_len = len(raw_line)
            line_start = cursor
            line_end = cursor + line_len
            stripped = raw_line.strip()
            if not stripped:
                if current and current_start is not None and current_end is not None:
                    indicators.append((current, (current_start, current_end)))
                    current = {}
                    current_start = None
                    current_end = None
            else:
                for field in self.indicator_fields:
                    if re.match(rf"{re.escape(field)}\s*[:：]\s*(.+)", stripped):
                        m = re.match(
                            rf"{re.escape(field)}\s*[:：]\s*(.+)", stripped
                        )
                        current[field] = m.group(1).strip()
                        if current_start is None:
                            current_start = line_start
                        current_end = line_end
                        break
            # +1 for the "\n" stripped by split; trailing line has no "\n" but
            # we never read cursor past content end so the over-advance is harmless.
            cursor = line_end + 1

        if current and current_start is not None and current_end is not None:
            indicators.append((current, (current_start, current_end)))

        if not indicators:
            # Paragraph fallback: each non-empty "\n\n"-split paragraph becomes
            # one indicator. Track its span in `content`.
            cursor = 0
            for raw in content.split("\n\n"):
                stripped = raw.strip()
                if stripped:
                    offset = raw.find(stripped)
                    start = cursor + offset
                    end = start + len(stripped)
                    indicators.append(({"content": stripped}, (start, end)))
                cursor += len(raw) + 2  # +2 for "\n\n"

        return indicators

    def _render_indicator(self, ind: dict[str, Any]) -> str:
        if "content" in ind:
            return ind["content"]
        parts = [f"{k}: {v}" for k, v in ind.items()]
        return "\n".join(parts)
