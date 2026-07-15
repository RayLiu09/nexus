"""Evidence-bound extraction of a teaching-standard's course-content table."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from nexus_app.knowledge.semantic_repack import _parse_markdown_table

DOMAIN_PROFILE = "teaching_standard.v1"
EXTRACTOR_VERSION = "teaching_standard_table_extractor.v1"

_TABLE_HEADERS = ("课程涉及的主要领域", "典型工作任务", "主要教学内容与要求")
_BULLET_PREFIX = re.compile(r"(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.、．])\s*")
_LEAF_PREFIX = re.compile(
    r"^\s*(?:典型工作任务(?:描述)?|主要教学内容与要求)\s*(?:为|是|[:：])?\s*"
)


@dataclass(frozen=True)
class RuleExtractionResult:
    payload: dict[str, Any] | None
    failure_reason: str | None = None


def extract(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract graph-ready rows only from the named normalized-document table."""
    return extract_with_diagnostics(payload).payload


def extract_with_diagnostics(payload: dict[str, Any]) -> RuleExtractionResult:
    """Run the deterministic extractor and retain a bounded fallback reason."""
    if not isinstance(payload, dict) or payload.get("content_type") != "document":
        return RuleExtractionResult(None, "invalid_normalized_document")
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        return RuleExtractionResult(None, "invalid_normalized_document")
    major_code, major_name = _major_identity(str(payload.get("title") or ""), blocks)
    if not major_name:
        return RuleExtractionResult(None, "major_identity_missing")
    rows: list[dict[str, Any]] = []
    table_seen = False
    target_table_seen = False
    incomplete = False
    for block in blocks:
        if not isinstance(block, dict) or block.get("block_type") != "table":
            continue
        table_seen = True
        parsed = _parse_markdown_table(str(block.get("content") or block.get("text") or ""))
        if not parsed:
            continue
        if not _is_target_table(parsed["headers"]):
            continue
        target_table_seen = True
        indexes = _column_indexes(parsed["headers"])
        table_rows: list[dict[str, Any]] = []
        for index, row in enumerate(parsed["data_rows"], start=1):
            cells = row["cells"]
            if _is_repeated_header_row(cells, parsed["headers"]):
                continue
            domain = _normalise_domain(cells[indexes["domain"]])
            task = cells[indexes["task"]].strip()
            requirement = cells[indexes["requirement"]].strip()
            if not domain or (not task and not requirement):
                incomplete = True
                continue
            evidence = _evidence(block, index, row.get("raw"))
            table_rows.append({
                "row_index": index,
                "row_serial": _row_serial(parsed["headers"], cells),
                "occupational_domain": domain,
                "typical_work_tasks": _split_work_tasks(task),
                "skill_knowledge_requirements": _split_bullets(requirement),
                "evidence": evidence,
            })
        rows.extend(_merge_split_logical_rows(table_rows))
    if not rows:
        if target_table_seen:
            return RuleExtractionResult(None, "row_parse_incomplete")
        return RuleExtractionResult(None, "header_alias_unmapped" if table_seen else "target_table_missing")
    if incomplete or any(not row["typical_work_tasks"] or not row["skill_knowledge_requirements"] for row in rows):
        return RuleExtractionResult(None, "row_parse_incomplete")
    return RuleExtractionResult({
        "schema_version": DOMAIN_PROFILE,
        "extractor_version": EXTRACTOR_VERSION,
        "major_code": major_code,
        "major_name": major_name,
        "rows": rows,
        "extractor": {"strategy": "rule", "version": EXTRACTOR_VERSION, "confidence": 1.0},
    })


def _is_target_table(headers: list[str]) -> bool:
    joined = " ".join(headers)
    return all(token in joined for token in _TABLE_HEADERS)


def _column_indexes(headers: list[str]) -> dict[str, int]:
    return {
        "domain": next(i for i, h in enumerate(headers) if "课程涉及的主要领域" in h),
        "task": next(i for i, h in enumerate(headers) if "典型工作任务" in h),
        "requirement": next(i for i, h in enumerate(headers) if "主要教学内容与要求" in h),
    }


def _is_repeated_header_row(cells: list[str], headers: list[str]) -> bool:
    """Ignore a header repeated by a continuation page as a data row."""
    return len(cells) == len(headers) and all(
        _normalise_header_cell(cell) == _normalise_header_cell(header)
        for cell, header in zip(cells, headers)
    )


def _normalise_header_cell(value: str) -> str:
    return re.sub(r"\s+", "", value).strip("：:")


def _row_serial(headers: list[str], cells: list[str]) -> str | None:
    for index, header in enumerate(headers):
        if "序号" not in header:
            continue
        serial = cells[index].strip()
        return serial if re.fullmatch(r"\d{1,3}", serial) else None
    return None


def _normalise_domain(value: str) -> str:
    """Normalize the bounded O2O OCR variant without changing domain semantics."""
    return re.sub(r"(?i)[o0]2[o0]", "O2O", value).strip()


def _domain_identity(value: str) -> str:
    return re.sub(r"[\s\-_/（）()]+", "", _normalise_domain(value)).casefold()


def _merge_split_logical_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge same-table cross-page fragments only when serial and domain agree.

    MinerU/PDF rescue can repeat a long logical row on a later physical page.
    The sequence number is the row identity in the teaching-standard table;
    without it we intentionally leave rows separate rather than guessing.
    """
    merged: list[dict[str, Any]] = []
    by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        serial = row.pop("row_serial", None)
        domain = str(row.get("occupational_domain") or "")
        if not serial or not domain:
            merged.append(row)
            continue
        identity = (serial, _domain_identity(domain))
        previous = by_identity.get(identity)
        if previous is None:
            by_identity[identity] = row
            merged.append(row)
            continue
        previous["typical_work_tasks"] = _unique_texts(
            [*previous["typical_work_tasks"], *row["typical_work_tasks"]]
        )
        previous["skill_knowledge_requirements"] = _unique_texts(
            [*previous["skill_knowledge_requirements"], *row["skill_knowledge_requirements"]]
        )
        previous["evidence"] = _merge_evidence(previous["evidence"], row["evidence"])
    return merged


def _unique_texts(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_leaf_text(value)
        identity = re.sub(r"\s+", "", cleaned).casefold()
        if cleaned and identity not in seen:
            seen.add(identity)
            unique.append(cleaned)
    return unique


def _merge_evidence(first: dict[str, Any], continuation: dict[str, Any]) -> dict[str, Any]:
    first_locator = dict(first.get("locator") or {})
    continuation_locator = dict(continuation.get("locator") or {})
    row_indices = [
        index
        for index in (
            *(first_locator.get("table_row_indices") or [first_locator.get("table_row_index")]),
            *(continuation_locator.get("table_row_indices") or [continuation_locator.get("table_row_index")]),
        )
        if isinstance(index, int)
    ]
    source_rows = _unique_texts([
        str(first.get("source_row") or ""), str(continuation.get("source_row") or ""),
    ])
    return {
        "source_block_ids": list(dict.fromkeys([
            *(first.get("source_block_ids") or []),
            *(continuation.get("source_block_ids") or []),
        ])),
        "locator": {
            **first_locator,
            "table_row_indices": row_indices,
        },
        "source_row": "\n".join(source_rows),
    }


def _major_identity(title: str, blocks: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    text = "\n".join(str(block.get("text") or block.get("content") or "") for block in blocks[:30])
    source = f"{title}\n{text}"
    name_first = re.search(r"([\u4e00-\u9fffA-Za-z]{2,40})\s*[（(]\s*(\d{4,6})\s*[）)]", source)
    if name_first:
        return name_first.group(2), name_first.group(1)
    match = re.search(r"(?:专业名称\s*[（(]?|^\s*)(\d{4,6})\s*([^\n（(）)]{2,40})", source)
    if match:
        return match.group(1), match.group(2).strip(" ：:（()")
    return None, None


def _split_bullets(value: str) -> list[str]:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = value.replace("；", "。")
    parts = _BULLET_PREFIX.split(value)
    if len(parts) == 1:
        parts = re.split(r"[\n。]", value)
    return _unique_texts([
        re.sub(r"\s+", " ", part).strip(" 。；;")
        for part in parts
        if part.strip(" 。；;\n")
    ])


def _split_work_tasks(value: str) -> list[str]:
    """Split explicit `工作内容包括 A、B、C` enumerations without guessing."""
    match = re.search(r"(?:工作内容)?(?:包括|主要有)(.+?)(?:，运用|，使用|。|$)", value)
    if match:
        items = [item.strip(" 、，,。") for item in re.split(r"[、，,]", match.group(1))]
        return _unique_texts([item for item in items if item])
    bullets = _split_bullets(value)
    return _unique_texts([
        item for item in bullets if not item.startswith(("运用", "使用"))
    ])


def _clean_leaf_text(value: str) -> str:
    return _LEAF_PREFIX.sub("", value).strip(" ：:；;。/")


def _evidence(block: dict[str, Any], row_index: int, raw: str | None) -> dict[str, Any]:
    return {
        "source_block_ids": [block.get("block_id")] if block.get("block_id") else [],
        "locator": {
            "page": block.get("page"), "bbox": block.get("bbox"),
            "table_row_index": row_index,
        },
        "source_row": raw or "",
    }
