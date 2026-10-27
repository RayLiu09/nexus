"""B3.5 — project a `ParsedWorkbook` dump into the contract-shape `record_body`.

Without this adapter the `domain_normalize` dispatcher always skips with
`record_body_shape_invalid`, because B3's `_build_normalized_record` writes
the raw `ParsedWorkbook.model_dump()` straight into `payload.record_body`,
whereas the B4 / B6 writers consume the JSON shapes frozen in
`docs/pipeline_b_contract_freeze.md §5.0.2`:

- `job_demand.v1` → `{dataset: {...}, records: [...]}`
- `ability_analysis.pgsd.v1` → `{analysis: {...}, tasks: [...]}`

The adapter is invoked from `pipeline/stages.py:_build_normalized_record`
once a `profile_dict` is available. When `profile_dict` is None (legacy JSON
ingestion that never runs through `profile_detect`), the raw payload passes
through unchanged so existing JSON pipelines keep working.

Design notes
------------
- The adapter is **content-shape only** — it does NOT classify, validate, or
  reject rows. Quality / placeholder / fingerprint logic stays in the
  writers (per `pipeline_b_b4_b6_contract_freeze.md §六 / §四`), so a future
  schema-version bump only touches one layer.
- Sheet / header inspection is **structural**, not column-position-dependent.
  Header aliases reuse the canonical aliases from `profile_detect.config`
  so the projection and the classifier agree on what each column means.
- Unknown profiles return the raw payload (dispatcher will skip downstream).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from nexus_app.capability_graph.major_normalizer import (
    extract_ability_analysis_major_identity,
    normalize_major_code,
    normalize_major_name,
)
from nexus_app.major_catalog import complete_major_identity
from nexus_app.structured_parse.ability_hierarchy import (
    declared_work_contents, resolve_work_code, source_item_key, task_description,
)
from nexus_app.profile_detect.config import (
    JOB_DEMAND_HEADER_ALIASES,
    JOB_DEMAND_OPTIONAL_HEADERS,
    PGSD_CATEGORY_ALIASES,
    PGSD_CODE_PREFIX_PATTERN,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Header → canonical-field aliases for `job_demand.v1`
# ---------------------------------------------------------------------------
# These map every alias we accept on the sheet header row to the field name
# the B4 writer reads from `record_body.records[]`. Keep canonical lowercase
# field names aligned with `pipeline_b_contract_freeze.md §5.2` exactly —
# any drift here silently breaks the writer's field mapping.
_JOB_DEMAND_FIELD_MAP: dict[str, str] = {
    # job_title
    "岗位名称": "job_title", "职位名称": "job_title", "岗位": "job_title",
    "职位": "job_title", "岗位名": "job_title", "招聘岗位": "job_title",
    "job_title": "job_title", "position": "job_title", "position_name": "job_title",
    # city
    "城市": "city", "工作城市": "city", "工作地点": "city", "工作地": "city",
    "city": "city", "work_city": "city", "location": "city",
    # company_name
    "公司名称": "company_name", "企业名称": "company_name", "公司": "company_name",
    "company": "company_name", "company_name": "company_name", "employer": "company_name",
    # salary / numerics
    "薪资": "salary_text", "薪水": "salary_text", "工资": "salary_text",
    "salary": "salary_text",
    "最低薪资": "salary_min", "salary_min": "salary_min",
    "最高薪资": "salary_max", "salary_max": "salary_max",
    # experience / education
    "经验要求": "experience_requirement", "工作经验": "experience_requirement",
    "经验": "experience_requirement", "experience": "experience_requirement",
    "学历要求": "education_requirement", "学历": "education_requirement",
    "education": "education_requirement",
    # description / skills
    "岗位描述": "job_description", "岗位说明": "job_description",
    "职位描述": "job_description", "job_description": "job_description",
    "description": "job_description",
    "岗位技能说明": "job_skill_text", "技能要求": "job_skill_text",
    "skills": "job_skill_text",
    "岗位职责": "responsibility_text", "工作职责": "responsibility_text",
    "responsibility": "responsibility_text", "responsibilities": "responsibility_text",
    "任职要求": "requirement_text", "requirement": "requirement_text",
    "requirements": "requirement_text",
    # enterprise / industry
    "公司规模": "enterprise_size", "企业规模": "enterprise_size",
    "company_size": "enterprise_size", "enterprise_size": "enterprise_size",
    "所属产业": "industry_name", "所属行业": "industry_name",
    "所属产业/行业": "industry_name", "行业": "industry_name",
    "industry": "industry_name",
    # company address
    "公司地址": "company_address", "company_address": "company_address",
    "address": "company_address",
    # employment / function
    "岗位类型": "employment_type", "工作类型": "employment_type",
    "employment_type": "employment_type",
    "职能类别": "job_function_category", "function": "job_function_category",
    "job_function_category": "job_function_category",
    "job_count": "job_count", "招聘人数": "job_count", "人数": "job_count",
    # publish + source provenance
    "发布时间": "source_published_at", "publish_time": "source_published_at",
    "published_at": "source_published_at",
    "source_url": "source_url", "url": "source_url", "链接": "source_url",
    "source_platform": "source_platform", "平台": "source_platform",
    "source_record_key": "source_record_key", "记录id": "source_record_key",
    "记录ID": "source_record_key",
}


def project_to_record_body(
    raw_payload: dict[str, Any],
    profile_dict: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a record_body in the shape the domain writer expects.

    `raw_payload` is the JSON-dumped `ParsedWorkbook` (see `structured_parse`).
    When `profile_dict` is None or carries an unknown `domain_profile`,
    `raw_payload` is returned unchanged.
    """
    if not profile_dict:
        return raw_payload
    domain_profile = profile_dict.get("domain_profile")
    if domain_profile == "job_demand.v1":
        return _project_job_demand(raw_payload, profile_dict)
    if domain_profile == "major_distribution.v1":
        raise ValueError("major_distribution Pipeline B is retired; use Ministry API sync")
    if domain_profile == "ability_analysis.pgsd.v1":
        return _project_ability_analysis_pgsd(raw_payload, profile_dict)
    return raw_payload


# ---------------------------------------------------------------------------
# job_demand.v1 projection
# ---------------------------------------------------------------------------

def _project_job_demand(
    raw_payload: dict[str, Any], profile_dict: dict[str, Any]
) -> dict[str, Any]:
    sheets = raw_payload.get("sheets") or []
    records: list[dict[str, Any]] = []

    for sheet in sheets:
        sheet_name = sheet.get("name") or ""
        rows = sheet.get("rows") or []
        header_row, header_index = _detect_header_row(rows)
        if header_row is None or header_index is None:
            continue
        # Build column-index → canonical-field map from the header row.
        col_to_field: dict[int, str] = {}
        for cell in header_row.get("cells") or []:
            label = _norm_text(cell.get("value"))
            if not label:
                continue
            field = _JOB_DEMAND_FIELD_MAP.get(label)
            if field:
                col_to_field[int(cell["column"])] = field

        if not col_to_field:
            continue

        # Every non-placeholder, non-empty row after the header becomes a record.
        for row in rows:
            if int(row.get("row_index", 0)) <= int(header_row["row_index"]):
                continue
            if row.get("is_empty") or row.get("is_placeholder_candidate"):
                continue
            record: dict[str, Any] = {
                "source_record_key": f"{sheet_name}#row{row['row_index']}",
                "trace": {"sheet": sheet_name, "row": row["row_index"]},
            }
            for cell in row.get("cells") or []:
                col = int(cell["column"])
                field = col_to_field.get(col)
                if not field:
                    continue
                value = cell.get("value")
                # Empty / blank strings → None so the writer treats them
                # uniformly with absent columns.
                if isinstance(value, str) and not value.strip():
                    value = None
                if value is None:
                    continue
                # Numeric coercion for salary_min / salary_max / job_count.
                if field in ("salary_min", "salary_max", "job_count"):
                    coerced = _coerce_int(value)
                    if coerced is not None:
                        record[field] = coerced
                else:
                    # source_record_key sheet+row default is overridden when a
                    # real key column is present.
                    record[field] = value
            # Drop rows that didn't pick up *any* meaningful field beyond the
            # synthesized trace / key — likely a separator / decoration row.
            if len(record) <= 2:
                continue
            records.append(record)

    dataset = {
        "source_channel": "excel_upload",
        "record_count": len(records),
        "invalid_count": 0,    # writer recomputes from quality_flags
        "duplicate_count": 0,
    }
    # Surface major / industry hints from the profile evidence if present.
    evidence = profile_dict.get("evidence") or {}
    if isinstance(evidence, dict):
        if evidence.get("major_name"):
            dataset["major_name"] = evidence["major_name"]
        if evidence.get("industry_name"):
            dataset["industry_name"] = evidence["industry_name"]

    return {"dataset": dataset, "records": records}


def _detect_header_row(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, int | None]:
    """Find the first row whose cell labels overlap the header alias set.

    Returns `(row, index)` where `index` is the position in `rows`. Returns
    `(None, None)` when no row hits the alias set — caller skips the sheet.
    """
    alias_set = JOB_DEMAND_HEADER_ALIASES | JOB_DEMAND_OPTIONAL_HEADERS
    for idx, row in enumerate(rows):
        if row.get("is_empty") or row.get("is_placeholder_candidate"):
            continue
        hit = 0
        for cell in row.get("cells") or []:
            label = _norm_text(cell.get("value"))
            if label and label in alias_set:
                hit += 1
                if hit >= 2:
                    return row, idx
    return None, None


def _coerce_int(value: Any) -> int | None:
    """Pull an int out of cell values like "5", 5.0, "5人". Returns None otherwise."""
    if isinstance(value, bool):  # bool is a subclass of int — exclude explicitly
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return int(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+", value)
        if match:
            try:
                return int(match.group(0))
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------------
# ability_analysis.pgsd.v1 projection
# ---------------------------------------------------------------------------

# Per-task sheet name pattern is `^\d+\.<chinese>...` (see profile_detect
# config). The number is the task code; the suffix is the task name.
_TASK_ID_FROM_ABILITY = re.compile(r"^P-([A-Z]|\d+)")


def _ability_sheet_identity(sheet: dict[str, Any]) -> tuple[str, str] | None:
    """Identify a task sheet by its professional-ability rows, not its tab label."""
    sheet_name = str(sheet.get("name") or "").strip()
    if "课程转化" in sheet_name:
        return None
    first_code: str | None = None
    for row in sheet.get("rows") or []:
        code, _ = _extract_ability(row)
        if code and code.startswith("P-"):
            first_code = code
            break
    if not first_code:
        return None
    code_match = _TASK_ID_FROM_ABILITY.match(first_code)
    if not code_match:
        return None
    task_code = code_match.group(1)
    tab_number = re.match(r"^(\d+)\.[^\d]", sheet_name)
    tab_letter = re.match(r"^(?:职业能力分析表)?([A-Z])(?:\s|$)", sheet_name)
    if tab_number:
        task_code = tab_number.group(1)
    elif tab_letter:
        task_code = tab_letter.group(1)
    for row in sheet.get("rows") or []:
        cells = row.get("cells") or []
        if len(cells) < 2:
            continue
        label = str(cells[0].get("value") or "").replace(" ", "")
        if len(label) > 40 or not label.startswith(("典型工作任务", "典型职业活动", "典型职业")):
            continue
        value = str(cells[1].get("value") or "").strip()
        if value and not value.startswith(("工作", "能力")):
            explicit = re.match(r"^([A-Z]|\d+)[.、\s]*([^\d].*)$", value, re.S)
            if explicit:
                return explicit.group(1), re.sub(r"\s+", "", explicit.group(2))
            name = re.sub(rf"^{re.escape(task_code)}[.、\s]*", "", value).strip()
            if name:
                return task_code, name
    name = re.sub(r"^\d+\.\d+", "", sheet_name).strip()
    name = re.sub(r"^(?:\d+-\d+\.)?PGSD能力分析表[-_]?", "", name).strip()
    name = re.sub(rf"^{re.escape(task_code)}[.、\s]*", "", name).strip()
    name = re.sub(r"(?:PGSD)?能力分析表.*$", "", name).strip()
    return task_code, name or sheet_name


def _project_ability_analysis_pgsd(
    raw_payload: dict[str, Any], profile_dict: dict[str, Any]
) -> dict[str, Any]:
    sheets = raw_payload.get("sheets") or []
    tasks: list[dict[str, Any]] = []

    for sheet in sheets:
        sheet_name = sheet.get("name") or ""
        identity = _ability_sheet_identity(sheet)
        if not identity:
            continue
        task_code, task_name = identity

        rows = sheet.get("rows") or []
        # Build hierarchical structure: walk rows, maintain "current work content"
        # whenever we encounter an ability code that names a new content_code.
        work_contents: dict[str, dict[str, Any]] = declared_work_contents(sheet, task_code, raw_payload)
        general_abilities: dict[str, list[dict[str, Any]]] = {"G": [], "S": [], "D": []}
        description, description_evidence = task_description(sheet)
        source_entries: list[dict[str, Any]] = []

        for row in rows:
            if row.get("is_empty") or row.get("is_placeholder_candidate"):
                continue
            ability_code, ability_content = _extract_ability(row)
            if not ability_code:
                continue
            category = ability_code[0]  # 'P' | 'G' | 'S' | 'D'
            row_index = row.get("row_index")
            entry = {
                "ability_code": ability_code,
                "ability_major_category_code": category,
                "ability_content": ability_content,
                "trace": {"sheet": sheet_name, "row": row_index},
            }
            entry["source_item_key"] = source_item_key(task_code, entry)
            source_entries.append(entry)

            if category == "P":
                # P-1.1.1 → content_code = "1.1" (first two segments after dash)
                content_code, inconsistent = resolve_work_code(ability_code, task_code, work_contents)
                if inconsistent:
                    entry["quality_flags"] = {"cross_sheet_inconsistency": True}
                    entry["trace"]["parent_resolution"] = "local_number_or_code_fallback"
                wc = work_contents.setdefault(content_code, {
                    "content_code": content_code,
                    "content_name": content_code,
                    "content_description": None,
                    "abilities": [],
                    "trace": {"sheet": sheet_name, "row": row_index, "name_source": "ability_fallback"},
                })
                if wc["content_name"] == content_code:
                    inferred_name = _infer_work_content_name(ability_content)
                    if inferred_name:
                        wc["content_name"] = inferred_name
                        wc["content_description"] = ability_content
                wc["abilities"].append(entry)
            elif category in ("G", "S", "D"):
                general_abilities[category].append(entry)

        code_counts: dict[str, int] = {}
        for entry in source_entries:
            code_counts[entry["ability_code"]] = code_counts.get(entry["ability_code"], 0) + 1
        for entry in source_entries:
            if code_counts[entry["ability_code"]] > 1:
                entry["quality_flags"] = {**entry.get("quality_flags", {}), "cross_sheet_inconsistency": True}
                entry["trace"]["duplicate_source_code"] = True

        tasks.append({
            "task_code": task_code,
            "task_name": task_name,
            "task_description": description,
            "task_description_structured": None,
            "display_order": int(task_code) if task_code.isdigit() else 0,
            "trace": {"sheet": sheet_name, "description_evidence": description_evidence},
            "work_contents": list(work_contents.values()),
            "general_abilities": general_abilities,
        })

    # Compute summary counts the writer would re-derive otherwise.
    work_content_total = sum(len(t["work_contents"]) for t in tasks)
    ability_total = 0
    for t in tasks:
        for wc in t["work_contents"]:
            ability_total += len(wc["abilities"])
        for cat_list in t["general_abilities"].values():
            ability_total += len(cat_list)

    analysis = {
        "analysis_model": "PGSD",
        "task_count": len(tasks),
        "work_content_count": work_content_total,
        "ability_item_count": ability_total,
    }
    # Preserve explicit profile evidence first.  The PGSD detector currently
    # identifies the analysis shape but does not extract professional
    # identity, so fall back to the parsed workbook's source filename.  This
    # stays inside the normalized-record projection boundary and never
    # reopens raw workbook bytes.
    evidence = profile_dict.get("evidence") or {}
    explicit_major_name = None
    if isinstance(evidence, dict) and isinstance(evidence.get("major_name"), str):
        explicit_major_name = normalize_major_name(evidence["major_name"])
    filename_code, filename_name = extract_ability_analysis_major_identity(
        raw_payload.get("source_filename")
    )
    major_name = explicit_major_name or filename_name
    explicit_code = evidence.get("major_code") if isinstance(evidence, dict) else None
    normalized_code = normalize_major_code(explicit_code)
    major_code = normalized_code if normalized_code and len(normalized_code) == 6 else filename_code
    major_code, major_name, education_level = complete_major_identity(major_code, major_name)
    if major_name:
        analysis["major_name"] = major_name
    if major_code:
        analysis["major_code"] = major_code
    if education_level:
        analysis["education_level"] = education_level
    if isinstance(evidence, dict):
        if evidence.get("major_direction"):
            analysis["major_direction"] = evidence["major_direction"]

    return {"analysis": analysis, "tasks": tasks}


def _infer_work_content_name(ability_content: str | None) -> str | None:
    """Infer a readable work-content label from the first P ability sentence.

    Some PGSD spreadsheets encode work content only in the P ability code
    group (e.g. `P-1.1.*`) and put no explicit work-content name column in
    the sheet. In that case using `1.1` as the graph node label is not useful.
    This helper keeps the inference deterministic and conservative: remove
    common ability-modal prefixes, then keep the remaining action phrase.
    """
    if not ability_content:
        return None
    text = str(ability_content).strip()
    if not text:
        return None
    text = re.sub(r"^[，,；;。.\s]+", "", text)
    text = re.sub(r"^(具备|掌握|熟悉|了解|理解|能够|能|会|可|可以)", "", text).strip()
    text = re.sub(r"^(运用|使用|利用)", "", text).strip()
    text = re.sub(r"^[，,；;。.\s]+", "", text)
    return text[:128] or None


def _extract_ability(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (ability_code, ability_content) for a row, or (None, None) when absent.

    The code is detected anywhere in the row (typical layout puts it in column
    B after a category column A); the content is the longest other non-empty
    string cell on the row.
    """
    ability_code: str | None = None
    candidates: list[str] = []
    for cell in row.get("cells") or []:
        value = cell.get("value")
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        if ability_code is None and PGSD_CODE_PREFIX_PATTERN.match(text):
            ability_code = text
        else:
            candidates.append(text)
    if not ability_code:
        return None, None
    # Strip category-name cells so they don't drown the real content.
    candidates = [c for c in candidates if _norm_text(c) not in PGSD_CATEGORY_ALIASES.keys()
                  and c not in {"职业能力", "通用能力", "社会能力", "发展能力", "职业技能"}]
    content = max(candidates, key=len) if candidates else None
    return ability_code, content


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _norm_text(value: Any) -> str:
    """Cell value → NFKC-normalized, stripped, lowercased string. Empty → ""."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).lower()


__all__ = ["project_to_record_body"]
