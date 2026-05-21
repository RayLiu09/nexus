"""Tier-A: Structured decompose strategy for talent_training_dataset."""

from __future__ import annotations

import re
from typing import Any

from nexus_app.enums import ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk
from nexus_app.knowledge.registry import register_strategy
from nexus_app.models import KnowledgeChunk


@register_strategy("structured_decompose")
class StructuredDecomposeStrategy:
    """Decompose document into predefined fields, then chunk each field independently."""

    def __init__(self, config: dict[str, Any]):
        self.fields = config.get("decompose_fields", [])
        self.field_chunk_size = config.get("field_chunk_size", 256)
        self.field_overlap = config.get("field_overlap", 32)

    def chunk(
        self,
        content: str,
        emission: dict[str, Any],
        kt_config: Any,
        normalized_ref_id: str,
    ) -> list[KnowledgeChunk]:
        field_map = self._decompose_to_fields(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        for field_name, field_text in field_map.items():
            if not field_text.strip():
                continue
            windows = self._sliding_window(field_text)
            for window_idx, text in enumerate(windows):
                if len(chunks) >= max_chunks:
                    break
                chunks.append(build_chunk(
                    normalized_ref_id, emission, kt_config,
                    chunk_type=ChunkType.STRUCTURED_FIELD,
                    index=len(chunks),
                    content=text,
                    extra_metadata={
                        "field_name": field_name,
                        "field_chunk_index": window_idx,
                    },
                ))
            if len(chunks) >= max_chunks:
                if chunks:
                    chunks[-1].chunk_metadata["truncated"] = True
                break

        return chunks

    def _decompose_to_fields(self, content: str) -> dict[str, str]:
        """Split content by field headings defined in config."""
        field_map: dict[str, str] = {}
        if not self.fields:
            field_map["_full"] = content
            return field_map

        pattern = "|".join(re.escape(f) for f in self.fields)
        parts = re.split(rf"(?:^|\n)\s*({pattern})\s*[:：]?\s*\n?", content)

        current_field = "_preamble"
        for part in parts:
            stripped = part.strip()
            if stripped in self.fields:
                current_field = stripped
                if current_field not in field_map:
                    field_map[current_field] = ""
            else:
                field_map.setdefault(current_field, "")
                field_map[current_field] += part

        field_map.pop("_preamble", None)

        for field in self.fields:
            if field not in field_map:
                field_map[field] = ""

        return field_map

    def _sliding_window(self, text: str) -> list[str]:
        """Split text into overlapping windows by character count."""
        if len(text) <= self.field_chunk_size:
            return [text] if text.strip() else []

        windows: list[str] = []
        start = 0
        while start < len(text):
            end = start + self.field_chunk_size
            window = text[start:end]
            if window.strip():
                windows.append(window)
            if end >= len(text):
                break
            start = end - self.field_overlap

        return windows
