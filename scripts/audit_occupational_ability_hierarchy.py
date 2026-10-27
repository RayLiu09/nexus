"""Audit cached real ability-analysis workbooks without changing business data.

Input: inventory.json plus <analysis_id>/parsed.json and normalized.json,
collected read-only from the existing analyses and their original objects.
The parsed files must use the canonical xlsx_parser intermediate representation.
Output contains counts and source coordinates, never ability/description text.
This diagnoses extraction feasibility; it does not approve conflicting facts.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "nexus-app"))

from nexus_app.structured_parse.record_body_adapter import (  # noqa: E402
    _ability_sheet_identity,
    _extract_ability,
)


def compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def audit_task(sheet: dict, identity: tuple[str, str]) -> dict:
    descriptions: list[dict] = []
    work_headers: list[dict] = []
    description_active = False
    codes: list[str] = []
    for row in sheet["rows"]:
        cells = [c for c in row["cells"] if c.get("value") is not None
                 and not c.get("is_filled_from_merge")]
        code, _ = _extract_ability(row)
        if code:
            codes.append(code)
        if code or any("能力类别" in compact(c["value"]) for c in cells):
            description_active = False
        if cells and "描述" in compact(cells[0]["value"]):
            description_active = True
            description_cells = cells[1:]
        else:
            description_cells = cells if description_active else []
        descriptions.extend({"row": row["row_index"], "column": c["column"]}
                            for c in description_cells if compact(c["value"]))
        for i, cell in enumerate(cells):
            text = compact(cell["value"])
            label = re.match(r"^工作(?:内容|任务)(?:及)?编号[：:]?(.*)$", text)
            if not label:
                continue
            # Some tables place an entire numbered list inside the label cell.
            if label.group(1) or any(compact(c["value"]) for c in cells[i + 1:]):
                work_headers.append({"row": row["row_index"], "column": cell["column"]})
    counts = Counter(codes)
    return {
        "task_code": identity[0],
        "sheet": sheet["name"],
        "description_cells": descriptions,
        "declared_work_content_headers": work_headers,
        "ability_rows": len(codes),
        "distinct_ability_codes": len(counts),
        "same_task_duplicate_codes": [code for code, count in counts.items() if count > 1],
        # Codes are source identifiers, not inferred facts or generated numbering.
        "codes": codes,
    }


def build_report(directory: Path) -> dict:
    inventory = json.loads((directory / "inventory.json").read_text())
    analyses = []
    for entry in sorted(inventory, key=lambda e: e.get("major_code") or "999999"):
        base = directory / entry["analysis_id"]
        parsed = json.loads((base / "parsed.json").read_text())
        normalized = json.loads((base / "normalized.json").read_text())
        category_headers = []
        tasks = []
        all_codes: list[str] = []
        for sheet in parsed["sheets"]:
            for row in sheet["rows"]:
                hits = [c for c in row["cells"] if compact(c.get("value"))
                        in {"岗位类", "岗位类别", "岗位群"}]
                if hits:
                    category_headers.extend({"sheet": sheet["name"],
                                             "row": row["row_index"],
                                             "column": c["column"]} for c in hits)
            identity = _ability_sheet_identity(sheet)
            if identity:
                task = audit_task(sheet, identity)
                all_codes.extend(task.pop("codes"))
                tasks.append(task)
        frequencies = Counter(all_codes)
        domain_codes = {t["task_code"] for t in normalized["record_body"]["tasks"]}
        analyses.append({
            "analysis_id": entry["analysis_id"],
            "normalized_ref_id": entry["ref_id"],
            "major_code": entry["major_code"],
            "major_name": entry["major_name"],
            "domain_tasks": entry["tasks"],
            "source_tasks": len(tasks),
            "task_count_matches_domain": entry["tasks"] == len(tasks),
            "source_task_codes_missing_from_normalized_record": sorted(
                {t["task_code"] for t in tasks} - domain_codes),
            "domain_work_contents": entry["work_contents"],
            "domain_abilities": entry["abilities"],
            "source_ability_rows": len(all_codes),
            "source_distinct_codes_across_analysis": len(frequencies),
            "source_distinct_codes_within_task": sum(t["distinct_ability_codes"] for t in tasks),
            "tasks_with_description": sum(bool(t["description_cells"]) for t in tasks),
            "tasks_with_declared_work_contents": sum(
                bool(t["declared_work_content_headers"]) for t in tasks),
            "explicit_job_category_headers": category_headers,
            "duplicate_codes_across_analysis": {
                code: count for code, count in frequencies.items() if count > 1},
            "same_task_duplicate_code_count": sum(
                len(t["same_task_duplicate_codes"]) for t in tasks),
            "tasks": tasks,
        })
    return {
        "scope": "read_only_source_structure_audit; not governance acceptance",
        "analysis_count": len(analyses),
        "domain_task_count": sum(a["domain_tasks"] for a in analyses),
        "source_task_count": sum(a["source_tasks"] for a in analyses),
        "source_tasks_with_description": sum(a["tasks_with_description"] for a in analyses),
        "source_tasks_with_declared_work_contents": sum(
            a["tasks_with_declared_work_contents"] for a in analyses),
        "analyses_with_explicit_job_category_headers": sum(
            bool(a["explicit_job_category_headers"]) for a in analyses),
        "analyses": analyses,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.inventory_dir)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "analyses"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
