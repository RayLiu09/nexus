"""Permission filtering hooks for search/QA results.

P0 scope (per user decision, 2026-05-29):
    - apply_permission_filter is a no-op identity function.
    - Authentication via api_caller credentials is the only gate.
    - Once an api_caller is authenticated, it can access all data.

P1 design intent (preserved here as TODO):
    - intersect chunk.org_scope with caller.org_scope and drop non-matching hits.
    - This file keeps the call-site stable so P1 upgrade is a one-line swap.
"""
from __future__ import annotations

import logging
from typing import Any

from nexus_app import models

logger = logging.getLogger(__name__)


def apply_permission_filter(
    caller: models.ApiCaller,
    hits: list[dict[str, Any]],
    *,
    scope_field: str = "org_scope",
) -> list[dict[str, Any]]:
    """Filter search/QA hits by caller permissions.

    P0: identity (returns hits unchanged); read `scope_field` from each hit to
    surface any missing-org-scope warnings early so the P1 cut-over is loud-fail.

    P1 (TODO): intersect each hit's `org_scope` with `caller.org_scope`. Drop hits
    with no intersection. Use `models.ApiCaller.org_scope` once that column is wired
    through the auth dependency.
    """
    if not hits:
        return hits

    # Touch the scope field on every hit so its absence is observable in logs.
    # This guards against P1 going live with hits that have no org_scope at all.
    missing_scope = 0
    for hit in hits:
        scope = hit.get(scope_field)
        if scope is None and (metadata := hit.get("metadata")) and isinstance(metadata, dict):
            scope = metadata.get(scope_field)
        if scope is None:
            missing_scope += 1

    if missing_scope:
        logger.debug(
            "permission_filter: %d/%d hits have no %s field (P0 noop; P1 will require it)",
            missing_scope,
            len(hits),
            scope_field,
        )

    # TODO(P1): when caller.org_scope is wired through, intersect here.
    # caller_scope = set(caller.org_scope or [])
    # if not caller_scope:
    #     return []  # caller has no granted scope
    # return [h for h in hits if set(_extract_scope(h, scope_field)) & caller_scope]
    return hits
