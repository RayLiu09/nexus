"""Small, source-backed identity metadata for professional-introduction documents."""

from __future__ import annotations

import re
from typing import Any

from nexus_app.major_profile.extractor import extract_institution_identity


def extract_document_metadata(payload: dict[str, Any]) -> dict[str, str | None]:
    title = str(payload.get("title") or "")
    blocks = payload.get("blocks")
    lead = "\n".join(
        str(block.get("text") or block.get("content") or "")
        for block in (blocks[:40] if isinstance(blocks, list) else [])
        if isinstance(block, dict)
    )[:6000]
    labeled_code = re.search(r"(?:专业代码|专业编码)\s*[:：]?\s*(\d{4,6})\b", lead)
    title_identity = re.search(
        r"\b(\d{4,6})\s+([\u4e00-\u9fa5]{2,20}?)"
        r"(?=专业(?:简介|介绍|概况)|[._（(\-]|$)", title,
    )
    code = labeled_code.group(1) if labeled_code else title_identity.group(1) if title_identity else None

    labeled_name = re.search(r"专业名称\s*[:：]\s*([^\n，,；;]{2,60})", lead)
    title_name = re.search(r"([\u4e00-\u9fa5]{2,24})专业(?:介绍|简介|概况)", title)
    name = (
        labeled_name.group(1).strip()
        if labeled_name else title_identity.group(2).strip()
        if title_identity else title_name.group(1).strip()
        if title_name else None
    )
    institution = extract_institution_identity({
        "content_type": "document", "title": title, "blocks": blocks or [],
    })
    level_match = re.search(r"(?:培养层次|学历层次|办学层次)\s*[:：]\s*([^\n，,；;]{2,30})", lead)
    if level_match:
        level = level_match.group(1).strip()
    elif "高职" in title or "高等职业" in title:
        level = "高职"
    elif "中职" in title or "中等职业" in title:
        level = "中职"
    elif "本科" in title:
        level = "本科"
    else:
        level = None
    return {
        "major_name": name,
        "major_code": code,
        "institution_name": institution["institution_name"] if institution else None,
        "education_level": level,
    }
