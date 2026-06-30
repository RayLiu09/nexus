"""Deterministic extractor for Pipeline A `major_profile.v1` documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DOMAIN_PROFILE = "major_profile.v1"
EXTRACTOR_VERSION = "major_profile_extractor.v1"


SECTION_DEFS: dict[str, dict[str, Any]] = {
    "occupation_oriented": {
        "title": "职业面向",
        "aliases": ["职业面向", "面向职业", "就业面向", "岗位面向"],
    },
    "training_goal": {
        "title": "培养目标定位",
        "aliases": ["培养目标定位", "培养目标", "培养定位"],
    },
    "ability_requirements": {
        "title": "主要专业能力要求",
        "aliases": ["主要专业能力要求", "专业能力要求", "职业能力要求"],
    },
    "courses_and_training": {
        "title": "主要专业课程与实习实训",
        "aliases": ["主要专业课程与实习实训", "课程与实训", "课程设置"],
    },
    "certificates": {
        "title": "职业类证书举例",
        "aliases": ["职业类证书举例", "职业等级证书举例", "执业证书举例", "职业资格证书举例"],
    },
    "continuation_majors": {
        "title": "接续专业举例",
        "aliases": [
            "接续专业举例",
            "接续高职专科专业举例",
            "接续高职本科专业举例",
            "接续普通本科专业举例",
            "接续本科专业举例",
        ],
    },
}

_SUBSECTION_ALIASES = {
    "foundation": ["专业基础课程", "基础课程"],
    "core": ["专业核心课程", "核心课程"],
    "practice_training": ["实习实训", "实践教学", "实训项目"],
}


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    text: str
    blocks: list[dict[str, Any]]


def extract(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract `major_profile.v1` from a normalized_document payload.

    This is intentionally deterministic and evidence-bound. LLM extraction can
    be added later behind the same JSON shape, but this baseline must not invent
    fields not present in the normalized document.
    """
    if not isinstance(payload, dict):
        return None
    content_type = payload.get("content_type")
    blocks = payload.get("blocks")
    if content_type != "document" or not isinstance(blocks, list):
        return None

    body_markdown = str(payload.get("body_markdown") or "")
    title = str(payload.get("title") or "")
    joined = "\n".join(_block_text(b) for b in blocks)
    text = body_markdown or joined
    if not _looks_like_major_profile(title, text):
        return None

    segment_profiles = [
        _profile_from_segment(title, code, name, segment_blocks)
        for code, name, segment_blocks in _major_segments(blocks)
    ]
    profiles = [profile for profile in segment_profiles if profile is not None]
    if profiles:
        primary = dict(profiles[0])
        primary["profiles"] = profiles
        primary["profile_count"] = len(profiles)
        return primary

    return _profile_from_segment(title, None, None, blocks)


def _profile_from_segment(
    title: str,
    explicit_code: str | None,
    explicit_name: str | None,
    blocks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    text = "\n".join(_block_text(b) for b in blocks)
    sections = _extract_sections(blocks)
    major_code, major_name = (
        (explicit_code, explicit_name)
        if explicit_code and explicit_name
        else _extract_identity(title, text)
    )
    if not major_code or not major_name:
        return None

    education_level = _extract_education_level(title, text)
    duration = _extract_duration(text)
    training_goal = _section_text(sections.get("training_goal"))

    profile: dict[str, Any] = {
        "schema_version": DOMAIN_PROFILE,
        "domain": "major",
        "domain_profile": DOMAIN_PROFILE,
        "extractor_version": EXTRACTOR_VERSION,
        "confidence": _confidence(sections),
        "major_code": major_code,
        "major_name": major_name,
        "education_level": education_level,
        "basic_study_duration": duration,
        "training_goal": _field_value(
            training_goal,
            sections.get("training_goal"),
        ),
        "occupation_oriented": _items_from_section(sections.get("occupation_oriented")),
        "ability_requirements": _items_from_section(sections.get("ability_requirements")),
        "courses_and_training": _courses_from_section(sections.get("courses_and_training")),
        "certificates": _items_from_section(sections.get("certificates")),
        "continuation_majors": _continuations_from_section(
            sections.get("continuation_majors")
        ),
        "sections": [
            _section_payload(section)
            for section in sections.values()
            if section.text.strip()
        ],
        "evidence": {
            "title": title,
            "matched_sections": [SECTION_DEFS[k]["title"] for k in sections],
            "source_block_ids": _unique_block_ids(blocks[:3]),
        },
        "quality_flags": {},
    }
    if not sections:
        profile["quality_flags"]["missing_profile_sections"] = True
    if not profile["ability_requirements"]:
        profile["quality_flags"]["missing_ability_requirements"] = True
    if not any(profile["courses_and_training"].values()):
        profile["quality_flags"]["missing_courses_and_training"] = True
    return profile


def _major_segments(blocks: list[dict[str, Any]]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    text, block_spans = _joined_blocks_with_spans(blocks)
    starts = [
        (start, code, name)
        for start, _end, code, name in _iter_labeled_identities(text)
    ]
    if not starts:
        return []
    if len(starts) > 1 and any(len(code) >= 5 for _, code, _ in starts):
        starts = [item for item in starts if len(item[1]) >= 5]

    segments: list[tuple[str, str, list[dict[str, Any]]]] = []
    for idx, (start, code, name) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(text)
        segment_blocks = [
            block
            for block, block_start, block_end in block_spans
            if block_end > start and block_start < end
        ]
        if segment_blocks:
            segments.append((code, name, segment_blocks))
    return segments


def _looks_like_major_profile(title: str, text: str) -> bool:
    haystack = f"{title}\n{text}"
    hits = sum(
        1
        for config in SECTION_DEFS.values()
        if any(alias in haystack for alias in config["aliases"])
    )
    return hits >= 2 and bool(re.search(r"\b\d{4,6}\b", haystack))


def _extract_identity(title: str, text: str) -> tuple[str | None, str | None]:
    labeled = _extract_labeled_identity(text)
    if labeled is not None:
        return labeled
    candidates = [title] + [line.strip() for line in text.splitlines()[:30]]
    for line in candidates:
        match = re.search(r"(?P<code>\d{4,6})\s+[,，、]?\s*(?P<name>[\u4e00-\u9fa5A-Za-z0-9（）()·\-]+)", line)
        if match:
            return match.group("code"), _clean_name(match.group("name"))
    code_match = re.search(r"(?:专业代码|代码)[:：\s]*(\d{4,6})", text)
    name_match = re.search(r"(?:专业名称|名称)[:：\s]*([\u4e00-\u9fa5A-Za-z0-9（）()·\-]+)", text)
    code = code_match.group(1) if code_match else None
    name = _clean_name(name_match.group(1)) if name_match else None
    return code, name


def _extract_labeled_identity(text: str) -> tuple[str, str] | None:
    identities = _iter_labeled_identities(text)
    if not identities:
        return None
    _start, _end, code, name = identities[0]
    return code, name


def _iter_labeled_identities(text: str) -> list[tuple[int, int, str, str]]:
    pattern = re.compile(
        r"专业代码\s*[:：]?\s*(?P<code>\d{4,6})"
        r"\s+专业名称\s*[:：]?\s*"
        r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]+?)"
        r"(?:\s+基本修业年限|$)"
    )
    identities: list[tuple[int, int, str, str]] = []
    for match in pattern.finditer(text):
        name = _clean_name(re.sub(r"\s+", "", match.group("name")))
        if name:
            identities.append((match.start(), match.end(), match.group("code"), name))
    return identities


def _joined_blocks_with_spans(
    blocks: list[dict[str, Any]],
) -> tuple[str, list[tuple[dict[str, Any], int, int]]]:
    parts: list[str] = []
    spans: list[tuple[dict[str, Any], int, int]] = []
    cursor = 0
    for block in blocks:
        if parts:
            parts.append("\n")
            cursor += 1
        text = _block_text(block)
        start = cursor
        parts.append(text)
        cursor += len(text)
        spans.append((block, start, cursor))
    return "".join(parts), spans


def _extract_education_level(title: str, text: str) -> str | None:
    haystack = f"{title}\n{text[:1000]}"
    if "高职" in haystack or "高等职业" in haystack:
        return "高职"
    if "中职" in haystack or "中等职业" in haystack:
        return "中职"
    if "本科" in haystack:
        return "本科"
    return None


def _extract_duration(text: str) -> str | None:
    match = re.search(r"基本修业年限[:：\s]*([一二三四五六七八九十0-9]+年)", text)
    if match:
        return match.group(1)
    match = re.search(r"修业年限[:：\s]*([一二三四五六七八九十0-9]+年)", text)
    return match.group(1) if match else None


def _extract_sections(blocks: list[dict[str, Any]]) -> dict[str, Section]:
    sections: dict[str, Section] = {}
    current_key: str | None = None
    current_title: str | None = None
    current_blocks: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal current_key, current_title, current_blocks
        if current_key is None:
            return
        text = "\n".join(_block_text(b) for b in current_blocks).strip()
        sections[current_key] = Section(
            key=current_key,
            title=current_title or SECTION_DEFS[current_key]["title"],
            text=text,
            blocks=list(current_blocks),
        )
        current_key = None
        current_title = None
        current_blocks = []

    for block in blocks:
        text = _block_text(block)
        matched = _match_section_heading(text)
        if matched is not None:
            if current_key == matched[0]:
                current_blocks.append({**block, "text": _strip_markdown_heading(text)})
                continue
            flush()
            current_key = matched[0]
            current_title = matched[1]
            remainder = (
                _strip_markdown_heading(text)
                if _is_continuation_category_heading(matched)
                else _strip_heading(text, matched[1])
            )
            current_blocks = []
            if remainder:
                block = {**block, "text": remainder}
                current_blocks.append(block)
            continue
        if current_key is not None:
            # Stop at an unrelated high-level heading after we have captured a
            # known section. This prevents appendix/next-major leakage.
            if _is_unrelated_heading(block):
                flush()
                continue
            current_blocks.append(block)
    flush()
    return sections


def _match_section_heading(text: str) -> tuple[str, str] | None:
    stripped = text.strip().lstrip("#").strip()
    stripped = re.sub(r"^[一二三四五六七八九十]+[、.．]\s*", "", stripped)
    stripped = re.sub(r"^\d+[、.．]\s*", "", stripped)
    for key, config in SECTION_DEFS.items():
        for alias in config["aliases"]:
            if stripped == alias or stripped.startswith(f"{alias}\n") or stripped.startswith(f"{alias}：") or stripped.startswith(f"{alias}:"):
                return key, alias
    return None


def _strip_heading(text: str, heading: str) -> str:
    stripped = text.strip().lstrip("#").strip()
    stripped = re.sub(r"^[一二三四五六七八九十]+[、.．]\s*", "", stripped)
    stripped = re.sub(r"^\d+[、.．]\s*", "", stripped)
    if stripped.startswith(heading):
        return stripped[len(heading):].lstrip(" ：:\n\t")
    return ""


def _strip_markdown_heading(text: str) -> str:
    stripped = text.strip().lstrip("#").strip()
    stripped = re.sub(r"^[一二三四五六七八九十]+[、.．]\s*", "", stripped)
    stripped = re.sub(r"^\d+[、.．]\s*", "", stripped)
    return stripped


def _is_continuation_category_heading(matched: tuple[str, str]) -> bool:
    key, title = matched
    return key == "continuation_majors" and title != "接续专业举例"


def _is_unrelated_heading(block: dict[str, Any]) -> bool:
    btype = block.get("block_type")
    if btype not in {"heading", "title"}:
        return False
    return _match_section_heading(_block_text(block)) is None


def _items_from_section(section: Section | None) -> list[dict[str, Any]]:
    if section is None or not section.text.strip():
        return []
    items = _split_items(section.text)
    if not items:
        items = [section.text.strip()]
    evidence_ids = _unique_block_ids(section.blocks)
    locator = _locator_from_blocks(section.blocks)
    return [
        {
            "item_index": idx + 1,
            "text": item,
            "source_text": item,
            "evidence_block_ids": evidence_ids,
            "locator": locator,
            "confidence": 0.86,
        }
        for idx, item in enumerate(items)
        if item.strip()
    ]


def _courses_from_section(section: Section | None) -> dict[str, list[dict[str, Any]]]:
    groups = {"foundation_courses": [], "core_courses": [], "practice_trainings": []}
    if section is None:
        return groups
    subtexts = _split_course_subsections(section.text)
    evidence_ids = _unique_block_ids(section.blocks)
    locator = _locator_from_blocks(section.blocks)
    for group, text in subtexts.items():
        output_key = {
            "foundation": "foundation_courses",
            "core": "core_courses",
            "practice_training": "practice_trainings",
        }[group]
        items = (
            [_clean_item(text)]
            if group == "practice_training" and _clean_item(text)
            else _split_items(text)
        )
        for idx, item in enumerate(items, start=1):
            groups[output_key].append({
                "item_index": idx,
                "name": item,
                "text": item,
                "source_text": item,
                "course_group": group,
                "course_type": "training" if group == "practice_training" else "course",
                "evidence_block_ids": evidence_ids,
                "locator": locator,
                "confidence": 0.86,
            })
    return groups


def _continuations_from_section(section: Section | None) -> list[dict[str, Any]]:
    if section is None or not section.text.strip():
        return []
    items = _split_continuation_items(section.text)
    if not items:
        items = [section.text.strip()]
    evidence_ids = _unique_block_ids(section.blocks)
    locator = _locator_from_blocks(section.blocks)
    return [
        {
            "item_index": idx + 1,
            "text": item,
            "source_text": item,
            "evidence_block_ids": evidence_ids,
            "locator": locator,
            "confidence": 0.86,
        }
        for idx, item in enumerate(items)
        if item.strip()
    ]


def _split_continuation_items(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    marker = re.compile(
        r"(?=接续(?:高职专科|高职本科|普通本科|本科|中职|高职)?专业举例(?:[:：]|\s+))"
    )
    starts = [match.start() for match in marker.finditer(cleaned)]
    if not starts:
        return [_clean_item(cleaned)]
    items: list[str] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(cleaned)
        item = _clean_item(cleaned[start:end])
        item = re.sub(
            r"^(接续(?:高职专科|高职本科|普通本科|本科|中职|高职)?专业举例)\s+",
            r"\1：",
            item,
        )
        if item:
            items.append(item)
    return _dedupe(items)


def _split_course_subsections(text: str) -> dict[str, str]:
    spans: list[tuple[int, str, str]] = []
    for group, aliases in _SUBSECTION_ALIASES.items():
        for alias in aliases:
            match = re.search(re.escape(alias), text)
            if match:
                spans.append((match.start(), group, alias))
                break
    if not spans:
        return {"foundation": text, "core": "", "practice_training": ""}
    spans.sort(key=lambda x: x[0])
    result = {"foundation": "", "core": "", "practice_training": ""}
    for idx, (start, group, alias) in enumerate(spans):
        end = spans[idx + 1][0] if idx + 1 < len(spans) else len(text)
        result[group] = text[start + len(alias):end].strip(" ：:\n\t")
    return result


def _split_items(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) > 1:
        candidates = []
        for line in lines:
            candidates.extend(_split_inline_items(line))
        return _dedupe([_clean_item(i) for i in candidates if _clean_item(i)])
    return [_clean_item(i) for i in _split_inline_items(cleaned) if _clean_item(i)]


def _split_inline_items(text: str) -> list[str]:
    text = re.sub(r"^\s*(?:[-*•·]|\d+[.．、]|[（(]?\d+[）)])\s*", "", text).strip()
    normalized = re.sub(r"[；;]\s*", "\n", text)
    normalized = re.sub(r"\s*[、，]\s*", "、", normalized)
    parts = re.split(r"(?:^|\n)\s*(?:[-*•·]|\d+[.．、]|[（(]?\d+[）)])\s*", normalized)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) > 1:
        return parts
    if "、" in text and len(text) < 300 and "能力" not in text and not text.startswith("具有"):
        return [p.strip() for p in text.split("、") if p.strip()]
    return [text.strip()]


def _field_value(value: str, section: Section | None) -> dict[str, Any] | None:
    if not value.strip():
        return None
    return {
        "text": value.strip(),
        "evidence_block_ids": _unique_block_ids(section.blocks if section else []),
        "locator": _locator_from_blocks(section.blocks if section else []),
        "confidence": 0.86,
    }


def _section_payload(section: Section) -> dict[str, Any]:
    return {
        "section_key": section.key,
        "section_title": section.title,
        "text": section.text,
        "source_block_ids": _unique_block_ids(section.blocks),
        "locator": _locator_from_blocks(section.blocks),
    }


def _section_text(section: Section | None) -> str:
    return section.text.strip() if section is not None else ""


def _block_text(block: dict[str, Any]) -> str:
    value = block.get("text") or block.get("content") or ""
    return str(value).strip()


def _unique_block_ids(blocks: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for block in blocks:
        block_id = block.get("block_id")
        if isinstance(block_id, str) and block_id and block_id not in seen:
            seen.add(block_id)
            ids.append(block_id)
    return ids


def _locator_from_blocks(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = []
    pages = []
    for block in blocks:
        page = block.get("page")
        if not isinstance(page, int):
            locator = block.get("source_locator")
            if isinstance(locator, dict) and isinstance(locator.get("page"), int):
                page = locator["page"]
        if isinstance(page, int):
            pages.append(page)
        normalized.append({
            "block_id": block.get("block_id"),
            "page": page if isinstance(page, int) else None,
            "bbox": block.get("bbox"),
            "md_char_range": block.get("md_char_range"),
        })
    return {
        "page_start": min(pages) if pages else None,
        "page_end": max(pages) if pages else None,
        "blocks": normalized,
    }


def _confidence(sections: dict[str, Section]) -> float:
    base = 0.62
    return min(0.95, base + len(sections) * 0.045)


def _clean_name(value: str) -> str:
    return value.strip().strip(" ：:，,。")


def _clean_item(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ：:，,。；;")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = ["DOMAIN_PROFILE", "EXTRACTOR_VERSION", "extract", "SECTION_DEFS"]
