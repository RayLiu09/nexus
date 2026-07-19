"""Shared factory for the QueryRouterV2 FastAPI dependency.

Both B6 (POST /open/v1/query) and B7 (POST /internal/v1/query) build
a router the same way — differing only in the ``route`` /
``caller_type`` labels they pass to ``router.run()``. Centralising the
factory here keeps the LiteLLM client + executor registry + pgvector
adapter wiring in one place and lets tests substitute a fake router
via FastAPI's ``dependency_overrides``.
"""
from __future__ import annotations

from functools import lru_cache

from nexus_app.ai_governance.services import _create_default_litellm_client
from nexus_app.index.pgvector_search import PgvectorSearchAdapter
from nexus_app.retrieval.router_v2 import QueryRouterV2
from nexus_app.retrieval.tool_executors_v2 import default_v2_executor_registry


@lru_cache(maxsize=1)
def _shared_pgvector_adapter() -> PgvectorSearchAdapter:
    return PgvectorSearchAdapter()


def build_query_router_v2() -> QueryRouterV2:
    """Fresh QueryRouterV2 per request.

    Executor registry, pgvector adapter, and LiteLLM client are
    process-shared; the router itself is a thin dataclass so
    instantiation is trivial. Making one per request keeps future
    per-request hooks (e.g. per-caller rate limits) clean to add.
    """
    adapter = _shared_pgvector_adapter()
    return QueryRouterV2(
        llm_client=_create_default_litellm_client(),
        executor_registry=default_v2_executor_registry(
            pgvector_adapter=adapter,
        ),
        pgvector_adapter=adapter,
    )


def get_query_router_v2() -> QueryRouterV2:
    """FastAPI Depends entry — thin passthrough so tests can override."""
    return build_query_router_v2()


__all__ = [
    "build_query_router_v2",
    "get_query_router_v2",
]
