"""Bounded RAG projection for a ``talent_training_plan.v1`` document.

The plan domain tables and deterministic graph projections remain authoritative
for identity, filters, courses, positions, and certificates.  This strategy
only indexes high-value narrative units for semantic retrieval and source
citation; it never reads raw parser output.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from nexus_app.enums import ChunkType, ChunkingStrategy
from nexus_app.knowledge.chunk_builder import build_chunk
from nexus_app.knowledge.registry import register_strategy
from nexus_app.models import KnowledgeChunk
from nexus_app.talent_training_plan.extractor import sanitize_courses


_SPEC_LABELS = {
    "abilities": "能力要求",
    "knowledge_requirements": "知识要求",
    "qualities": "素质要求",
}
_DEFAULT_SUPPLEMENTARY_HEADINGS = ("入学要求", "实践要求", "实训要求", "教学进程", "实施保障", "毕业要求")


@register_strategy("talent_training_plan_decompose")
class TalentTrainingPlanDecomposeStrategy:
    """Project only the narrative complement of structured plan retrieval."""

    def __init__(self, config: dict[str, Any]):
        configured = config.get("include_semantic_units") or []
        self.include = set(configured) if configured else {
            "training_goal", "training_specification", "position_capability", "course", "supplementary_section",
        }
        self.narrative_size = max(300, int(config.get("narrative_chunk_size", 1200)))
        self.narrative_overlap = max(0, min(int(config.get("narrative_chunk_overlap", 80)), self.narrative_size // 3))
        self.course_size = max(80, int(config.get("course_content_chunk_size", 900)))
        self.course_overlap = max(0, min(int(config.get("course_content_overlap", 64)), self.course_size // 3))
        headings = config.get("supplementary_headings") or _DEFAULT_SUPPLEMENTARY_HEADINGS
        self.supplementary_headings = tuple(str(value).strip() for value in headings if str(value).strip())

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
        plan = emission.get("talent_training_plan")
        if not isinstance(plan, dict):
            return []
        blocks = [block for block in (content_blocks or []) if isinstance(block, dict)]
        by_id = {str(block["block_id"]): block for block in blocks if block.get("block_id")}
        context = _plan_context(plan)
        chunks: list[KnowledgeChunk] = []

        def add(unit: str, text: str, source_blocks: list[dict[str, Any]] | None, metadata: dict[str, Any]) -> None:
            if unit not in self.include or not text.strip() or len(chunks) >= kt_config.max_chunks_per_unit:
                return
            pieces = _split_narrative(text.strip(), self.narrative_size, self.narrative_overlap)
            for part, piece in enumerate(pieces, 1):
                if len(chunks) >= kt_config.max_chunks_per_unit:
                    return
                chunks.append(build_chunk(
                    normalized_ref_id, emission, kt_config,
                    chunk_type=ChunkType.SEMANTIC_BLOCK,
                    chunking_strategy=ChunkingStrategy.TALENT_TRAINING_PLAN_DECOMPOSE,
                    index=len(chunks), content=piece, source_blocks=source_blocks,
                    anchor_role=f"talent_training_plan_{unit}",
                    extra_metadata={
                        "domain_model": "talent_training_plan.v1",
                        "domain_profile": "talent_training_plan.v1",
                        "semantic_unit": unit,
                        **context,
                        **metadata,
                        "semantic_part": part,
                        "semantic_parts": len(pieces),
                    },
                ))

        goal = _string(plan.get("training_goal"))
        if goal:
            add("training_goal", f"{context['plan_label']}。培养目标：\n{goal}", _section_blocks(blocks, "培养目标"), {})

        specification = plan.get("training_specification")
        if isinstance(specification, dict):
            for key, label in _SPEC_LABELS.items():
                items = _names(specification.get(key))
                if items:
                    add("training_specification", f"{context['plan_label']}。培养规格-{label}：\n" + "\n".join(f"- {item}" for item in items), _evidence_blocks(specification.get(key), by_id) or _section_blocks(blocks, "培养规格"), {"specification_category": key})

        if "position_capability" in self.include:
            career = plan.get("career_orientation")
            positions = career.get("positions") if isinstance(career, dict) else []
            for position in positions if isinstance(positions, list) else []:
                if not isinstance(position, dict):
                    continue
                name = _string(position.get("name"))
                skills = _names(position.get("skills"))
                domains = _names(position.get("learning_domains"))
                # A position label alone is a structured-filter concern.  A RAG
                # projection exists only for evidenced capability semantics.
                if not name or not (skills or domains):
                    continue
                lines = [f"{context['plan_label']}。岗位：{name}。"]
                if skills:
                    lines.append("岗位能力：" + "；".join(skills))
                if domains:
                    lines.append("对应学习领域：" + "；".join(domains))
                add("position_capability", "\n".join(lines), _evidence_blocks([position, *(_as_dicts(position.get("skills"))), *(_as_dicts(position.get("learning_domains")))], by_id), {"position_name": name, "skill_count": len(skills), "learning_domain_count": len(domains)})

        if "course" in self.include:
            for course in sanitize_courses(plan.get("courses")):
                name = _string(course.get("course_name"))
                objective = _string(course.get("course_objective"))
                course_content = _string(course.get("course_content"))
                if not name or not course_content:
                    continue
                prefix = _course_prefix(context, course, name, objective)
                pieces = _split_narrative(course_content, self.course_size, self.course_overlap)
                sources = _evidence_blocks([course], by_id) or _section_blocks(blocks, "课程")
                part_count = len(pieces)
                for part, piece in enumerate(pieces, 1):
                    suffix = "\n课程内容：" if part_count == 1 else f"\n课程内容（{part}/{part_count}）："
                    add("course", prefix + suffix + piece, sources, {"course_name": name, "course_code": _string(course.get("course_code")), "course_type": _string(course.get("course_type")) or "course", "curriculum_group": _string(course.get("curriculum_group")) or "unknown", "course_content_part": part, "course_content_parts": part_count, "skill_refs": _names(course.get("skill_refs"))})

        if "supplementary_section" in self.include:
            for heading, section_blocks in _supplementary_sections(blocks, self.supplementary_headings):
                text = "\n".join(_block_text(block) for block in section_blocks).strip()
                if text:
                    add("supplementary_section", f"{context['plan_label']}。章节：{heading}。\n{text}", section_blocks, {"section_title": heading})
        return chunks


def _plan_context(plan: dict[str, Any]) -> dict[str, str]:
    fields = {key: _string(plan.get(key)) for key in ("institution_name", "major_name", "major_code", "education_level", "study_duration")}
    label_bits = [value for value in (fields["institution_name"], fields["major_name"], f"专业代码{fields['major_code']}" if fields["major_code"] else None, fields["education_level"], fields["study_duration"]) if value]
    return {**{key: value for key, value in fields.items() if value}, "plan_label": "，".join(label_bits) or "人才培养方案"}


def _course_prefix(context: dict[str, str], course: dict[str, Any], name: str, objective: str | None) -> str:
    parts = [f"{context['plan_label']}。课程：{name}。"]
    for label, key in (("课程类别", "curriculum_group"), ("课程类型", "course_type")):
        value = _string(course.get(key))
        if value and value != "unknown":
            parts.append(f"{label}：{value}。")
    if objective:
        parts.append(f"课程目标：{objective}\n")
    return "".join(parts)


def _split_narrative(value: str, size: int, overlap: int) -> list[str]:
    if len(value) <= size:
        return [value]
    units = [item.strip() for item in re.split(r"(?<=[。！？；;])|\n+", value) if item.strip()]
    chunks: list[str] = []; current = ""
    for unit in units or [value]:
        if current and len(current) + len(unit) + 1 > size:
            chunks.append(current)
            current = (current[-overlap:] if overlap else "") + unit
        else:
            current += ("\n" if current else "") + unit
    if current:
        chunks.append(current)
    return chunks


def _supplementary_sections(blocks: list[dict[str, Any]], wanted: tuple[str, ...]) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    active: str | None = None; section: list[dict[str, Any]] = []
    for block in blocks:
        text = _block_text(block)
        is_heading = block.get("block_type") in {"heading", "title"}
        matched = next((heading for heading in wanted if heading in text), None) if is_heading else None
        if matched:
            if active and section:
                yield active, section
            active, section = matched, [block]
        elif is_heading and active:
            if section:
                yield active, section
            active, section = None, []
        elif active:
            section.append(block)
    if active and section:
        yield active, section


def _section_blocks(blocks: list[dict[str, Any]], marker: str) -> list[dict[str, Any]] | None:
    matched = [block for block in blocks if marker in _block_text(block)]
    return matched or None


def _evidence_blocks(items: Any, by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]] | None:
    ids: list[str] = []
    for item in items if isinstance(items, list) else [items]:
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence")
        if isinstance(evidence, dict):
            ids.extend(str(value) for value in evidence.get("block_ids", []) if value)
    found = [by_id[value] for value in dict.fromkeys(ids) if value in by_id]
    return found or None


def _as_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _names(value: Any) -> list[str]:
    output: list[str] = []
    for item in value if isinstance(value, list) else []:
        name = _string(item.get("name")) if isinstance(item, dict) else _string(item)
        if name and name not in output:
            output.append(name)
    return output


def _block_text(block: dict[str, Any]) -> str:
    return _string(block.get("text") or block.get("content")) or ""


def _string(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
