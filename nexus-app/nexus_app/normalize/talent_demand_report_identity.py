"""Small, source-backed list identity for talent-demand documents."""

from __future__ import annotations

import re
from typing import Any


_REPORT_TITLE = re.compile(r"人才需求.{0,18}(?:报告|调研)|(?:调研|分析).{0,12}人才需求")
_MAJOR_IN_TITLE = re.compile(r"^(.{2,50}?)专业(?:人才需求|人才培养需求)")
_CODE_LABEL = r"专\s*业\s*代\s*码"
_CODE = re.compile(rf"{_CODE_LABEL}\s*[:：]?\s*(\d{{4,6}})")
_MAJOR_LABEL = re.compile(r"专\s*业\s*名\s*称\s*[:：]\s*([^\n]{2,60})")
_INSTITUTION = re.compile(
    r"(?:编制单位|发布单位|学校名称|所属院校)\s*[:：]\s*([^\s，,；;]{3,40})"
)


def extract(title: str, blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Read cover/leading blocks only; surveyed schools are never attribution."""
    clean_title = re.sub(r"\.(?:pdf|docx?)$", "", title.strip(), flags=re.I)
    lead = [block for block in blocks[:12] if isinstance(block, dict)]
    lines = [str(block.get("text") or "").strip() for block in lead]
    if not _REPORT_TITLE.search(clean_title) and not any(_REPORT_TITLE.search(line) for line in lines[:5]):
        return None

    major_name = None
    major_source = None
    for index, line in enumerate([clean_title, *lines[:5]]):
        match = _MAJOR_IN_TITLE.search(line)
        if match:
            major_name = match.group(1).strip(" ：:、 ")
            major_source = None if index == 0 else lead[index - 1].get("block_id")
            break
    code = None
    code_source = None
    institution = None
    institution_source = None
    for index, (block, line) in enumerate(zip(lead, lines, strict=False)):
        explicit_major = _MAJOR_LABEL.search(line)
        if explicit_major:
            major_name = explicit_major.group(1).strip()
            major_source = block.get("block_id")
        if code is None:
            match = _CODE.search(line)
            if match:
                code, code_source = match.group(1), block.get("block_id")
            elif re.search(rf"{_CODE_LABEL}\s*[:：]?\s*$", line) and index + 1 < len(lines):
                next_code = re.fullmatch(r"\s*(\d{4,6})\s*", lines[index + 1])
                if next_code:
                    code, code_source = next_code.group(1), lead[index + 1].get("block_id")
        if institution is None:
            match = _INSTITUTION.search(line)
            if match:
                institution, institution_source = match.group(1), block.get("block_id")

    return {
        "major_name": major_name,
        "major_code": code,
        "institution_name": institution,
        "evidence": {
            "major_name_block_id": major_source,
            "major_code_block_id": code_source,
            "institution_name_block_id": institution_source,
        },
    }
