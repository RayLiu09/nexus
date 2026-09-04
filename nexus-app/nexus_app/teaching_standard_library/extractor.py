"""Deterministic extraction of standard-level professional teaching facts."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from nexus_app.knowledge.semantic_repack import _parse_markdown_table
from nexus_app.teaching_standard_library.schema import DOMAIN_PROFILE, validate_payload

EXTRACTOR_VERSION = "teaching_standard_library_extractor.v1"

_SECTION_DIMENSIONS = {
    "适用行业": "applied_industry",
    "面向行业": "applied_industry",
    "所属专业大类": "applied_industry",
    "职业面向": "occupation_type",
    "职业领域": "occupation_type",
    "就业面向": "occupation_type",
    "主要岗位": "primary_position",
    "就业岗位": "primary_position",
    "岗位面向": "primary_position",
    "职业类证书": "certificate_type",
    "职业资格证书": "certificate_type",
    "证书要求": "certificate_type",
}
_COURSE_HEADINGS = {
    "专业基础课程": "foundation",
    "基础课程": "foundation",
    "专业核心课程": "core",
    "核心课程": "core",
    "专业拓展课程": "extension",
    "拓展课程": "extension",
    "专业选修课程": "extension",
}
_OCCUPATION_COLUMNS = {
    "对应行业": "applied_industry",
    "所属行业": "applied_industry",
    "主要职业类别": "occupation_type",
    "职业类别": "occupation_type",
    "主要岗位": "primary_position",
    "岗位类别": "primary_position",
    "技术领域": "primary_position",
    "职业类证书": "certificate_type",
    "职业资格证书": "certificate_type",
}
_RATIO_VALUE = r"(\d{1,3}(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?)"
_RULES = (
    ("total_hours", r"(?:总学时|总课时)[^\n。；;]{0,30}?(\d{3,5})\s*(?:学时|课时|小时)", "hours"),
    (
        "public_foundation_ratio",
        rf"(?:公共基础课程|公共基础课)[^\n。；;]{{0,80}}?(?:占(?:总学时)?(?:的)?|不低于|不少于)\s*{_RATIO_VALUE}(?:以上|以下)?",
        "ratio",
    ),
    (
        "professional_course_ratio",
        rf"(?:专业课程|专业课)[^\n。；;]{{0,80}}?(?:占(?:总学时)?(?:的)?|不低于|不少于)\s*{_RATIO_VALUE}(?:以上|以下)?",
        "ratio",
    ),
    (
        "practice_ratio",
        rf"(?:实践教学|实践性教学|实训)[^\n。；;]{{0,80}}?(?:占(?:总学时)?(?:的)?|不低于|不少于)\s*{_RATIO_VALUE}(?:以上|以下)?",
        "ratio",
    ),
    (
        "elective_ratio",
        rf"(?:各类)?(?:选修课程|选修课)[^\n。；;]{{0,80}}?(?:占(?:总学时)?(?:的)?|不低于|不少于)\s*{_RATIO_VALUE}(?:以上|以下)?",
        "ratio",
    ),
    (
        "internship_months",
        r"(?:校外企业岗位实习|岗位实习|顶岗实习|毕业实习|实习)[^\n。；;]{0,50}?(?:不超过|不高于|不少于|不低于|为)\s*(\d+(?:\.\d+)?)\s*个?月",
        "months",
    ),
)


def extract(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("content_type") != "document":
        return None
    blocks = [block for block in payload.get("blocks", []) if isinstance(block, dict)]
    if not blocks:
        return None
    title = _clean(payload.get("title"))
    whole_text = "\n".join(_text(block) for block in blocks)
    if "专业教学标准" not in f"{title}\n{whole_text}":
        return None

    standard_id = _extract_standard_id(title, whole_text)
    major_code, major_name = _extract_major_identity(title, whole_text)
    education_level = _extract_education_level(title, whole_text)
    sections = _sections(blocks)
    occupations = _occupations(sections)
    rules = _rules(blocks)
    course_structures = _course_structures(sections)
    training_goal = _first_section(sections, ("培养目标", "培养目标定位", "培养规格"))
    quality_flags: dict[str, Any] = {}
    if not major_name:
        quality_flags["major_identity_missing"] = True
    if not occupations:
        quality_flags["occupation_orientation_missing"] = True
    if not course_structures:
        quality_flags["course_structure_missing"] = True
    result = {
        "schema_version": DOMAIN_PROFILE,
        "domain_profile": DOMAIN_PROFILE,
        "extractor_version": EXTRACTOR_VERSION,
        "standard_id": standard_id,
        "standard_title": title or None,
        "major_code": major_code,
        "major_name": major_name,
        "education_level": education_level,
        "major_category": _classification(whole_text, "专业大类"),
        "major_class": _classification(whole_text, "专业类"),
        "basic_study_years": _study_years(whole_text),
        "occupations": occupations,
        "course_structures": course_structures,
        "rules": rules,
        "training_goal_source": training_goal,
        "source_evidence": {"title": title, "source_block_ids": _ids(blocks[:3])},
        "quality_flags": quality_flags,
    }
    return validate_payload(result)[0]


def _sections(blocks: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    result: list[tuple[str, list[dict[str, Any]]]] = []
    current: list[dict[str, Any]] | None = None
    title = ""
    for block in blocks:
        text = _text(block)
        heading = _heading(text) if block.get("block_type") in {"heading", "title"} else ""
        if heading:
            if current is not None:
                result.append((title, current))
            title, current = heading, []
        elif current is not None:
            current.append(block)
    if current is not None:
        result.append((title, current))
    return result


def _occupations(sections: list[tuple[str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for heading, blocks in sections:
        table_facts = [fact for block in blocks for fact in _occupation_table_facts(block, heading)]
        for fact in table_facts:
            identity = (fact["dimension_type"], fact["source_name"])
            if identity not in seen:
                seen.add(identity)
                output.append(fact)
        dimension = next(
            (value for alias, value in _SECTION_DIMENSIONS.items() if alias in heading), None
        )
        if dimension is None:
            continue
        narrative_blocks = [block for block in blocks if block.get("block_type") != "table"]
        source = "\n".join(_text(block) for block in narrative_blocks)
        for item in _items(source):
            identity = (dimension, item)
            if identity in seen:
                continue
            seen.add(identity)
            output.append(
                {
                    "dimension_type": dimension,
                    "source_name": item,
                    "source_text": source,
                    "evidence_block_ids": _ids(narrative_blocks),
                    "locator": _locator(narrative_blocks, heading),
                }
            )
    return output


def _occupation_table_facts(block: dict[str, Any], heading: str) -> list[dict[str, Any]]:
    if block.get("block_type") != "table":
        return []
    parsed = _parse_markdown_table(_text(block))
    if not parsed:
        return []
    columns: dict[int, str] = {}
    for index, header in enumerate(parsed["headers"]):
        normalized = re.sub(r"\s+|[（(][^）)]*[）)]", "", header)
        dimension = next(
            (value for alias, value in _OCCUPATION_COLUMNS.items() if alias in normalized), None
        )
        if dimension:
            columns[index] = dimension
    facts: list[dict[str, Any]] = []
    for row_index, row in enumerate(parsed["data_rows"], start=1):
        cells = row.get("cells") or []
        for column_index, dimension in columns.items():
            if column_index >= len(cells):
                continue
            for source_name, source_code in _coded_items(cells[column_index]):
                facts.append(
                    {
                        "dimension_type": dimension,
                        "source_code": source_code,
                        "source_name": source_name,
                        "source_text": row.get("raw") or cells[column_index],
                        "evidence_block_ids": _ids([block]),
                        "locator": {
                            **_locator([block], heading),
                            "table_row_index": row_index,
                            "table_column_index": column_index,
                        },
                    }
                )
    return facts


def _coded_items(value: str) -> list[tuple[str, str | None]]:
    values = re.split(r"(?:<br\s*/?>|[\n；;])", value, flags=re.I)
    output: list[tuple[str, str | None]] = []
    for item in values:
        item = item.strip(" 、，,。")
        if not item:
            continue
        match = re.match(r"(.+?)[（(]\s*([0-9][0-9.\-]*)\s*[）)]$", item)
        output.append((match.group(1).strip(), match.group(2)) if match else (item, None))
    return output


def _rules(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float, str]] = set()
    for block in blocks:
        source = _text(block)
        match_source = re.sub(r"\s+", "", source)
        for rule_type, pattern, unit in _RULES:
            for match in re.finditer(pattern, match_source):
                value = _numeric_rule_value(match.group(1), unit)
                comparator = _comparator(match.group(0))
                identity = (rule_type, comparator, value, match.group(0))
                if identity in seen:
                    continue
                seen.add(identity)
                output.append(
                    {
                        "rule_type": rule_type,
                        "comparator": comparator,
                        "numeric_value": value,
                        "unit": "ratio" if unit == "ratio" else unit,
                        "source_text": source,
                        "evidence_block_ids": _ids([block]),
                        "locator": _locator([block], None),
                    }
                )
    return output


def _course_structures(sections: list[tuple[str, list[dict[str, Any]]]]) -> list[str]:
    values: list[str] = []
    for heading, _blocks in sections:
        for alias, value in _COURSE_HEADINGS.items():
            if alias in heading and value not in values:
                values.append(value)
    return values


def _numeric_rule_value(value: str, unit: str) -> float:
    cleaned = re.sub(r"\s+", "", value)
    if unit != "ratio":
        return float(cleaned)
    if cleaned.endswith("%"):
        return float(cleaned[:-1]) / 100
    numerator, denominator = cleaned.split("/", 1)
    return float(numerator) / float(denominator)


def _comparator(source_text: str) -> str:
    if any(token in source_text for token in ("不超过", "不高于", "以下")):
        return "<="
    if any(token in source_text for token in ("不少于", "不低于", "以上")):
        return ">="
    return "="


def _first_section(
    sections: list[tuple[str, list[dict[str, Any]]]], aliases: Iterable[str]
) -> dict[str, Any] | None:
    for heading, blocks in sections:
        if any(alias in heading for alias in aliases):
            text = "\n".join(_text(block) for block in blocks).strip()
            if text:
                return {
                    "text": text,
                    "evidence_block_ids": _ids(blocks),
                    "locator": _locator(blocks, heading),
                }
    return None


def _extract_standard_id(title: str, text: str) -> str | None:
    match = re.search(
        r"(?:标准编号|标准号|专业代码)\s*[：:]?\s*([A-Z]{1,6}/?[A-Z0-9.\-]{3,})", f"{title}\n{text}"
    )
    return match.group(1) if match else None


def _extract_major_identity(title: str, text: str) -> tuple[str | None, str | None]:
    source = f"{title}\n{text[:12000]}"
    match = re.search(r"([\u4e00-\u9fffA-Za-z]{2,40})\s*[（(]\s*(\d{4,6})\s*[）)]", source)
    if match:
        return match.group(2), match.group(1).strip()
    match = re.search(
        r"(?:专业名称\s*[：:]?\s*)([\u4e00-\u9fffA-Za-z]{2,40})(?:\s*[（(]\s*(\d{4,6})\s*[）)])?",
        source,
    )
    if match:
        return match.group(2), match.group(1).strip()
    title_match = re.search(r"([\u4e00-\u9fffA-Za-z]{2,30})专业教学标准", title)
    return (None, title_match.group(1).strip("（）() -")) if title_match else (None, None)


def _extract_education_level(title: str, text: str) -> str | None:
    source = f"{title}\n{text}"
    for value in ("中等职业教育", "高等职业教育本科", "高等职业教育专科", "职业本科"):
        if value in source:
            return value
    return None


def _classification(text: str, label: str) -> dict[str, str | None]:
    match = re.search(
        rf"{label}\s*[：:]?\s*(?:（?\s*(\d{{2,4}})\s*）?)?\s*([^\n，。；;]{{2,40}})", text
    )
    return {"code": match.group(1), "name": match.group(2).strip()} if match else {}


def _study_years(text: str) -> str | None:
    match = re.search(r"(?:基本修业年限|基本学习年限|修业年限)\s*[：:]?\s*([^\n。；;]{1,40})", text)
    return match.group(1).strip() if match else None


def _items(text: str) -> list[str]:
    text = re.sub(r"^[^：:]{2,30}[：:]", "", text.strip())
    return [
        part.strip(" \n、，,；;。")
        for part in re.split(r"[\n、；;]", text)
        if 1 < len(part.strip(" \n、，,；;。")) < 80
    ]


def _heading(value: str) -> str:
    return re.sub(r"^[#\s一二三四五六七八九十\d]+[、.．\s]*", "", value).strip().rstrip("：:")


def _text(block: dict[str, Any]) -> str:
    return _clean(block.get("text") or block.get("content") or "")


def _clean(value: Any) -> str:
    return str(value).strip()


def _ids(blocks: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(str(block["block_id"]) for block in blocks if block.get("block_id")))


def _locator(blocks: list[dict[str, Any]], heading: str | None) -> dict[str, Any]:
    pages = [block.get("page") for block in blocks if isinstance(block.get("page"), int)]
    return {"heading_path": [heading] if heading else [], "pages": list(dict.fromkeys(pages))}
