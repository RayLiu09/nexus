"""Evidence-bound deterministic extraction for `talent_training_plan.v1`."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

DOMAIN_PROFILE = "talent_training_plan.v1"
EXTRACTOR_VERSION = "talent_training_plan_extractor.v1"


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.rows: list[list[str]] = []; self._row: list[str] | None = None; self._cell: list[str] | None = None
    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr": self._row = []
        elif tag in {"td", "th"}: self._cell = []
        elif tag in {"br", "p", "div", "li"} and self._cell is not None:
            # Preserve source-provided cell structure. Course and capability
            # facts can be safely split at these boundaries later; a plain
            # text concatenation cannot be reliably reconstructed.
            self._cell.append("\n")
    def handle_data(self, data: str) -> None:
        if self._cell is not None: self._cell.append(data)
    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell).strip()); self._cell = None
        elif tag == "tr" and self._row:
            self.rows.append(self._row); self._row = None


def extract(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("content_type") != "document": return None
    blocks = payload.get("blocks")
    if not isinstance(blocks, list): return None
    title = str(payload.get("title") or "")
    text = "\n".join(_text(b) for b in blocks)
    if "人才培养方案" not in f"{title}\n{text}": return None
    major_name, major_code = _identity(text, title)
    if not major_name: return None
    tables = [
        (block, rows)
        for block in blocks
        if isinstance(block, dict)
        for rows in _table_row_groups(block)
        if rows
    ]
    career = _career_orientation(tables)
    courses = _courses(tables)
    _link_courses_to_position_skills(courses, career["positions"])
    goal = _section_text(blocks, ("培养目标",), stop=("培养规格", "课程设置", "毕业要求"))
    specification = _specification(blocks)
    certificates = _certificates(tables, text)
    # A plan projection is useful only when it contains at least one graph or
    # structured-retrieval input beyond identity. Older normalized documents
    # can retain text blocks while omitting table structure; do not emit a
    # misleading, identity-only row for those historical payloads.
    if not career.get("industries") and not career.get("occupations") and not career.get("positions") and not courses:
        return None
    evidence_ids = [str(b.get("block_id")) for b in blocks[:3] if b.get("block_id")]
    flags: dict[str, Any] = {}
    if not career.get("industries") and not career.get("occupations") and not career.get("positions"): flags["missing_career_orientation"] = True
    if not courses: flags["missing_courses"] = True
    return {
        "schema_version": DOMAIN_PROFILE, "domain_profile": DOMAIN_PROFILE, "extractor_version": EXTRACTOR_VERSION,
        "institution_name": _institution(title, text), "major_name": major_name, "major_code": major_code,
        "education_level": _education_level(title, text), "study_duration": _duration(text), "training_goal": goal,
        "training_specification": specification, "career_orientation": career, "certificates": certificates,
        "courses": courses, "confidence": 0.9 if courses and career else 0.75,
        "evidence": {"source_block_ids": evidence_ids}, "quality_flags": flags,
    }


def _text(block: Any) -> str:
    return str(block.get("text") or block.get("content") or "") if isinstance(block, dict) else ""


def _table_rows(block: dict[str, Any]) -> list[list[str]]:
    html = block.get("html") or block.get("table_html")
    if not isinstance(html, str) or "<table" not in html.lower(): return []
    parser = _TableParser(); parser.feed(html); return parser.rows


def _table_row_groups(block: dict[str, Any]) -> list[list[list[str]]]:
    """Return source tables from HTML or standard Markdown table text.

    Normalized DOCX documents may retain table structure as GitHub-flavoured
    Markdown in a text block instead of ``table_html``.  Treat only rows with
    a Markdown separator as tables, so prose containing pipe characters never
    becomes a domain fact.
    """
    html_rows = _table_rows(block)
    if html_rows:
        return [html_rows]

    lines = str(block.get("text") or block.get("content") or "").splitlines()
    groups: list[list[list[str]]] = []
    index = 0
    while index + 1 < len(lines):
        header = _markdown_cells(lines[index])
        separator = _markdown_cells(lines[index + 1])
        if not header or len(header) < 2 or len(header) != len(separator) or not _markdown_separator(separator):
            index += 1
            continue
        rows = [header]
        index += 2
        while index < len(lines):
            row = _markdown_cells(lines[index])
            if not row or len(row) != len(header):
                break
            rows.append(row)
            index += 1
        if len(rows) > 1:
            groups.append(rows)
    return groups


def _markdown_cells(line: str) -> list[str]:
    value = line.strip()
    if "|" not in value:
        return []
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [re.sub(r"<br\s*/?>", "\n", cell, flags=re.IGNORECASE).strip() for cell in value.split("|")]


def _markdown_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _identity(text: str, title: str) -> tuple[str | None, str | None]:
    code = re.search(r"专业代码\s*[:：]\s*(\d{4,6})", text)
    name = re.search(r"专业名称\s*[:：]\s*([\u4e00-\u9fa5A-Za-z0-9（）()·\-]+)", text)
    if not code:
        code = re.search(r"\|\s*专业代码\s*\|\s*(\d{4,6})\s*\|", text)
    if not name:
        name = re.search(r"\|\s*专业名称\s*\|\s*([^|\n]+?)\s*\|", text)
    if name: return name.group(1).strip(), code.group(1) if code else None
    cleaned = re.sub(r"[（(].*?[）)]", "", title)
    cleaned = re.sub(r"\.(?:pdf|docx?)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("人才培养方案", "").strip()
    return (cleaned or None, code.group(1) if code else None)


def _institution(title: str, text: str) -> str | None:
    match = re.search(r"([\u4e00-\u9fa5]{2,30}(?:职业技术大学|职业技术学院|职业学院|学院|学校))", title + "\n" + text[:1200])
    return match.group(1) if match else None


def _education_level(title: str, text: str) -> str | None:
    value = title + "\n" + text[:1500]
    return "中职" if "中职" in value or "中等职业" in value else "高职" if "高职" in value or "高等职业" in value else None


def _duration(text: str) -> str | None:
    match = re.search(r"(?:基本)?修业年限\s*[:：]?\s*([一二三四五六七八九十0-9]+年)", text)
    return match.group(1) if match else None


def _section_text(blocks: list[dict[str, Any]], headings: tuple[str, ...], *, stop: tuple[str, ...]) -> str | None:
    collected: list[str] = []; active = False
    for block in blocks:
        value = _text(block).strip()
        if any(h in value for h in headings): active = True
        elif active and any(h in value for h in stop): break
        if active and value: collected.append(value)
    value = "\n".join(collected)
    return value[:6000] if value else None


def _item(name: str, code: str | None, block: dict[str, Any], column: str) -> dict[str, Any]:
    return {"name": name.strip(), **({"code": code} if code else {}), "source_text": name.strip(), "evidence": _evidence(block, column)}


def _career_orientation(tables: list[tuple[dict[str, Any], list[list[str]]]]) -> dict[str, Any]:
    result: dict[str, list[dict[str, Any]]] = {"industries": [], "occupations": [], "positions": []}
    for block, rows in tables:
        if not rows: continue
        headers = rows[0]
        mapping = _position_skill_mapping(block, rows)
        if mapping:
            result["positions"].extend(mapping)
            continue
        indices = {kind: next((i for i, h in enumerate(headers) if marker in h), None) for kind, marker in (("industries", "行业"), ("occupations", "职业"), ("positions", "岗位"))}
        if any(index is not None for index in indices.values()):
            for row in rows[1:]:
                for kind, index in indices.items():
                    if index is not None and index < len(row):
                        _append_career_values(result, kind, row[index], block, headers[index])
        else:
            # Institution plans commonly render 职业面向 as a two-column
            # key/value table ("对应行业 | ..."), without semantic headers.
            # The left column is still normalized-document evidence, so use
            # only explicit labels rather than inferring facts from values.
            for row in rows[1:]:
                if len(row) < 2:
                    continue
                label, value = row[0], row[1]
                kind = (
                    "industries" if "行业" in label
                    else "occupations" if "职业类别" in label or "职业名称" in label
                    else "positions" if "岗位" in label
                    else None
                )
                if kind:
                    _append_career_values(result, kind, value, block, label)
    result["industries"] = _unique(result["industries"], "name")
    result["occupations"] = _unique(result["occupations"], "name")
    result["positions"] = _merge_positions(result["positions"])
    return result


def _append_career_values(
    result: dict[str, list[dict[str, Any]]],
    kind: str,
    raw_value: str,
    block: dict[str, Any],
    column: str,
) -> None:
    if not raw_value.strip():
        return
    value = re.sub(r"<br\s*/?>", "\n", raw_value, flags=re.IGNORECASE)
    for segment in _split_values(value):
        # A common rendered form is `批发业（51）零售业（52）`, which has no
        # punctuation boundary but does have explicit name/code evidence.
        coded_items = list(re.finditer(
            r"([^（()\n；;、]+?)\s*[（(]([0-9-]{2,14})[）)]", segment
        ))
        if coded_items:
            for match in coded_items:
                name = match.group(1).strip()
                if name:
                    result[kind].append(_item(name, match.group(2), block, column))
            continue
        name = segment.strip()
        if name:
            result[kind].append(_item(name, None, block, column))


def _merge_positions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        current = merged.get(name)
        if current is None:
            current = dict(item)
            current["skills"] = list(item.get("skills") or [])
            current["learning_domains"] = list(item.get("learning_domains") or [])
            merged[name] = current
            continue
        current["skills"] = _unique(
            list(current.get("skills") or []) + list(item.get("skills") or []),
            "name",
        )
        current["learning_domains"] = _unique(
            list(current.get("learning_domains") or []) + list(item.get("learning_domains") or []),
            "name",
        )
        if not current.get("source_text") and item.get("source_text"):
            current["source_text"] = item["source_text"]
    return list(merged.values())


def _position_skill_mapping(block: dict[str, Any], rows: list[list[str]]) -> list[dict[str, Any]]:
    """Extract plan-local position -> capability -> learning-domain evidence.

    These values intentionally remain attributes of this training plan.  They
    are source facts for a later graph projection, not global job or skill
    master data.
    """
    if len(rows) < 2:
        return []
    headers = rows[0]
    position_i = next((i for i, h in enumerate(headers) if "岗位" in h), None)
    skill_i = next((i for i, h in enumerate(headers) if "核心能力" in h or "岗位能力" in h), None)
    domain_i = next((i for i, h in enumerate(headers) if "学习领域" in h or "学习内容" in h), None)
    if position_i is None or (skill_i is None and domain_i is None):
        return []
    result: list[dict[str, Any]] = []
    recovery = block.get("table_structure_recovery")
    recovery_rows = (
        recovery.get("recovered_rows") or []
        if isinstance(recovery, dict) and recovery.get("status") == "recovered"
        else []
    )
    recovered_rows = {
        item.get("row_index"): item
        for item in recovery_rows
        if isinstance(item, dict)
    }
    affected_rows = set(recovery.get("affected_row_indexes") or []) if isinstance(recovery, dict) else set()
    for row_index, row in enumerate(rows[1:], start=1):
        if position_i >= len(row) or not row[position_i].strip():
            continue
        names = [_normalize_position_name(value) for value in _split_values(row[position_i])]
        recovered = recovered_rows.get(row_index)
        if recovered is not None:
            skills = _recovered_values(recovered.get("skills"), block, headers[skill_i] if skill_i is not None else "岗位核心能力", "professional_skill")
            domains = _recovered_values(recovered.get("learning_domains"), block, headers[domain_i] if domain_i is not None else "学习领域", None)
        elif row_index in affected_rows:
            # Do not form a false single capability fact from a flattened cell.
            skills, domains = [], []
        else:
            skills = _evidenced_values(
                row[skill_i] if skill_i is not None and skill_i < len(row) else "",
                block,
                headers[skill_i] if skill_i is not None else "岗位核心能力",
                "professional_skill",
            )
            domains = _evidenced_values(
                row[domain_i] if domain_i is not None and domain_i < len(row) else "",
                block,
                headers[domain_i] if domain_i is not None else "学习领域",
                None,
            )
        for name in names:
            result.append({
                "name": name,
                "source_text": " | ".join(row),
                "skills": skills,
                "learning_domains": domains,
                "evidence": _evidence(block, headers[position_i]),
            })
    return result


def _normalize_position_name(value: str) -> str:
    """Remove layout whitespace from a plan-local position label only."""
    return re.sub(r"\s+", "", value).strip()


def _courses(tables: list[tuple[dict[str, Any], list[list[str]]]]) -> list[dict[str, Any]]:
    result = []
    for block, rows in tables:
        if len(rows) < 2: continue
        headers = rows[0]
        columns = _resolve_course_columns(headers)
        name_i = columns["course_name"]
        if name_i is None: continue
        objective_i = columns["course_objective"]
        content_i = columns["course_content"]
        for row in rows[1:]:
            if name_i >= len(row) or not row[name_i].strip(): continue
            result.append({
                "course_name": row[name_i],
                "curriculum_group": "unknown",
                "course_type": "course",
                "course_objective": row[objective_i] if objective_i is not None and objective_i < len(row) else None,
                "course_content": row[content_i] if content_i is not None and content_i < len(row) else None,
                "skill_refs": [],
                "knowledge_topics": [],
                "source_text": " | ".join(row),
                "evidence": _evidence(block, headers[name_i]),
            })
    return sanitize_courses(result)


_COURSE_HEADER_ALIASES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "course_name": (
        ("课程名称", "课程名", "课 程 名 称", "课程"),
        ("课程目标", "教学目标", "学习目标", "教学内容", "课程内容", "课程简介", "课程性质", "课程类别"),
    ),
    "course_objective": (
        ("课程目标", "教学目标", "学习目标", "课程学习目标", "教学目的", "课程目的", "教学要求"),
        ("教学内容", "课程内容", "课程简介", "课程名称", "课程性质", "课程类别"),
    ),
    "course_content": (
        ("课程内容", "教学内容", "主要教学内容", "教学主要内容", "学习内容", "课程主要内容", "课程模块", "教学项目"),
        ("课程目标", "教学目标", "学习目标", "教学要求", "课程名称", "课程性质", "课程类别"),
    ),
}


def _resolve_course_columns(headers: list[str]) -> dict[str, int | None]:
    """Resolve course-table fields with normalized, semantic header matching.

    Normalization handles MinerU's line-wrap, whitespace, full-width
    punctuation, and compound labels. The aliases express document semantics,
    while exclusions prevent target/content columns from being conflated. This
    is deterministic by design: ambiguous columns are left unmapped rather
    than guessed through an LLM.
    """
    normalized = [_normalize_course_header(header) for header in headers]
    return {
        field: _best_course_header_index(normalized, aliases, excluded)
        for field, (aliases, excluded) in _COURSE_HEADER_ALIASES.items()
    }


def _normalize_course_header(value: Any) -> str:
    text = _decode_unicode_escapes(str(value or ""))
    text = text.translate(str.maketrans({"：": ":", "（": "(", "）": ")", "－": "-"}))
    return re.sub(r"[\s:：()（）\[\]【】、,，;；.。·_-]+", "", text).lower()


def _best_course_header_index(
    headers: list[str], aliases: tuple[str, ...], excluded: tuple[str, ...]
) -> int | None:
    candidates: list[tuple[int, int]] = []
    normalized_aliases = [_normalize_course_header(alias) for alias in aliases]
    normalized_excluded = [_normalize_course_header(value) for value in excluded]
    for index, header in enumerate(headers):
        if not header or any(value in header for value in normalized_excluded):
            continue
        scores = [
            100 if header == alias else 80 if alias in header else 0
            for alias in normalized_aliases
        ]
        score = max(scores, default=0)
        if score:
            candidates.append((score, index))
    if not candidates:
        return None
    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    return candidates[0][1]


_COURSE_PLACEHOLDERS = frozenset({"-", "--", "—", "无", "暂无", "n/a", "na", "null", "none"})
_COURSE_NON_NAMES = re.compile(
    r"^(?:序号|编号|课程名称|课程|课程目标|课程内容|教学内容|合计|总计|小计|备注|类别|模块|学期|学年|学时|理论|实践|课时|学时占比|实践学时占比|第[一二三四五六七八九十]+学年|第[一二三四五六七八九十]+期)$"
)
_COURSE_DESCRIPTION_PREFIX = re.compile(
    r"^(?:掌握|了解|熟悉|理解|培养|通过|能够|能|会|使学生|本课程|养成|树立|提高|增强|具备)"
)
_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def sanitize_courses(courses: Any) -> list[dict[str, Any]]:
    """Keep only useful plan-owned course facts before persistence/graph use.

    MinerU tables can include serial numbers, merged header cells, and summary
    rows under a loosely detected `课程名称` column. A course node without a
    usable Chinese course name and concrete course content has no retrieval or
    course-graph value, so it is deliberately excluded here.
    """
    if not isinstance(courses, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in courses:
        if not isinstance(item, dict):
            continue
        name = _clean_course_text(item.get("course_name"), strip_hours=True)
        content = _clean_course_text(item.get("course_content"))
        if not _is_valid_course_name(name) or not _is_meaningful_course_content(content):
            continue
        objective = _clean_course_text(item.get("course_objective"))
        cleaned.append({
            **item,
            "course_name": name,
            "course_code": _clean_course_text(item.get("course_code")),
            "course_objective": objective,
            "course_content": content,
            "skill_refs": _sanitize_evidenced_items(item.get("skill_refs")),
            "knowledge_topics": _sanitize_evidenced_items(item.get("knowledge_topics")),
        })
    return _unique(cleaned, "course_name")


def _clean_course_text(value: Any, *, strip_hours: bool = False) -> str | None:
    if value is None:
        return None
    text = _decode_unicode_escapes(str(value)).replace("\u00a0", " ").strip()
    if strip_hours:
        text = re.sub(r"[（(]\s*\d+\s*(?:课时|学时)[）)]", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    return None if not text or text.lower() in _COURSE_PLACEHOLDERS else text


def _is_valid_course_name(value: str | None) -> bool:
    if not value or _COURSE_NON_NAMES.fullmatch(value):
        return False
    # A Chinese curriculum title may contain English/tool tokens (e.g. WEB),
    # but a bare serial number or alphabetic table fragment is never a course.
    if len(value) > 60 or _COURSE_DESCRIPTION_PREFIX.match(value):
        return False
    if any(mark in value for mark in ("。", "；", ";", "：", ":")):
        return False
    return len(re.findall(r"[\u4e00-\u9fff]", value)) >= 2


def _is_meaningful_course_content(value: str | None) -> bool:
    return bool(value and len(re.sub(r"\s+", "", value)) >= 2)


def _sanitize_evidenced_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _clean_course_text(item.get("name"))
        if not name or len(re.findall(r"[\u4e00-\u9fffA-Za-z]", name)) < 2:
            continue
        output.append({**_decode_unicode_tree(item), "name": name})
    return _unique(output, "name")


def _decode_unicode_tree(value: Any) -> Any:
    if isinstance(value, str):
        return _decode_unicode_escapes(value)
    if isinstance(value, list):
        return [_decode_unicode_tree(item) for item in value]
    if isinstance(value, dict):
        return {key: _decode_unicode_tree(item) for key, item in value.items()}
    return value


def _decode_unicode_escapes(value: str) -> str:
    # Decode only literal JSON Unicode escapes; never broadly unicode-escape
    # arbitrary source text, which could corrupt paths and backslashes.
    for _ in range(2):
        decoded = _UNICODE_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), value)
        if decoded == value:
            break
        value = decoded
    return value


def _specification(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    value = _section_text(blocks, ("培养规格",), stop=("课程设置", "毕业要求"))
    if not value:
        return {}
    categories = {
        "abilities": ("能力",),
        "knowledge_requirements": ("知识",),
        "qualities": ("素质", "职业素养"),
    }
    result: dict[str, Any] = {"source_text": value, "abilities": [], "knowledge_requirements": [], "qualities": []}
    for block in blocks:
        block_text = _text(block).strip()
        if not block_text or not any(marker in block_text for markers in categories.values() for marker in markers):
            continue
        for key, markers in categories.items():
            if any(marker in block_text for marker in markers):
                for item in _split_requirement_sentences(block_text):
                    if any(marker in item for marker in markers):
                        result[key].append({"name": item, "source_text": item, "evidence": _evidence(block, key)})
    for key in categories:
        result[key] = _unique(result[key], "name")
    return result


def _link_courses_to_position_skills(courses: list[dict[str, Any]], positions: list[dict[str, Any]]) -> None:
    for course in courses:
        course_name = str(course.get("course_name") or "")
        if not course_name:
            continue
        refs: list[dict[str, Any]] = []
        for position in positions:
            domains = position.get("learning_domains") if isinstance(position.get("learning_domains"), list) else []
            if not any(_course_matches_domain(course_name, str(domain.get("name") or "")) for domain in domains if isinstance(domain, dict)):
                continue
            for skill in position.get("skills") if isinstance(position.get("skills"), list) else []:
                if not isinstance(skill, dict):
                    continue
                refs.append({
                    "name": skill.get("name"),
                    "skill_type": skill.get("skill_type", "professional_skill"),
                    "position_name": position.get("name"),
                    "evidence": skill.get("evidence") or position.get("evidence") or {},
                })
        course["skill_refs"] = _unique(refs, "name")


def _course_matches_domain(course_name: str, domain_name: str) -> bool:
    left = re.sub(r"[（(].*?[）)]", "", course_name).strip()
    right = re.sub(r"[（(].*?[）)]", "", domain_name).strip()
    return bool(left and right and (left == right or left in right or right in left))


def _split_values(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[；;、\n]+", value) if item.strip()]


def _evidenced_values(
    value: str,
    block: dict[str, Any],
    column: str,
    item_type: str | None,
) -> list[dict[str, Any]]:
    result = []
    for name in _split_values(value):
        item = {"name": name, "source_text": name, "evidence": _evidence(block, column)}
        if item_type:
            item["skill_type"] = item_type
        result.append(item)
    return _unique(result, "name")


def _recovered_values(
    values: Any, block: dict[str, Any], column: str, item_type: str | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(values, list):
        return result
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        name = item["text"].strip()
        if not name:
            continue
        evidence = {
            **_evidence(block, column),
            "cell_segment_index": item.get("segment_index"),
            "structure_recovery": "litellm_default_governance_model",
        }
        result.append({"name": name, "source_text": name, "evidence": evidence, **({"skill_type": item_type} if item_type else {})})
    return _unique(result, "name")


def _split_requirement_sentences(value: str) -> list[str]:
    return [item.strip(" \t;；") for item in re.split(r"[。；;\n]+", value) if len(item.strip()) > 4]


def _certificates(tables: list[tuple[dict[str, Any], list[list[str]]]], text: str) -> list[dict[str, Any]]:
    result = []
    for block, rows in tables:
        for row in rows:
            for cell in row:
                if "证书" in cell and len(cell) > 8:
                    for name in re.split(r"[；;、]\s*", cell):
                        if "证书" in name: result.append({"name": name.strip(), "source_text": name.strip(), "evidence": _evidence(block, "证书")})
    return _unique(result, "name")


def _evidence(block: dict[str, Any], column: str) -> dict[str, Any]:
    return {"block_ids": [block["block_id"]] if block.get("block_id") else [], "locator": block.get("source_locator") or {}, "table_column": column}


def _unique(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set(); output = []
    for item in items:
        value = str(item.get(key) or "").strip()
        if value and value not in seen: seen.add(value); output.append(item)
    return output
