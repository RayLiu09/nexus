"""Evidence-bound extraction of a teaching-standard's course-content table."""

from __future__ import annotations

import re
from typing import Any

from nexus_app.knowledge.semantic_repack import _parse_markdown_table

DOMAIN_PROFILE = "teaching_standard.v1"
EXTRACTOR_VERSION = "teaching_standard_table_extractor.v1"

_TABLE_HEADERS = ("课程涉及的主要领域", "典型工作任务", "主要教学内容与要求")
_BULLET_PREFIX = re.compile(r"(?:^|\s)(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.、．])\s*")


def extract(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract graph-ready rows only from the named normalized-document table."""
    if not isinstance(payload, dict) or payload.get("content_type") != "document":
        return None
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        return None
    major_code, major_name = _major_identity(str(payload.get("title") or ""), blocks)
    if not major_name:
        return None
    rows: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("block_type") != "table":
            continue
        parsed = _parse_markdown_table(str(block.get("content") or block.get("text") or ""))
        if not parsed or not _is_target_table(parsed["headers"]):
            continue
        indexes = _column_indexes(parsed["headers"])
        for index, row in enumerate(parsed["data_rows"], start=1):
            cells = row["cells"]
            domain = cells[indexes["domain"]].strip()
            task = cells[indexes["task"]].strip()
            requirement = cells[indexes["requirement"]].strip()
            if not domain or (not task and not requirement):
                continue
            evidence = _evidence(block, index, row.get("raw"))
            rows.append({
                "row_index": index,
                "occupational_domain": domain,
                "typical_work_tasks": _split_bullets(task),
                "skill_knowledge_requirements": _split_bullets(requirement),
                "evidence": evidence,
            })
    if not rows:
        return None
    return {
        "schema_version": DOMAIN_PROFILE,
        "extractor_version": EXTRACTOR_VERSION,
        "major_code": major_code,
        "major_name": major_name,
        "rows": rows,
    }


def _is_target_table(headers: list[str]) -> bool:
    joined = " ".join(headers)
    return all(token in joined for token in _TABLE_HEADERS)


def _column_indexes(headers: list[str]) -> dict[str, int]:
    return {
        "domain": next(i for i, h in enumerate(headers) if "课程涉及的主要领域" in h),
        "task": next(i for i, h in enumerate(headers) if "典型工作任务" in h),
        "requirement": next(i for i, h in enumerate(headers) if "主要教学内容与要求" in h),
    }


def _major_identity(title: str, blocks: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    text = "\n".join(str(block.get("text") or block.get("content") or "") for block in blocks[:30])
    match = re.search(r"(?:专业名称\s*[（(]?|^\s*)(\d{4,6})\s*([^\n（(）)]{2,40})", f"{title}\n{text}")
    if not match:
        return None, None
    return match.group(1), match.group(2).strip(" ：:（()")


def _split_bullets(value: str) -> list[str]:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = value.replace("；", "。")
    parts = _BULLET_PREFIX.split(value)
    if len(parts) == 1:
        parts = re.split(r"[\n。]", value)
    return [re.sub(r"\s+", " ", part).strip(" 。；;") for part in parts if part.strip(" 。；;\n")]


def _evidence(block: dict[str, Any], row_index: int, raw: str | None) -> dict[str, Any]:
    return {
        "source_block_ids": [block.get("block_id")] if block.get("block_id") else [],
        "locator": {
            "page": block.get("page"), "bbox": block.get("bbox"),
            "table_row_index": row_index,
        },
        "source_row": raw or "",
    }
