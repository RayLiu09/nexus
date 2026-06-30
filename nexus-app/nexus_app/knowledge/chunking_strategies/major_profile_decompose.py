"""Section-level semantic chunks for `major_profile_knowledge`."""

from __future__ import annotations

from typing import Any

from nexus_app.enums import ChunkType, ChunkingStrategy
from nexus_app.knowledge.chunk_builder import build_chunk
from nexus_app.knowledge.registry import register_strategy
from nexus_app.models import KnowledgeChunk


@register_strategy("major_profile_decompose")
class MajorProfileDecomposeStrategy:
    """Create one semantic chunk per major profile business section."""

    def __init__(self, config: dict[str, Any]):
        self.include_sections = set(config.get("include_sections") or [])

    def chunk(
        self,
        content: str,
        emission: dict[str, Any],
        kt_config: Any,
        normalized_ref_id: str,
        content_blocks: list[dict[str, Any]] | None = None,
        *,
        record_body: dict[str, Any] | list[Any] | None = None,  # noqa: ARG002
    ) -> list[KnowledgeChunk]:
        profile = emission.get("major_profile")
        if not isinstance(profile, dict):
            # run_knowledge_pipeline only passes emissions today. The normalized
            # payload is represented by content/content_blocks, so reconstruct
            # sections from block headings as a fallback.
            profile = _profile_from_blocks(content_blocks)
        blocks_by_id = {
            block.get("block_id"): block
            for block in (content_blocks or [])
            if isinstance(block.get("block_id"), str)
        }
        chunks: list[KnowledgeChunk] = []
        for one_profile in _profiles(profile):
            sections = one_profile.get("sections") if isinstance(one_profile, dict) else None
            if not isinstance(sections, list):
                continue
            major_code = one_profile.get("major_code")
            major_name = one_profile.get("major_name")
            education_level = one_profile.get("education_level")
            for section in sections:
                if not isinstance(section, dict):
                    continue
                key = str(section.get("section_key") or "").strip()
                if not key:
                    continue
                if self.include_sections and key not in self.include_sections:
                    continue
                section_text = str(section.get("text") or "").strip()
                if not section_text:
                    continue
                title = str(section.get("section_title") or key).strip()
                source_blocks = _source_blocks(section, blocks_by_id)
                chunks.append(build_chunk(
                    normalized_ref_id=normalized_ref_id,
                    emission=emission,
                    kt_config=kt_config,
                    chunk_type=ChunkType.SEMANTIC_BLOCK,
                    chunking_strategy=ChunkingStrategy.MAJOR_PROFILE_DECOMPOSE,
                    index=len(chunks),
                    content=_content(major_code, major_name, title, section_text),
                    source_blocks=source_blocks,
                    extra_metadata={
                        "domain": "major",
                        "domain_profile": "major_profile.v1",
                        "section_key": key,
                        "section_title": title,
                        "major_code": major_code,
                        "major_name": major_name,
                        "education_level": education_level,
                        "contains_structured_items": key in {
                            "occupation_oriented",
                            "ability_requirements",
                            "courses_and_training",
                            "certificates",
                            "continuation_majors",
                        },
                        "content_for_embedding": _embedding_text(
                            major_code, major_name, education_level, title, section_text
                        ),
                    },
                    anchor_role="major_profile_section",
                ))
        return chunks


def _profiles(profile: dict[str, Any]) -> list[dict[str, Any]]:
    raw_profiles = profile.get("profiles")
    if isinstance(raw_profiles, list):
        profiles = [item for item in raw_profiles if isinstance(item, dict)]
        if profiles:
            return profiles
    return [profile]


def _content(
    major_code: Any,
    major_name: Any,
    section_title: str,
    section_text: str,
) -> str:
    prefix_parts = []
    if major_name:
        prefix_parts.append(str(major_name))
    if major_code:
        prefix_parts.append(f"（{major_code}）")
    prefix = "".join(prefix_parts)
    if prefix:
        return f"专业：{prefix}。章节：{section_title}。\n{section_text}"
    return f"章节：{section_title}。\n{section_text}"


def _embedding_text(
    major_code: Any,
    major_name: Any,
    education_level: Any,
    section_title: str,
    section_text: str,
) -> str:
    parts = [
        str(v)
        for v in (major_name, major_code, education_level, section_title, section_text)
        if v
    ]
    return " ".join(parts)


def _source_blocks(
    section: dict[str, Any],
    blocks_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]] | None:
    ids = section.get("source_block_ids")
    if not isinstance(ids, list):
        return None
    blocks = [
        blocks_by_id[block_id]
        for block_id in ids
        if isinstance(block_id, str) and block_id in blocks_by_id
    ]
    return blocks or None


def _profile_from_blocks(content_blocks: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not content_blocks:
        return {"sections": []}
    try:
        from nexus_app.major_profile.extractor import extract
        return extract({
            "content_type": "document",
            "title": "",
            "blocks": content_blocks,
            "body_markdown": "\n".join(
                str(block.get("text") or "") for block in content_blocks
            ),
        }) or {"sections": []}
    except Exception:
        return {"sections": []}


__all__ = ["MajorProfileDecomposeStrategy"]
