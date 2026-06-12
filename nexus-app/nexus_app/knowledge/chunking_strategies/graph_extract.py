"""Tier-C: Graph extraction strategy for knowledge graphs."""
# P1 TODO: entity disambiguation, relation strength scoring, Neo4j integration

from __future__ import annotations

import re
from typing import Any

from nexus_app.enums import ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk, resolve_blocks_for_span
from nexus_app.knowledge.registry import register_strategy
from nexus_app.models import KnowledgeChunk


@register_strategy("graph_extract")
class GraphExtractStrategy:
    """Extract (subject, predicate, object) triples from content."""

    def __init__(self, config: dict[str, Any]):
        self.node_types = config.get("node_types", [])
        self.relation_types = config.get("relation_types", [])

    def chunk(
        self,
        content: str,
        emission: dict[str, Any],
        kt_config: Any,
        normalized_ref_id: str,
        content_blocks: list[dict[str, Any]] | None = None,
    ) -> list[KnowledgeChunk]:
        triples = self._extract_triples(content)
        max_chunks = kt_config.max_chunks_per_unit
        chunks: list[KnowledgeChunk] = []

        # Stage 2.4: each triple is a concept-level statement; its evidence
        # naturally spans multiple blocks. The locator carries:
        #   primary: the block(s) containing the line where the relation was
        #            stated (via md_char_range overlap on the line span)
        #   evidence: blocks whose text mentions the subject or object exactly
        # The aggregated source_blocks union is the concept's "supporting set".
        # We also store the primary vs evidence partition in extra_metadata so
        # downstream UI can prioritise the primary citation.
        for i, (triple, line_span) in enumerate(triples):
            if len(chunks) >= max_chunks:
                break
            primary = resolve_blocks_for_span(
                content_blocks, line_span, doc_fallback=None,
            ) or []
            evidence = self._collect_concept_evidence(
                content_blocks, triple, exclude_ids={
                    b.get("block_id") for b in primary if b.get("block_id")
                },
            )
            combined = self._dedup_blocks(primary + evidence)
            # Fall back to whole-document blocks if both primary and evidence
            # are empty (no md_char_range, or content_blocks is None).
            if not combined:
                combined = content_blocks or None
            extra: dict[str, Any] = dict(triple)
            extra["primary_block_ids"] = [
                b["block_id"] for b in primary if b.get("block_id")
            ]
            extra["evidence_block_ids"] = [
                b["block_id"] for b in evidence if b.get("block_id")
            ]
            chunks.append(build_chunk(
                normalized_ref_id, emission, kt_config,
                chunk_type=ChunkType.GRAPH_NODE,
                index=i,
                content=f"{triple['subject']} -[{triple['predicate']}]-> {triple['object']}",
                extra_metadata=extra,
                source_blocks=combined,
            ))

        return chunks

    def _extract_triples(
        self, content: str,
    ) -> list[tuple[dict[str, str], tuple[int, int]]]:
        """Heuristic triple extraction with per-line spans.

        Returns ``[(triple, (line_start, line_end))]`` where the span covers
        the source line in ``content`` (used to identify the primary block
        via md_char_range overlap).
        """
        patterns = [
            r"(.+?)\s*[-—→]+\s*\[(.+?)\]\s*[-—→]+\s*(.+)",
            r"(.+?)\s+(?:包含|依赖|先修|对应|应用)\s+(.+)",
        ]
        out: list[tuple[dict[str, str], tuple[int, int]]] = []
        cursor = 0
        for raw_line in content.split("\n"):
            line_len = len(raw_line)
            line_start = cursor
            line_end = cursor + line_len
            stripped = raw_line.strip()
            if not stripped:
                cursor = line_end + 1
                continue
            for pat in patterns:
                m = re.match(pat, stripped)
                if not m:
                    continue
                groups = m.groups()
                if len(groups) == 3:
                    triple = {
                        "subject": groups[0].strip(),
                        "predicate": groups[1].strip(),
                        "object": groups[2].strip(),
                    }
                elif len(groups) == 2:
                    triple = {
                        "subject": groups[0].strip(),
                        "predicate": "关联",
                        "object": groups[1].strip(),
                    }
                else:
                    continue
                out.append((triple, (line_start, line_end)))
                break
            cursor = line_end + 1
        return out

    def _collect_concept_evidence(
        self,
        content_blocks: list[dict[str, Any]] | None,
        triple: dict[str, str],
        *,
        exclude_ids: set[str],
        max_evidence_per_concept: int = 5,
    ) -> list[dict[str, Any]]:
        """Find blocks (other than primary) that mention subject or object.

        Bounded by ``max_evidence_per_concept`` per concept to prevent runaway
        evidence on common terms. Substring match — case-insensitive ASCII,
        verbatim CJK (no normalisation).
        """
        if not content_blocks:
            return []
        out: list[dict[str, Any]] = []
        seen: set[str] = set(exclude_ids)
        for concept in (triple.get("subject", ""), triple.get("object", "")):
            if not concept:
                continue
            count = 0
            for block in content_blocks:
                bid = block.get("block_id")
                if not bid or bid in seen:
                    continue
                text = block.get("text") or block.get("content") or ""
                if concept in text:
                    out.append(block)
                    seen.add(bid)
                    count += 1
                    if count >= max_evidence_per_concept:
                        break
        return out

    @staticmethod
    def _dedup_blocks(
        blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for b in blocks:
            bid = b.get("block_id")
            if not bid or bid in seen:
                continue
            seen.add(bid)
            out.append(b)
        return out
