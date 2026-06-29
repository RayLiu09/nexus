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

from nexus_app.profile_detect.config import (
    JOB_DEMAND_HEADER_ALIASES,
    JOB_DEMAND_OPTIONAL_HEADERS,
    MAJOR_CODE_PATTERN,
    MAJOR_DISTRIBUTION_HEADER_ALIASES,
    MAJOR_DISTRIBUTION_TOTAL_MARKERS,
    PGSD_CATEGORY_ALIASES,
    PGSD_CODE_PREFIX_PATTERN,
    PGSD_SHEET_NAME_PATTERN,
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
        return _project_major_distribution(raw_payload, profile_dict)
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


# ---------------------------------------------------------------------------
# major_distribution.v1 projection
# ---------------------------------------------------------------------------


def _project_major_distribution(
    raw_payload: dict[str, Any], profile_dict: dict[str, Any]
) -> dict[str, Any]:
    sheets = raw_payload.get("sheets") or []
    records: list[dict[str, Any]] = []
    ignored_summary_count = 0
    placeholder_count = 0
    invalid_count = 0
    field_inference = {
        "education_level": {"filled": False, "source": None, "evidence": None},
    }

    for sheet in sheets:
        sheet_name = sheet.get("name") or ""
        rows = sheet.get("rows") or []
        header_row, _header_index = _detect_major_distribution_header_row(rows)
        if header_row is None:
            continue
        col_to_field = _major_distribution_column_map(header_row)
        if not col_to_field:
            continue

        for row in rows:
            row_index = int(row.get("row_index", 0))
            if row_index <= int(header_row.get("row_index", 0)):
                continue
            if row.get("is_placeholder_candidate"):
                placeholder_count += 1
                continue
            if row.get("is_empty"):
                continue

            record: dict[str, Any] = {
                "source_record_key": f"{sheet_name}#row{row_index}",
                "trace": {"sheet": sheet_name, "row": row_index, "columns": {}},
                "quality_flags": [],
            }
            for cell in row.get("cells") or []:
                column = int(cell["column"])
                field = col_to_field.get(column)
                if not field:
                    continue
                value = cell.get("value")
                if isinstance(value, str) and not value.strip():
                    value = None
                if value is None:
                    continue
                if field == "source_row_no":
                    record["source_row_no"] = str(value).strip()
                elif field == "year":
                    year, year_text = _parse_year(value)
                    record["year_text"] = year_text
                    if year is not None:
                        record["year"] = year
                elif field == "distribution_count":
                    count = _coerce_int(value)
                    if count is not None:
                        record["distribution_count"] = count
                elif field == "major_code":
                    code = _normalise_major_code(value)
                    if code:
                        record["major_code"] = code
                elif field == "province_name":
                    record["province_name"] = str(value).strip()
                elif field == "education_level":
                    record["education_level"] = str(value).strip()
                elif field == "major_name":
                    record["major_name"] = str(value).strip()
                record["trace"]["columns"][field] = cell.get("column_letter")

            province = record.get("province_name")
            if province in MAJOR_DISTRIBUTION_TOTAL_MARKERS:
                ignored_summary_count += 1
                continue

            if not _major_distribution_required_present(record):
                invalid_count += 1
                continue

            if not MAJOR_CODE_PATTERN.match(str(record["major_code"])):
                record["quality_flags"].append("major_code_invalid")
            if int(record["distribution_count"]) < 0:
                record["quality_flags"].append("distribution_count_invalid")
            record["region_scope"] = "province" if province else "unknown"
            record.setdefault("education_level", None)
            records.append(record)

    major_codes = {r.get("major_code") for r in records if r.get("major_code")}
    major_names = {r.get("major_name") for r in records if r.get("major_name")}
    education_levels = {
        r.get("education_level") for r in records if r.get("education_level")
    }
    years = [int(r["year"]) for r in records if isinstance(r.get("year"), int)]

    dataset: dict[str, Any] = {
        "dataset_name": raw_payload.get("source_filename") or "major_distribution_dataset",
        "source_channel": "excel_upload",
        "major_scope": (
            "single_major" if len(major_codes) == 1
            else "multi_major" if len(major_codes) > 1 else "unknown"
        ),
        "record_count": len(records),
        "invalid_count": invalid_count,
        "placeholder_count": placeholder_count,
        "ignored_summary_count": ignored_summary_count,
        "duplicate_count": 0,
    }
    if len(major_codes) == 1:
        dataset["major_code"] = next(iter(major_codes))
    if len(major_names) == 1:
        dataset["major_name"] = next(iter(major_names))
    if len(education_levels) == 1:
        dataset["education_level"] = next(iter(education_levels))
    if years:
        dataset["year_min"] = min(years)
        dataset["year_max"] = max(years)
    dataset["province_count"] = len({
        r.get("province_name") for r in records if r.get("province_name")
    })

    evidence = profile_dict.get("evidence") or {}
    if isinstance(evidence, dict):
        dataset.setdefault("major_name", evidence.get("major_name"))
        dataset.setdefault("major_code", evidence.get("major_code"))

    return {
        "dataset": dataset,
        "records": records,
        "field_inference": field_inference,
    }


def _detect_major_distribution_header_row(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, int | None]:
    aliases = {
        _norm_text(alias)
        for values in MAJOR_DISTRIBUTION_HEADER_ALIASES.values()
        for alias in values
    }
    for idx, row in enumerate(rows):
        if row.get("is_empty") or row.get("is_placeholder_candidate"):
            continue
        hit = 0
        for cell in row.get("cells") or []:
            label = _norm_text(cell.get("value"))
            if label and label in aliases:
                hit += 1
        if hit >= 3:
            return row, idx
    return None, None


def _major_distribution_column_map(header_row: dict[str, Any]) -> dict[int, str]:
    alias_to_field = {
        _norm_text(alias): field
        for field, aliases in MAJOR_DISTRIBUTION_HEADER_ALIASES.items()
        for alias in aliases
    }
    col_to_field: dict[int, str] = {}
    for cell in header_row.get("cells") or []:
        label = _norm_text(cell.get("value"))
        field = alias_to_field.get(label)
        if field:
            col_to_field[int(cell["column"])] = field
    return col_to_field


def _parse_year(value: Any) -> tuple[int | None, str | None]:
    text = str(value).strip() if value is not None else None
    if not text:
        return None, None
    match = re.search(r"(19|20)\d{2}", text)
    return (int(match.group(0)) if match else None, text)


def _normalise_major_code(value: Any) -> str | None:
    text = _norm_text(value)
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _major_distribution_required_present(record: dict[str, Any]) -> bool:
    return all(
        record.get(field) is not None
        for field in (
            "year", "province_name", "major_name", "major_code",
            "distribution_count",
        )
    )


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
_TASK_SHEET_HEADER = re.compile(r"^(\d+)\.\s*(.+)$")


def _project_ability_analysis_pgsd(
    raw_payload: dict[str, Any], profile_dict: dict[str, Any]
) -> dict[str, Any]:
    sheets = raw_payload.get("sheets") or []
    tasks: list[dict[str, Any]] = []

    for sheet in sheets:
        sheet_name = sheet.get("name") or ""
        if not PGSD_SHEET_NAME_PATTERN.match(sheet_name):
            continue
        match = _TASK_SHEET_HEADER.match(sheet_name)
        if not match:
            continue
        task_code, task_name = match.group(1), match.group(2).strip()

        rows = sheet.get("rows") or []
        # Build hierarchical structure: walk rows, maintain "current work content"
        # whenever we encounter an ability code that names a new content_code.
        work_contents: dict[str, dict[str, Any]] = {}
        general_abilities: dict[str, list[dict[str, Any]]] = {"G": [], "S": [], "D": []}

        for row in rows:
            if row.get("is_empty") or row.get("is_placeholder_candidate"):
                continue
            ability_code, ability_content = _extract_ability(row)
            if not ability_code:
                continue
            category = ability_code[0]  # 'P' | 'G' | 'S' | 'D'
            row_index = row.get("row_index")

            if category == "P":
                # P-1.1.1 → content_code = "1.1" (first two segments after dash)
                code_body = ability_code.split("-", 1)[1] if "-" in ability_code else ability_code
                parts = code_body.split(".")
                content_code = ".".join(parts[:2]) if len(parts) >= 2 else code_body
                wc = work_contents.setdefault(content_code, {
                    "content_code": content_code,
                    "content_name": content_code,
                    "content_description": None,
                    "abilities": [],
                })
                if wc["content_name"] == content_code:
                    inferred_name = _infer_work_content_name(ability_content)
                    if inferred_name:
                        wc["content_name"] = inferred_name
                        wc["content_description"] = ability_content
                wc["abilities"].append({
                    "ability_code": ability_code,
                    "ability_major_category_code": "P",
                    "ability_content": ability_content,
                    "trace": {"sheet": sheet_name, "row": row_index},
                })
            elif category in ("G", "S", "D"):
                general_abilities[category].append({
                    "ability_code": ability_code,
                    "ability_content": ability_content,
                    "trace": {"sheet": sheet_name, "row": row_index},
                })

        tasks.append({
            "task_code": task_code,
            "task_name": task_name,
            "task_description": None,
            "task_description_structured": None,
            "display_order": int(task_code) if task_code.isdigit() else 0,
            "trace": {"sheet": sheet_name},
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
    # Surface major hints from profile evidence if available.
    evidence = profile_dict.get("evidence") or {}
    if isinstance(evidence, dict):
        if evidence.get("major_name"):
            analysis["major_name"] = evidence["major_name"]
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
