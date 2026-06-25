"""B6 writer — persists `record_body.analysis` into the ability_analysis
domain tables.

Reads the canonical `record_body` shape pinned by
`docs/pipeline_b_contract_freeze.md §5.0.2` (the "职业能力分析" variant)
and writes one row into `occupational_ability_analysis` plus N rows into
each of:

  - `occupational_work_task`
  - `occupational_work_content`
  - `occupational_ability_item` (P / G / S / D)
  - `occupational_ability_relation` (`TASK_HAS_WORK_CONTENT`,
                                     `WORK_CONTENT_REQUIRES_ABILITY`)

The writer is **strictly contract-driven**: every field name comes from
`docs/pipeline_b_b4_b6_contract_freeze.md §二.2` and every quality flag
key comes from §四. Adding new flag keys or new field mappings requires
re-freezing the contract.

What this writer NEVER does (per Forbidden changes §九):
  - call an LLM (B5)
  - write `task_description_structured` to anything other than `{}` (B5)
  - write `ability_analysis_source_dataset` (P0 default = NULL; future
    slice will populate it when `payload.metadata.source_job_demand_dataset_id`
    is set)
  - write `knowledge_chunk` or trigger RAGFlow (Pipeline B never emits
    knowledge chunks — decision 23)
  - create new `quality_flags` keys (only the §四 whitelist)
  - mutate the PGSD profile row
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.domain_normalize.schemas import DomainNormalizeResult
from nexus_app.enums import AuditEventType

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from nexus_app.config import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Quality flag keys frozen by docs/pipeline_b_b4_b6_contract_freeze.md §四.
# Writer must never accumulate keys outside this set.
# ---------------------------------------------------------------------------

FLAG_ABILITY_CODE_PATTERN_MISMATCH = "ability_code_pattern_mismatch"   # non-blocking
FLAG_ABILITY_CATEGORY_UNKNOWN = "ability_category_unknown"             # blocking
FLAG_WORK_CONTENT_MISSING_FOR_P_CATEGORY = "work_content_missing_for_p_category"  # blocking
FLAG_TASK_CODE_DUPLICATE = "task_code_duplicate"                       # blocking (keeps first)
FLAG_CROSS_SHEET_INCONSISTENCY = "cross_sheet_inconsistency"           # non-blocking (decision 17)


# Relation types we write — others (ABILITY_DERIVED_FROM_JOB_REQUIREMENT,
# ABILITY_RELATED_TO_SKILL) are reserved for B5 / later slices.
_REL_TASK_HAS_WORK_CONTENT = "TASK_HAS_WORK_CONTENT"
_REL_WORK_CONTENT_REQUIRES_ABILITY = "WORK_CONTENT_REQUIRES_ABILITY"


def write(
    session: "Session",
    normalized_ref: "models.NormalizedAssetRef",
    record_body: dict[str, Any],
    *,
    settings: "Settings | None" = None,
) -> DomainNormalizeResult:
    """Persist `record_body` into the ability_analysis domain tables.

    See module docstring for contract scope; see §三.3 of the freeze for
    the dataset-level upsert behaviour (delete-then-insert on the unique
    normalized_ref_id key).
    """
    _ = settings  # currently unused; kept on the signature per §五.3

    # ------------------------------------------------------------------ #
    # 1. Resolve the profile by metadata_summary.domain_profile.
    # ------------------------------------------------------------------ #
    domain_profile = (normalized_ref.metadata_summary or {}).get("domain_profile")
    if not domain_profile:
        return DomainNormalizeResult(
            domain_profile=None,
            skipped=True,
            reason="missing_domain_profile",
        )

    profile = session.scalar(
        select(models.AbilityAnalysisProfile).where(
            models.AbilityAnalysisProfile.schema_version == domain_profile,
            models.AbilityAnalysisProfile.is_active.is_(True),
        )
    )
    if profile is None:
        # Don't insert anything; the dispatcher will surface this as a
        # COMPLETED-with-skipped audit. Cleaner than raising — operators
        # see a clear "profile missing" reason instead of a stack trace.
        return DomainNormalizeResult(
            domain_profile=domain_profile,
            skipped=True,
            reason="profile_not_found",
        )

    analysis_block = record_body.get("analysis") if isinstance(record_body, dict) else None
    tasks_block = record_body.get("tasks") if isinstance(record_body, dict) else None
    if not isinstance(analysis_block, dict):
        return DomainNormalizeResult(
            domain_profile=domain_profile,
            skipped=True,
            reason="missing_analysis_block",
        )
    if not isinstance(tasks_block, list):
        tasks_block = []

    declared_model = analysis_block.get("analysis_model")
    if declared_model and declared_model != profile.model_code:
        # Profile / record_body inconsistency: refuse rather than guess.
        return DomainNormalizeResult(
            domain_profile=domain_profile,
            skipped=True,
            reason="analysis_model_mismatch",
        )

    # ------------------------------------------------------------------ #
    # 2. dataset-level idempotency — delete the previous analysis and its
    #    children, then re-insert. We issue explicit per-table deletes
    #    (rather than relying on FK CASCADE) so the test suite works
    #    against SQLite (which doesn't enforce FK constraints by default)
    #    and PG behaves identically. Child tables are listed in dependency
    #    order: leaves first, parents last.
    # ------------------------------------------------------------------ #
    from sqlalchemy import delete

    existing = session.scalar(
        select(models.OccupationalAbilityAnalysis).where(
            models.OccupationalAbilityAnalysis.normalized_ref_id == normalized_ref.id
        )
    )
    if existing is not None:
        analysis_id_to_purge = existing.id
        session.execute(
            delete(models.OccupationalAbilityRelation).where(
                models.OccupationalAbilityRelation.analysis_id == analysis_id_to_purge
            )
        )
        session.execute(
            delete(models.OccupationalAbilityItem).where(
                models.OccupationalAbilityItem.analysis_id == analysis_id_to_purge
            )
        )
        session.execute(
            delete(models.OccupationalWorkContent).where(
                models.OccupationalWorkContent.analysis_id == analysis_id_to_purge
            )
        )
        session.execute(
            delete(models.OccupationalWorkTask).where(
                models.OccupationalWorkTask.analysis_id == analysis_id_to_purge
            )
        )
        session.execute(
            delete(models.AbilityAnalysisSourceDataset).where(
                models.AbilityAnalysisSourceDataset.analysis_id == analysis_id_to_purge
            )
        )
        session.delete(existing)
        # Flush so the unique constraint on normalized_ref_id is freed
        # before we insert the replacement.
        session.flush()

    # ------------------------------------------------------------------ #
    # 3. Build the analysis row (counts filled after rows are written).
    # ------------------------------------------------------------------ #
    analysis = models.OccupationalAbilityAnalysis(
        normalized_ref_id=normalized_ref.id,
        asset_version_id=normalized_ref.version_id,
        profile_id=profile.id,
        analysis_model=profile.model_code,
        major_name=_str_or_none(analysis_block.get("major_name")),
        major_direction=_str_or_none(analysis_block.get("major_direction")),
        # P0 default: source_job_demand_dataset_id stays NULL (§二.2).
        source_job_demand_dataset_id=None,
        schema_version=domain_profile,
        quality_summary={},
    )
    session.add(analysis)
    session.flush()  # need analysis.id for FK in children

    # ------------------------------------------------------------------ #
    # 4. Iterate tasks / work_contents / abilities.
    # ------------------------------------------------------------------ #
    code_pattern: dict[str, Any] = profile.code_pattern or {}
    category_lookup = _build_category_lookup(profile.category_schema or [])

    task_objects: list[models.OccupationalWorkTask] = []
    work_content_objects: list[models.OccupationalWorkContent] = []
    ability_objects: list[models.OccupationalAbilityItem] = []
    relation_objects: list[models.OccupationalAbilityRelation] = []
    quality_summary: dict[str, int] = {}
    abilities_rejected_count = 0
    rejected_examples: list[dict[str, Any]] = []

    seen_task_codes: set[str] = set()
    seen_ability_codes: set[str] = set()
    seen_content_codes: set[str] = set()
    task_display_counter = 0

    for task_entry in tasks_block:
        if not isinstance(task_entry, dict):
            continue
        task_code = _str_or_none(task_entry.get("task_code"))
        task_name = _str_or_none(task_entry.get("task_name"))
        if not task_code or not task_name:
            # Tasks without identifying fields are dropped silently — the
            # contract doesn't define a flag for this; B5 / governance will
            # surface it from `record_count - tasks_written` if needed.
            continue
        if task_code in seen_task_codes:
            _bump(quality_summary, FLAG_TASK_CODE_DUPLICATE)
            continue
        seen_task_codes.add(task_code)
        task_display_counter += 1
        task_obj = models.OccupationalWorkTask(
            analysis_id=analysis.id,
            task_code=task_code,
            task_name=task_name,
            task_description=_str_or_none(task_entry.get("task_description")),
            # B6 ALWAYS writes {} here — B5 LLM fills it later (decision 18).
            task_description_structured={},
            display_order=_coerce_int(
                task_entry.get("display_order"), default=task_display_counter
            ),
            trace=_jsonable_dict(task_entry.get("trace")),
        )
        session.add(task_obj)
        session.flush()
        task_objects.append(task_obj)

        # 4a. work_contents under this task
        wc_entries = task_entry.get("work_contents")
        if not isinstance(wc_entries, list):
            wc_entries = []
        for wc_index, wc_entry in enumerate(wc_entries, start=1):
            if not isinstance(wc_entry, dict):
                continue
            content_code = _str_or_none(wc_entry.get("content_code"))
            content_name = _str_or_none(wc_entry.get("content_name"))
            if not content_code or not content_name:
                continue
            if content_code in seen_content_codes:
                # No dedicated flag; cross_sheet_inconsistency covers the
                # broader "structure conflicts" bucket (decision 17 lenient).
                _bump(quality_summary, FLAG_CROSS_SHEET_INCONSISTENCY)
                continue
            seen_content_codes.add(content_code)
            wc_obj = models.OccupationalWorkContent(
                analysis_id=analysis.id,
                task_id=task_obj.id,
                content_code=content_code,
                content_name=content_name,
                content_description=_str_or_none(wc_entry.get("content_description")),
                display_order=_coerce_int(
                    wc_entry.get("display_order"), default=wc_index,
                ),
                trace=_jsonable_dict(wc_entry.get("trace")),
            )
            session.add(wc_obj)
            session.flush()
            work_content_objects.append(wc_obj)
            # TASK_HAS_WORK_CONTENT relation
            relation_objects.append(
                models.OccupationalAbilityRelation(
                    analysis_id=analysis.id,
                    source_type="task",
                    source_id=task_obj.id,
                    relation_type=_REL_TASK_HAS_WORK_CONTENT,
                    target_type="work_content",
                    target_id=wc_obj.id,
                )
            )

            # 4b. abilities (P-type, under work_content)
            for ability_entry in wc_entry.get("abilities") or []:
                if not isinstance(ability_entry, dict):
                    continue
                rejection_reason = _persist_ability(
                    session=session,
                    analysis=analysis,
                    task_obj=task_obj,
                    work_content_obj=wc_obj,
                    ability_entry=ability_entry,
                    code_pattern=code_pattern,
                    category_lookup=category_lookup,
                    quality_summary=quality_summary,
                    ability_objects=ability_objects,
                    relation_objects=relation_objects,
                    seen_ability_codes=seen_ability_codes,
                )
                if rejection_reason is not None:
                    abilities_rejected_count += 1
                    if len(rejected_examples) < 20:
                        rejected_examples.append({
                            "ability_code": ability_entry.get("ability_code"),
                            "reason": rejection_reason,
                        })

        # 4c. general_abilities under this task (G / S / D)
        general_block = task_entry.get("general_abilities")
        if isinstance(general_block, dict):
            for category_code, items in general_block.items():
                if not isinstance(items, list):
                    continue
                for ability_entry in items:
                    if not isinstance(ability_entry, dict):
                        continue
                    # If the entry omitted its category, fall back to the
                    # dict key — common shape from record_body where the
                    # outer key already names the category.
                    if not ability_entry.get("ability_major_category_code"):
                        ability_entry = {
                            **ability_entry,
                            "ability_major_category_code": category_code,
                        }
                    rejection_reason = _persist_ability(
                        session=session,
                        analysis=analysis,
                        task_obj=task_obj,
                        work_content_obj=None,
                        ability_entry=ability_entry,
                        code_pattern=code_pattern,
                        category_lookup=category_lookup,
                        quality_summary=quality_summary,
                        ability_objects=ability_objects,
                        relation_objects=relation_objects,
                        seen_ability_codes=seen_ability_codes,
                    )
                    if rejection_reason is not None:
                        abilities_rejected_count += 1
                        if len(rejected_examples) < 20:
                            rejected_examples.append({
                                "ability_code": ability_entry.get("ability_code"),
                                "reason": rejection_reason,
                            })

    # ------------------------------------------------------------------ #
    # 5. Flush relations + roll up counts + quality summary.
    # ------------------------------------------------------------------ #
    session.add_all(relation_objects)
    session.flush()

    analysis.task_count = len(task_objects)
    analysis.work_content_count = len(work_content_objects)
    analysis.ability_item_count = len(ability_objects)
    analysis.quality_summary = dict(quality_summary)
    session.flush()

    # ------------------------------------------------------------------ #
    # 6. Audit events — `ABILITY_ANALYSIS_PERSISTED`, then either
    #    `ABILITY_ITEMS_PERSISTED` (always) and (when applicable)
    #    `ABILITY_ITEMS_REJECTED`. Trace id passes through normalized_ref
    #    lineage if present.
    # ------------------------------------------------------------------ #
    trace_id = _resolve_trace_id(normalized_ref)
    write_audit(
        session,
        AuditEventType.ABILITY_ANALYSIS_PERSISTED,
        target_type="occupational_ability_analysis",
        target_id=analysis.id,
        trace_id=trace_id,
        summary={
            "normalized_ref_id": normalized_ref.id,
            "profile_id": profile.id,
            "model_code": profile.model_code,
            "schema_version": domain_profile,
            "task_count": analysis.task_count,
            "work_content_count": analysis.work_content_count,
            "ability_item_count": analysis.ability_item_count,
            "quality_summary": dict(quality_summary),
        },
    )
    write_audit(
        session,
        AuditEventType.ABILITY_ITEMS_PERSISTED,
        target_type="occupational_ability_analysis",
        target_id=analysis.id,
        trace_id=trace_id,
        summary={
            "abilities_written": len(ability_objects),
            "relations_written": len(relation_objects),
        },
    )
    if abilities_rejected_count > 0:
        write_audit(
            session,
            AuditEventType.ABILITY_ITEMS_REJECTED,
            target_type="occupational_ability_analysis",
            target_id=analysis.id,
            trace_id=trace_id,
            summary={
                "abilities_rejected": abilities_rejected_count,
                "examples": rejected_examples,
            },
        )

    return DomainNormalizeResult(
        domain_profile=domain_profile,
        analysis_id=analysis.id,
        records_written=analysis.task_count,
        items_written=len(ability_objects),
        quality_summary={
            **dict(quality_summary),
            # Convenience counters surfaced for the dispatcher audit summary —
            # not part of the on-row quality_summary so we don't double-count.
            "_tasks_written": len(task_objects),
            "_work_contents_written": len(work_content_objects),
            "_abilities_written": len(ability_objects),
            "_abilities_rejected": abilities_rejected_count,
            "_relations_written": len(relation_objects),
            "_profile_id": profile.id,
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _persist_ability(
    *,
    session: "Session",
    analysis: models.OccupationalAbilityAnalysis,
    task_obj: models.OccupationalWorkTask,
    work_content_obj: models.OccupationalWorkContent | None,
    ability_entry: dict[str, Any],
    code_pattern: dict[str, Any],
    category_lookup: dict[str, dict[str, Any]],
    quality_summary: dict[str, int],
    ability_objects: list[models.OccupationalAbilityItem],
    relation_objects: list[models.OccupationalAbilityRelation],
    seen_ability_codes: set[str],
) -> str | None:
    """Persist one ability entry. Returns None on success or the rejection
    reason key when the row was dropped (`abilities_rejected++`).
    """
    ability_code = _str_or_none(ability_entry.get("ability_code"))
    ability_content = _str_or_none(ability_entry.get("ability_content"))
    category_code = _str_or_none(ability_entry.get("ability_major_category_code"))
    if not ability_code or not ability_content or not category_code:
        # Missing identifying field — treat as category_unknown for audit
        # bucketing (no dedicated flag in the §四 whitelist).
        _bump(quality_summary, FLAG_ABILITY_CATEGORY_UNKNOWN)
        return FLAG_ABILITY_CATEGORY_UNKNOWN

    if category_code not in category_lookup:
        _bump(quality_summary, FLAG_ABILITY_CATEGORY_UNKNOWN)
        return FLAG_ABILITY_CATEGORY_UNKNOWN

    category_meta = category_lookup[category_code]
    category_name = category_meta.get("name") or category_code
    pattern_meta = code_pattern.get(category_code) or {}
    requires_work_content = bool(pattern_meta.get("requires_work_content", False))

    # Enforce the work_content gating from the profile.
    if requires_work_content and work_content_obj is None:
        _bump(quality_summary, FLAG_WORK_CONTENT_MISSING_FOR_P_CATEGORY)
        return FLAG_WORK_CONTENT_MISSING_FOR_P_CATEGORY

    if ability_code in seen_ability_codes:
        # Same code under the same analysis — reject silently as a
        # cross-sheet inconsistency (decision 17 = lenient). The unique
        # constraint would surface this anyway; we catch it earlier so the
        # rejection counter increments properly.
        _bump(quality_summary, FLAG_CROSS_SHEET_INCONSISTENCY)
        return FLAG_CROSS_SHEET_INCONSISTENCY

    # Per-row quality flags (non-blocking).
    per_row_flags: dict[str, Any] = {}
    regex_str = pattern_meta.get("regex")
    if isinstance(regex_str, str) and regex_str:
        try:
            if re.fullmatch(regex_str, ability_code) is None:
                per_row_flags[FLAG_ABILITY_CODE_PATTERN_MISMATCH] = True
                _bump(quality_summary, FLAG_ABILITY_CODE_PATTERN_MISMATCH)
        except re.error:
            # Bad regex in the profile shouldn't crash writes; flag it.
            per_row_flags[FLAG_ABILITY_CODE_PATTERN_MISMATCH] = True
            _bump(quality_summary, FLAG_ABILITY_CODE_PATTERN_MISMATCH)

    ability_sequence = _extract_sequence(ability_code, category_code)

    item = models.OccupationalAbilityItem(
        analysis_id=analysis.id,
        task_id=task_obj.id,
        # NULL when requires_work_content=False (G/S/D in PGSD).
        work_content_id=work_content_obj.id if work_content_obj is not None else None,
        ability_code=ability_code,
        ability_major_category_code=category_code,
        ability_major_category_name=category_name,
        ability_sequence=ability_sequence,
        ability_content=ability_content,
        normalized_terms=_jsonable_dict(ability_entry.get("normalized_terms")),
        confidence=None,  # B6 doesn't set confidence; B5 LLM does
        quality_flags=per_row_flags,
        trace=_jsonable_dict(ability_entry.get("trace")),
    )
    session.add(item)
    session.flush()
    ability_objects.append(item)
    seen_ability_codes.add(ability_code)

    # WORK_CONTENT_REQUIRES_ABILITY relation — only when we actually have a
    # work_content parent (G/S/D abilities skip this and hang on the task).
    if work_content_obj is not None:
        relation_objects.append(
            models.OccupationalAbilityRelation(
                analysis_id=analysis.id,
                source_type="work_content",
                source_id=work_content_obj.id,
                relation_type=_REL_WORK_CONTENT_REQUIRES_ABILITY,
                target_type="ability_item",
                target_id=item.id,
            )
        )
    return None


def _build_category_lookup(category_schema: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """code → {name, alias, ...}. Defensive against malformed seed."""
    lookup: dict[str, dict[str, Any]] = {}
    for entry in category_schema or []:
        if not isinstance(entry, dict):
            continue
        code = entry.get("code")
        if isinstance(code, str) and code:
            lookup[code] = entry
    return lookup


def _extract_sequence(ability_code: str, category_code: str) -> str:
    """Strip the `<category>-` prefix to derive the bare sequence (e.g.
    `P-1.1.1` → `1.1.1`). Falls back to the full code when the prefix
    isn't present (defensive — should not happen for whitelisted categories).
    """
    prefix = f"{category_code}-"
    if ability_code.startswith(prefix):
        return ability_code[len(prefix):]
    return ability_code


def _coerce_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        # bool is a subclass of int in Python — guard against `True` slipping in.
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except (TypeError, ValueError):
            return default
    return default


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return str(value)


def _jsonable_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _bump(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _resolve_trace_id(ref: "models.NormalizedAssetRef") -> str | None:
    lineage = ref.lineage or {}
    trace = lineage.get("trace_id")
    if isinstance(trace, str):
        return trace
    return None


__all__ = ["write"]
