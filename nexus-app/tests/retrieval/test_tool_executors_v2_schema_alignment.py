"""Contract test: every executor's ``arguments[...]`` reads must
match its declared schema in ``config/query_router_tools.json``.

Why this exists — Batch B0.2 rewrote
``internal.get_job_demand_role_graph``'s schema (dropped
``dataset_id``, made ``job_title`` required) but the executor kept
reading ``arguments["dataset_id"]``. The LLM emitted schema-
conforming args, args validation passed, and the executor
immediately KeyError'd, cratering scenario_2 in production. A later
audit found ``query_ability_analysis`` had the same class of drift
(``arguments["major"]`` vs schema-required ``major_name``).

This test scans ``tool_executors_v2.py`` with the Python AST module,
extracts every ``arguments["key"]`` (required-style) and
``arguments.get("key")`` (optional-style) access, and cross-checks
against every scenario's declared schema. Any future schema tweak
without the matching executor change trips the test.

Rules:

* An ``arguments["X"]`` access is only legal when X is in
  ``required`` for EVERY scenario the tool appears in.  If a scenario
  makes X optional, the executor cannot assume its presence.
* An ``arguments.get("X")`` access is legal when X is in
  ``properties`` for at least one scenario the tool appears in, OR
  when the executor explicitly whitelists X as a legacy alias
  (``LEGACY_ALIAS_ALLOWLIST`` below — kept small; new aliases require
  an explicit test opt-in so we don't drift back into KeyError land).
* Every schema-``required`` field must be read by the executor in
  some form (``[...]`` OR ``.get(...)``). An unread required arg
  means the executor is ignoring what the LLM was forced to supply.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from nexus_app.retrieval import tool_executors_v2
from nexus_app.retrieval.tools_registry import get_default_tool_registry


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Legacy arg aliases the executor is permitted to `.get()` even though
# the current schema doesn't declare them. Kept intentionally sparse so
# a new alias requires an explicit entry (and reviewer eyeballs).
LEGACY_ALIAS_ALLOWLIST: dict[str, set[str]] = {
    "internal.query_ability_analysis": {"major"},
}

# Tool name → (top-level function name, nested closure name or None).
# When the wired executor is a closure returned by a factory
# (``make_search_chunks_executor``), we walk the factory's AST body to
# find the nested FunctionDef.
EXECUTOR_FN_BY_TOOL: dict[str, tuple[str, str | None]] = {
    "internal.search_chunks_by_semantic": ("make_search_chunks_executor", "_run"),
    "internal.query_major_information": ("query_major_information", None),
    "internal.query_capability_graph_by_major":
        ("query_capability_graph_by_major", None),
    "internal.get_evidence_graph_by_ref": ("get_evidence_graph_by_ref", None),
    "internal.query_job_demand": ("query_job_demand", None),
    "internal.get_job_demand_role_graph": ("get_job_demand_role_graph", None),
    "internal.query_ability_analysis": ("query_ability_analysis", None),
    "internal.query_major_distribution": ("query_major_distribution", None),
    "internal.get_outline_subtree": ("get_outline_subtree", None),
}


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


_SOURCE_PATH = Path(inspect.getfile(tool_executors_v2))
_MODULE_TREE = ast.parse(_SOURCE_PATH.read_text(encoding="utf-8"))


def _find_toplevel_function(name: str) -> ast.FunctionDef:
    for node in _MODULE_TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(
        f"tool_executors_v2 has no top-level function {name!r}"
    )


def _find_nested_function(parent: ast.FunctionDef, name: str) -> ast.FunctionDef:
    for node in ast.walk(parent):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(
        f"factory {parent.name!r} has no nested function {name!r}"
    )


def _executor_ast_for(tool_name: str) -> ast.FunctionDef:
    top, nested = EXECUTOR_FN_BY_TOOL[tool_name]
    parent = _find_toplevel_function(top)
    return _find_nested_function(parent, nested) if nested else parent


def _collect_argument_accesses(fn: ast.FunctionDef) -> tuple[set[str], set[str]]:
    """Return ``(required_style_keys, optional_style_keys)``.

    Required-style: ``arguments["X"]``.
    Optional-style: ``arguments.get("X")`` (with or without default).
    """
    required: set[str] = set()
    optional: set[str] = set()
    for node in ast.walk(fn):
        # arguments["X"]
        if isinstance(node, ast.Subscript):
            value = node.value
            slice_node = node.slice
            if (
                isinstance(value, ast.Name)
                and value.id == "arguments"
                and isinstance(slice_node, ast.Constant)
                and isinstance(slice_node.value, str)
            ):
                required.add(slice_node.value)
        # arguments.get("X" [, default])
        if isinstance(node, ast.Call):
            fn_node = node.func
            if (
                isinstance(fn_node, ast.Attribute)
                and fn_node.attr == "get"
                and isinstance(fn_node.value, ast.Name)
                and fn_node.value.id == "arguments"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                optional.add(node.args[0].value)
    return required, optional


# ---------------------------------------------------------------------------
# Schema helpers — a tool may appear in multiple scenarios with subtly
# different schemas (e.g. `search_chunks_by_semantic` in scenarios
# 1 / 3 / 4). We compare against:
#   - intersection of `required` — any arg accessed as `[X]` must be
#     required in EVERY scenario, else the executor would crash in the
#     scenario that makes X optional.
#   - union of `properties` — any arg accessed as `.get(X)` must be
#     declared in at least one scenario.
# ---------------------------------------------------------------------------


def _schema_shapes_for(tool_name: str) -> tuple[set[str], set[str]]:
    registry = get_default_tool_registry()
    schemas: list[dict] = []
    for scenario_id in registry.scenarios.keys():
        for tool in registry.for_scenario(scenario_id):
            if tool.name == tool_name:
                schemas.append(tool.parameters)
    if not schemas:
        raise AssertionError(
            f"tool {tool_name!r} is registered as an executor but "
            f"not declared in any scenario schema"
        )
    required_sets = [set(s.get("required", []) or []) for s in schemas]
    property_sets = [set((s.get("properties") or {}).keys()) for s in schemas]
    required_intersect = set.intersection(*required_sets) if required_sets else set()
    required_union = set.union(*required_sets) if required_sets else set()
    property_union = set.union(*property_sets) if property_sets else set()
    return required_intersect, required_union, property_union  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Contract assertions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", sorted(EXECUTOR_FN_BY_TOOL.keys()))
def test_executor_required_access_matches_schema(tool_name: str):
    """Every ``arguments["X"]`` MUST be schema-required in every
    scenario that carries this tool.

    This is the check that would have caught the
    ``get_job_demand_role_graph`` regression when the schema dropped
    ``dataset_id``: the AST still contained ``arguments["dataset_id"]``,
    but ``dataset_id`` was no longer in ``required``, so this test
    would have failed loud in CI instead of production.
    """
    fn = _executor_ast_for(tool_name)
    required_accesses, _ = _collect_argument_accesses(fn)
    required_intersect, _, _ = _schema_shapes_for(tool_name)
    illegal = required_accesses - required_intersect
    assert not illegal, (
        f"{tool_name}: executor accesses arguments[X] where X is not "
        f"schema-required in every scenario using this tool. "
        f"Offending keys: {sorted(illegal)}. "
        f"Fix: either add X to schema.required OR switch the executor "
        f"to arguments.get(X)."
    )


@pytest.mark.parametrize("tool_name", sorted(EXECUTOR_FN_BY_TOOL.keys()))
def test_executor_optional_access_matches_schema_or_alias(tool_name: str):
    """Every ``arguments.get("X")`` MUST be a declared property in at
    least one scenario OR an explicit legacy alias."""
    fn = _executor_ast_for(tool_name)
    _, optional_accesses = _collect_argument_accesses(fn)
    _, _, property_union = _schema_shapes_for(tool_name)
    allowed_aliases = LEGACY_ALIAS_ALLOWLIST.get(tool_name, set())
    illegal = optional_accesses - property_union - allowed_aliases
    assert not illegal, (
        f"{tool_name}: executor reads arguments.get(X) where X is not "
        f"in the schema.properties union and not in "
        f"LEGACY_ALIAS_ALLOWLIST. Offending keys: {sorted(illegal)}. "
        f"Fix: either declare X in the tool schema OR add X to "
        f"LEGACY_ALIAS_ALLOWLIST with a review comment."
    )


@pytest.mark.parametrize("tool_name", sorted(EXECUTOR_FN_BY_TOOL.keys()))
def test_executor_reads_every_required_arg(tool_name: str):
    """Every schema-``required`` field (union across scenarios) must
    be read somewhere in the executor. An unread required arg is a
    silent contract violation — the LLM was forced to supply the
    value and the executor ignores it, which is almost always a bug
    (spec change without impl change, or vice versa)."""
    fn = _executor_ast_for(tool_name)
    required_accesses, optional_accesses = _collect_argument_accesses(fn)
    _, required_union, _ = _schema_shapes_for(tool_name)
    read_somehow = required_accesses | optional_accesses
    unread = required_union - read_somehow
    assert not unread, (
        f"{tool_name}: executor never reads required args {sorted(unread)}. "
        f"Fix: either read them (arguments[X] or arguments.get(X)) or "
        f"drop them from schema.required."
    )


def test_every_registered_executor_has_a_contract_row():
    """Guards against a new executor landing in
    ``default_v2_executor_registry`` without a matching row in
    ``EXECUTOR_FN_BY_TOOL`` — otherwise the contract tests silently
    skip it."""
    # Use a stub adapter to avoid loading LiteLLM config just to enumerate
    # registered names.
    from types import SimpleNamespace
    stub = SimpleNamespace(search=lambda *args, **kwargs: [])
    registry = tool_executors_v2.default_v2_executor_registry(pgvector_adapter=stub)
    registered = set(registry.executors.keys())
    covered = set(EXECUTOR_FN_BY_TOOL.keys())
    missing = registered - covered
    assert not missing, (
        f"executor(s) {sorted(missing)} are wired into "
        f"default_v2_executor_registry() but have no row in "
        f"EXECUTOR_FN_BY_TOOL. Add them so the contract tests cover them."
    )
    orphan = covered - registered
    assert not orphan, (
        f"EXECUTOR_FN_BY_TOOL declares {sorted(orphan)} which are no "
        f"longer in default_v2_executor_registry(). Remove the stale rows."
    )
