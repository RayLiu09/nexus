"""Source-bound PGSD headers and work-content identifiers (no AI inference)."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def source_item_key(task_code: str, entry: dict[str, Any]) -> str:
    trace = entry.get("trace") or {}
    location = {k: trace[k] for k in ("sheet", "row", "column") if k in trace}
    identity = [task_code, location] if location else [
        task_code, entry.get("ability_code"), entry.get("ability_content"),
    ]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def original_cells(row: dict) -> list[dict]:
    return [c for c in row.get("cells", []) if c.get("value") is not None
            and not c.get("is_filled_from_merge") and str(c["value"]).strip()]


def compact(text: object) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def task_description(sheet: dict) -> tuple[str | None, list[dict]]:
    parts, evidence = [], []
    active = False
    for row in sheet.get("rows", []):
        cells = original_cells(row)
        if any("能力类别" in compact(c["value"]) or re.match(r"^[PGSD]-", str(c["value"])) for c in cells):
            break
        if cells and "描述" in compact(cells[0]["value"]):
            active = True
            cells = cells[1:]
        if active:
            for cell in cells:
                parts.append(str(cell["value"]).strip())
                evidence.append({"sheet": sheet["name"], "row": row["row_index"], "column": cell["column"]})
    return "\n".join(parts) or None, evidence


def summary_work_contents(workbook: dict, task_code: str) -> dict[str, dict]:
    result = {}
    for sheet in workbook.get("sheets", []):
        if "课程" in sheet.get("name", ""):
            continue
        rows = sheet.get("rows", [])
        # A numbered work-content matrix is different from a PGSD ability sheet.
        if any(re.match(r"^[PGSD]-", str(c.get("value") or "")) for r in rows for c in r.get("cells", [])):
            continue
        headings = {c["column"]: str(c["value"]).strip() for r in rows[:4] for c in original_cells(r)
                    if re.fullmatch(r"\d+", str(c["value"]).strip())}
        for row in rows:
            cells = original_cells(row)
            for index, cell in enumerate(cells[:-2]):
                if str(cell["value"]).strip() != task_code:
                    continue
                if not re.search(r"[A-Za-z\u4e00-\u9fff]", str(cells[index + 1]["value"])):
                    continue
                for content in cells[index + 2:]:
                    number = headings.get(content["column"])
                    if not number:
                        continue
                    code = f"{task_code}{number}" if task_code.isalpha() else f"{task_code}.{number}"
                    name = re.sub(rf"^{re.escape(code)}[.、\s]*", "", str(content["value"]).strip())
                    result.setdefault(code, {
                        "content_code": code, "content_name": name,
                        "content_description": None, "abilities": [], "display_order": int(number),
                        "trace": {"sheet": sheet["name"], "row": row["row_index"],
                                  "column": content["column"], "name_source": "explicit_summary"},
                    })
    return result


def declared_work_contents(sheet: dict, task_code: str, workbook: dict | None = None) -> dict[str, dict]:
    result = {}
    for row in sheet.get("rows", []):
        # Merged label cells also identify continuation rows of a header list.
        cells = [c for c in row.get("cells", []) if c.get("value") is not None]
        for index, cell in enumerate(cells):
            label = re.match(r"^工作(?:内容|任务)(?:及)?编号[：:]?(.*)$", compact(cell["value"]))
            if not label:
                continue
            values = [(label.group(1), cell)] if label.group(1) else []
            values.extend((str(c["value"]), c) for c in cells[index + 1:]
                          if not c.get("is_filled_from_merge"))
            for text, origin in values:
                matches = list(re.finditer(r"(?<![A-Za-z0-9.])([A-Z]\d+|\d+\.\d+|\d+[.、])(?!\d)", text))
                for i, match in enumerate(matches):
                    token = match.group(1)
                    local = token.endswith((".", "、"))
                    number = token.rstrip(".、")
                    code = (f"{task_code}{number}" if task_code.isalpha() else f"{task_code}.{number}") if local else token
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                    name = text[match.end():end].strip(" \t\r\n、，,；;。.")
                    if not name:
                        continue
                    result.setdefault(code, {
                        "content_code": code, "content_name": name,
                        "content_description": None, "abilities": [],
                        "display_order": len(result) + 1,
                        "trace": {"sheet": sheet["name"], "row": row["row_index"],
                                  "column": origin["column"], "name_source": "explicit_header",
                                  "local_number": number if local else None},
                    })
    summary = summary_work_contents(workbook or {}, task_code)
    for code in list(result):
        local = re.search(r"(?:[A-Z]|\.)(\d+)$", code)
        scoped = (f"{task_code}{local.group(1)}" if task_code.isalpha()
                  else f"{task_code}.{local.group(1)}") if local else code
        if code not in summary and scoped in summary:
            original = result.pop(code)
            summary[scoped]["trace"]["header_content_code"] = code
            summary[scoped]["trace"]["header_evidence"] = original["trace"]
    for code, content in summary.items():
        # The matrix provides a source name for an unnumbered/typo header item.
        if code not in result or re.search(rf"[、，,；;]{re.escape(task_code)}[^\d]", result[code]["content_name"]):
            result[code] = content
    return result


def ability_work_code(code: str) -> str:
    body = code.split("-", 1)[-1]
    alpha = re.match(r"^([A-Z]\d+)(?:\.|$)", body)
    if alpha:
        return alpha.group(1)
    parts = body.split(".")
    return ".".join(parts[:2])


def resolve_work_code(code: str, task_code: str, declared: dict[str, dict]) -> tuple[str, bool]:
    candidate = ability_work_code(code)
    if candidate in declared or not declared:
        return candidate, False
    # Header and source code can disagree on task prefix. Preserve the ability
    # code; a unique local number is usable with an explicit inconsistency flag.
    local_match = re.search(r"(?:[A-Z]|\.)(\d+)$", candidate)
    if local_match:
        local = local_match.group(1)
        matches = [key for key in declared if re.search(rf"(?:[A-Z]|\.){re.escape(local)}$", key)]
        if len(matches) == 1:
            return matches[0], True
    return candidate, True
