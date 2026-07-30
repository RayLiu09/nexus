"""Cross-asset projection whitelist (v1.3 §2.4 / v1.3 revision round 2).

Business-defined mapping from **structured record fields** to
``tag_taxonomy`` type codes.  Only fields listed in ``field_projections``
(or matching ``conditional_projections``) get pushed into
``tag_asset_index`` — everything else stays as local SQL
``structured_filters`` inside the domain executor for that table.

Design constraints imposed by v1.3 revision round 2:

1. ``job_demand_requirement_item.item_type`` is a fixed enum
   (``professional_skill / tool / certificate / professional_literacy /
   work_task_candidate``).  Only ``professional_skill`` items are worth
   cross-asset projection — the rest describe local hiring constraints
   (education level, certificate types, etc.) that add noise to the
   cross-asset semantic index.
2. Cross-asset ``ability`` linking between
   ``occupational_ability_item`` / ``job_demand_requirement_item`` /
   ``major_profile_ability`` relies entirely on **text-level semantic
   similarity** — the local ``ability_code`` / ``taxonomy_code`` / etc.
   are internal sequence numbers with no shared vocabulary, so they are
   **not** projected as tags (they stay ``local_only_filters``).
3. Writer-time projection must anticipate the **retrieval-side filter
   vocabulary** documented in
   ``docs/knowledge_retrieval_result_enhancement_v1.3.md §5``.
   Fields that will never be used as cross-asset filters
   (``salary_min``, ``distribution_count``, etc.) stay local.
4. Long free-text fields (job description, responsibilities, requirement
   text) are **not** projected — they belong in the chunk / outline
   layer and would flood ``tag_asset_index`` with noisy topic values.

This module is a v0.1 **code-only** hosting for the whitelist.  A future
milestone will migrate it into ``governance_rules.json.tag_taxonomy``
(see the writer for `projection_whitelist` in v1.3 §16.6) so business
experts can maintain it via the console under the existing fcntl + ETag
protection.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "PROJECTION_WHITELIST_VERSION",
    "PROJECTION_WHITELIST_V1_3",
    "get_field_projections",
    "get_conditional_projections",
    "get_local_only_filters",
    "get_long_text_fields",
    "iter_tables",
]


PROJECTION_WHITELIST_VERSION: str = "0.1"


PROJECTION_WHITELIST_V1_3: dict[str, dict[str, Any]] = {
    # ------------------------------------------------------------------
    # Pipeline A — major_profile abilities extracted from textbooks/plans
    # ------------------------------------------------------------------
    "major_profile_ability": {
        "field_projections": {
            "text": ["ability"],
        },
        "local_only_filters": [
            "item_index",
        ],
    },

    # ------------------------------------------------------------------
    # Pipeline A — knowledge outline nodes (policy / report / textbook)
    # ------------------------------------------------------------------
    "knowledge_outline_node": {
        "field_projections": {
            "title": ["topic"],
        },
        # keywords projected under a dotted metadata path; hook implementations
        # should walk `node_metadata["keywords"]` if it is a list of strings.
        "metadata_projections": {
            "node_metadata.keywords": ["topic"],
        },
        "local_only_filters": [
            "level",
            "anchor_range",
            "chunk_count",
            "numbering_path",
        ],
    },

    # ------------------------------------------------------------------
    # Pipeline A — task outline nodes (task-textbook)
    # ------------------------------------------------------------------
    "task_outline_node": {
        "field_projections": {
            "title": ["topic"],
        },
        "local_only_filters": [
            "task_profile",
            "textbook_subtype",
            "level",
            "node_type",
        ],
    },
}


# ---------------------------------------------------------------------------
# Read helpers — small enough to inline, but keep call sites readable.
# ---------------------------------------------------------------------------


def _cfg(table: str) -> dict[str, Any]:
    if table not in PROJECTION_WHITELIST_V1_3:
        raise KeyError(f"no projection whitelist entry for table '{table}'")
    return PROJECTION_WHITELIST_V1_3[table]


def get_field_projections(table: str) -> dict[str, list[str]]:
    """Return ``{field_name: [tag_type, …]}`` for direct field projections."""
    return dict(_cfg(table).get("field_projections", {}))


def get_conditional_projections(table: str) -> list[dict[str, Any]]:
    """Return the list of ``{when, value_field, target_tag_types}`` rules."""
    return list(_cfg(table).get("conditional_projections", []))


def get_local_only_filters(table: str) -> list[str]:
    return list(_cfg(table).get("local_only_filters", []))


def get_long_text_fields(table: str) -> list[str]:
    return list(_cfg(table).get("long_text_fields", []))


def get_metadata_projections(table: str) -> dict[str, list[str]]:
    """Return ``{dotted_path: [tag_type, …]}`` for metadata projections.

    v1.3 PR-8 addition — dotted paths like ``"node_metadata.keywords"``
    let the engine reach into JSON columns without a per-table SQL
    accessor.  When the terminal segment resolves to a list, the engine
    iterates it and emits one row per element.
    """
    return dict(_cfg(table).get("metadata_projections", {}))


def iter_tables() -> list[str]:
    return list(PROJECTION_WHITELIST_V1_3.keys())
