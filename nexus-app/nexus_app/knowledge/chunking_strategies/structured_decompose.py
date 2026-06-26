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
        content_blocks: list[dict[str, Any]] | None = None,
        *,
        record_body: dict[str, Any] | list[Any] | None = None,  # noqa: ARG002 — protocol arg, unused here
    ) -> list[KnowledgeChunk]:
        field_map = self._decompose_to_fields(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        # Stage 2.1: heading-bounded mapping. Group blocks under each field
        # heading; all windows of one field share that field's block set.
        # Sub-window-level mapping requires md_char_range (Stage 2.2).
        field_block_map = self._group_blocks_by_field(content_blocks)
        doc_fallback = content_blocks or None

        for field_name, field_text in field_map.items():
            if not field_text.strip():
                continue
            windows = self._sliding_window(field_text)
            field_blocks = field_block_map.get(field_name) or doc_fallback
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
                    source_blocks=field_blocks,
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

    def _group_blocks_by_field(
        self,
        content_blocks: list[dict[str, Any]] | None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Walk blocks and group them under the most recent matching heading.

        A heading block whose text contains a configured field name opens a
        section; all subsequent non-heading blocks belong to that section.
        Encountering another field-named heading switches the active section.
        Blocks before the first matched heading and blocks under non-matching
        headings are dropped (we cannot attribute them to a known field).

        Returns: dict[field_name -> list[block]]. Empty when no blocks or no
        fields configured — callers should fall back to document-level locator.
        """
        if not content_blocks or not self.fields:
            return {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        current: str | None = None
        for block in content_blocks:
            btype = block.get("block_type")
            if btype in ("heading", "title"):
                text = (block.get("text") or "").strip()
                matched: str | None = None
                for f in self.fields:
                    if f and f in text:
                        matched = f
                        break
                if matched is not None:
                    current = matched
                    grouped.setdefault(current, [])
                    continue
                # Non-matching heading: keep accumulating under current section
            if current is not None:
                grouped.setdefault(current, []).append(block)
        return grouped

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
