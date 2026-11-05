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
from fastapi import Request

from nexus_app.ai_governance.services import _create_default_litellm_client
from nexus_app.index.pgvector_search import PgvectorSearchAdapter
from nexus_app.retrieval.router_v2 import QueryRouterV2
from nexus_app.retrieval.tool_executors_v2 import default_v2_executor_registry
from nexus_app.retrieval.web_search import create_default_ai_web_search_client


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
        web_search_client=create_default_ai_web_search_client(),
    )


def get_query_router_v2(request: Request):
    """Console uses public HTTP tools; existing external query behavior stays compatible."""
    if request.url.path.startswith("/internal/v1/query"):
        from nexus_api.function_tools import generate_catalog
        from nexus_api.public_query_runtime import PublicQueryRuntime
        from nexus_api.public_query_tools import PublicToolExecutor
        from nexus_app.config import get_settings
        import uuid

        settings = get_settings()
        catalog = getattr(request.app.state, "public_query_catalog", None)
        if catalog is None:
            catalog = generate_catalog(request.app.openapi())
            request.app.state.public_query_catalog = catalog
        trace_id = getattr(request.state, "trace_id", None) or str(uuid.uuid4())
        executor = PublicToolExecutor(catalog, settings, trace_id=trace_id)
        # Bound a synchronous model round independently of the older router's timeout.
        client_settings = settings.model_copy(update={"litellm_timeout": min(settings.litellm_timeout, 45)})
        return PublicQueryRuntime(executor, _create_default_litellm_client(client_settings, sdk_max_retries=0), settings)
    return build_query_router_v2()


__all__ = [
    "build_query_router_v2",
    "get_query_router_v2",
]
