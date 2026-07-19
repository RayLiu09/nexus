"""B6/B7 (§10 阶段 B) — Query Router v2.0 top-level orchestrator.

Ties Layer 1 (intent + parameter extraction), Layer 2 (dispatcher),
and Layer 3 (Markdown composer) into a single ``run()`` call that both
``POST /open/v1/query`` (api_caller) and ``POST /internal/v1/query``
(console user) entry points call through.

Design red lines picked up here:

* **Fallback taxonomy** (§六 + §1.11 决策 #4): ``unknown`` intent OR
  dispatcher fallbacks other than ``scenario_5_template`` route to the
  §六 vector-only top-K path (``kb=None``, ``top_k=20``,
  ``similarity_threshold=0.3``) before Composer runs.
* **scenario_5** — Agentic RAG template executor is not in P0 batch B3a
  scope; the router surfaces a clear ``scenario_5_template_not_implemented``
  reason so the entry point can respond with an informative message.
* **Audit summary** (§8.2): the return type carries every field the
  §八 audit spec lists (route / caller_type / intent / intent_confidence
  / invoked_tools / generated_ratio / template_id / query_route=v2 /
  missing_optional_params / chart_hallucination_ids / chart_unused_ids
  / dispatch_fallback / matched_queries / expand_queries_status). The
  entry point drops it into ``audit_log.summary`` verbatim.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

from sqlalchemy.orm import Session

from nexus_app.ai_governance.litellm_client import LiteLLMClientProtocol
from nexus_app.audit_v2_retrieval import (
    CallerType,
    IntentType,
    RetrievalV2SummaryFields,
    RouteType,
    build_retrieval_v2_summary,
)
from nexus_app.index.pgvector_search import PgvectorSearchAdapter
from nexus_app.retrieval.chart_adapter import ChartRegistry
from nexus_app.retrieval.composer_v2 import (
    ComposeResult,
    ComposeStreamEvent,
    MDComposerV2,
)
from nexus_app.retrieval.dispatcher_v2 import (
    DispatchResult,
    DispatcherV2,
    ToolExecutorRegistry,
    ToolResult,
)
from nexus_app.retrieval.intent_v2 import IntentClassifierV2, IntentV2Result
from nexus_app.retrieval.parameter_extractor import (
    ParameterExtractorV2,
    ParamExtractionResult,
)
from nexus_app.retrieval.prompt_profiles_v2 import DEFAULT_V2_LITELLM_ALIAS
from nexus_app.retrieval.tools_registry import (
    ToolRegistry,
    get_default_tool_registry,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


RouterStreamEventType = Literal["meta", "chunk", "final", "done", "error"]


@dataclass(frozen=True)
class RouterStreamEvent:
    """One event on the ``QueryRouterV2.run_stream`` iterator.

    * ``meta`` — first event, always. Carries ``intent`` /
      ``intent_confidence`` / ``invoked_tools`` (empty when the
      fallback path fires) / registered ``chart_ids`` so the frontend
      can pre-allocate placeholders before any prose arrives.
    * ``chunk`` — incremental raw markdown chunk from the Composer's
      streaming call. Not emitted on the scenario_5 stub path.
    * ``final`` — sent immediately before ``done``. Payload is a
      ``RouterResult`` with markdown = the fully-swapped composer
      output (§7.3 chart placeholder replacement done ONCE at the end).
    * ``done`` — terminating event. Payload is empty; audit_summary
      is on the preceding ``final`` event.
    * ``error`` — non-fatal warning surfaced mid-stream. When the
      backend downgrades to fallback markdown the ``final`` event still
      fires; ``error`` here is informational (e.g. ``llm_call_failed``).
    """

    type: RouterStreamEventType
    text: str = ""
    result: "RouterResult | None" = None
    meta: dict[str, Any] | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RouterResult:
    """What the router returns to the FastAPI entry point.

    * ``markdown`` — final Composer output with chart placeholders
      replaced. Suitable for direct streaming / return.
    * ``raw_markdown`` — pre-replacement text; entry points that stream
      via SSE can emit this incrementally and swap only in the final
      event (§7.3).
    * ``audit_summary`` — the RetrievalV2SummaryFields-shaped dict the
      entry point drops into ``audit_log.summary`` alongside the
      existing v1 fields (``query_hash`` etc.).
    * ``fallback_reason`` — high-level marker for the entry point:
      ``None`` = happy path; ``unknown_fallback`` / ``scenario_5_template_not_implemented``
      / other = distinct handling if the caller wants to shape the
      response differently (still returns markdown either way).
    """

    markdown: str
    raw_markdown: str
    audit_summary: dict[str, Any]
    intent: str
    intent_confidence: float
    invoked_tools: list[str]
    fallback_reason: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


_UNKNOWN_FALLBACK_TOP_K = 20
_UNKNOWN_FALLBACK_SIMILARITY = 0.3


@dataclass
class QueryRouterV2:
    """Top-level orchestrator for query-router-v2.

    Constructor deps:
    * ``llm_client`` — shared client for intent / param / dispatcher / composer.
    * ``executor_registry`` — real ToolExecutor callables.
    * ``pgvector_adapter`` — used for the §六 unknown-fallback path.
    * ``tool_registry`` / ``model_alias`` — optional overrides.

    Threading the same ``llm_client`` through every layer keeps the
    LiteLLM alias + retry behaviour consistent across the request.
    """

    llm_client: LiteLLMClientProtocol
    executor_registry: ToolExecutorRegistry
    pgvector_adapter: PgvectorSearchAdapter | None = None
    tool_registry: ToolRegistry | None = None
    model_alias: str = DEFAULT_V2_LITELLM_ALIAS

    def run(
        self,
        session: Session,
        *,
        query: str,
        route: RouteType,
        caller_type: CallerType,
    ) -> RouterResult:
        registry = self.tool_registry or get_default_tool_registry()

        # ------------------------------------------------------------
        # Layer 1: intent classification
        # ------------------------------------------------------------
        intent_classifier = IntentClassifierV2(llm_client=self.llm_client)
        intent_result = intent_classifier.classify(session, query)

        # ------------------------------------------------------------
        # Layer 1: parameter extraction
        # ------------------------------------------------------------
        param_extractor = ParameterExtractorV2(
            llm_client=self.llm_client, registry=registry,
        )
        param_result = param_extractor.extract(
            session,
            query=query,
            intent=intent_result.intent,
        )

        # ------------------------------------------------------------
        # Layer 2: dispatcher — skipped for unknown / no-tools scenarios.
        # ------------------------------------------------------------
        if intent_result.intent == "unknown" or intent_result.low_confidence:
            return self._unknown_fallback_path(
                session,
                query=query,
                intent_result=intent_result,
                param_result=param_result,
                route=route,
                caller_type=caller_type,
                trigger=(
                    "low_confidence"
                    if intent_result.low_confidence
                    else "unknown_intent"
                ),
            )

        dispatcher = DispatcherV2(
            llm_client=self.llm_client,
            executor_registry=self.executor_registry,
            registry=registry,
        )
        dispatch_result = dispatcher.dispatch(
            session,
            query=query,
            intent=intent_result.intent,
            extracted_params=param_result.extracted_params,
            model_alias=self.model_alias,
        )

        if dispatch_result.fallback_reason == "scenario_5_template":
            return self._scenario_5_placeholder(
                query=query,
                intent_result=intent_result,
                param_result=param_result,
                route=route,
                caller_type=caller_type,
            )

        if dispatch_result.fallback_reason is not None:
            # unknown_intent / no_tool_call / param_validation_failed /
            # llm_call_failed / no_tools_registered / tool_execution_failed
            # → all route through §六 vector-only fallback.
            return self._unknown_fallback_path(
                session,
                query=query,
                intent_result=intent_result,
                param_result=param_result,
                route=route,
                caller_type=caller_type,
                trigger=dispatch_result.fallback_reason,
                dispatch_result=dispatch_result,
            )

        # ------------------------------------------------------------
        # Layer 3: composer
        # ------------------------------------------------------------
        composer = MDComposerV2(llm_client=self.llm_client)
        compose_result = composer.compose(
            session, query=query, dispatch_result=dispatch_result,
        )

        summary = self._build_summary(
            route=route,
            caller_type=caller_type,
            intent_result=intent_result,
            param_result=param_result,
            dispatch_result=dispatch_result,
            compose_result=compose_result,
        )

        return RouterResult(
            markdown=compose_result.markdown,
            raw_markdown=compose_result.raw_markdown,
            audit_summary=summary,
            intent=intent_result.intent,
            intent_confidence=intent_result.confidence,
            invoked_tools=dispatch_result.invoked_tool_names,
            fallback_reason=compose_result.fallback_reason,
            warnings=tuple(list(dispatch_result.warnings)
                           + list(compose_result.warnings)),
        )

    # ------------------------------------------------------------------ #
    # Streaming variant — used by /internal|open/v1/query/stream
    # ------------------------------------------------------------------ #

    def run_stream(
        self,
        session: Session,
        *,
        query: str,
        route: RouteType,
        caller_type: CallerType,
    ) -> Iterator[RouterStreamEvent]:
        """SSE-oriented streaming variant of :meth:`run`.

        Emits events in this order:

        1. Exactly one ``meta`` event once L1/L2 finish (so the
           frontend can render the intent / tool badges before any
           prose lands).
        2. Zero or more ``chunk`` events during Composer streaming.
        3. Exactly one ``final`` event (or ``fallback`` from Composer
           translated into a final event with fallback_reason set).
        4. Exactly one ``done`` event.

        Unknown-intent / dispatcher-fallback / scenario_5 paths bypass
        Composer streaming entirely — they emit ``meta`` → the fully
        pre-baked ``final`` payload → ``done`` (no ``chunk`` events).
        This keeps the client's rendering path uniform: whenever a
        ``final`` event arrives, the accumulated chunk text should be
        discarded in favour of ``result.markdown``.
        """
        registry = self.tool_registry or get_default_tool_registry()

        # ------------------------------------------------------------
        # Layer 1: intent + params (non-streaming; identical to run())
        # ------------------------------------------------------------
        intent_classifier = IntentClassifierV2(llm_client=self.llm_client)
        intent_result = intent_classifier.classify(session, query)

        param_extractor = ParameterExtractorV2(
            llm_client=self.llm_client, registry=registry,
        )
        param_result = param_extractor.extract(
            session, query=query, intent=intent_result.intent,
        )

        # ------------------------------------------------------------
        # Short-circuit unknown / low-confidence — no chunk stream.
        # ------------------------------------------------------------
        if intent_result.intent == "unknown" or intent_result.low_confidence:
            trigger = (
                "low_confidence"
                if intent_result.low_confidence
                else "unknown_intent"
            )
            yield RouterStreamEvent(
                type="meta",
                meta={
                    "intent": "unknown",
                    "intent_confidence": intent_result.confidence,
                    "invoked_tools": [],
                    "chart_ids": [],
                    "fallback_reason": "unknown_fallback",
                },
            )
            result = self._unknown_fallback_path(
                session,
                query=query,
                intent_result=intent_result,
                param_result=param_result,
                route=route,
                caller_type=caller_type,
                trigger=trigger,
            )
            yield RouterStreamEvent(type="final", result=result)
            yield RouterStreamEvent(type="done")
            return

        # ------------------------------------------------------------
        # Layer 2: dispatcher (non-streaming; tool exec is parallel).
        # ------------------------------------------------------------
        dispatcher = DispatcherV2(
            llm_client=self.llm_client,
            executor_registry=self.executor_registry,
            registry=registry,
        )
        dispatch_result = dispatcher.dispatch(
            session,
            query=query,
            intent=intent_result.intent,
            extracted_params=param_result.extracted_params,
            model_alias=self.model_alias,
        )

        if dispatch_result.fallback_reason == "scenario_5_template":
            yield RouterStreamEvent(
                type="meta",
                meta={
                    "intent": "scenario_5",
                    "intent_confidence": intent_result.confidence,
                    "invoked_tools": [],
                    "chart_ids": [],
                    "template_id": "talent_cultivation_plan",
                },
            )
            result = self._scenario_5_placeholder(
                query=query,
                intent_result=intent_result,
                param_result=param_result,
                route=route,
                caller_type=caller_type,
            )
            yield RouterStreamEvent(type="final", result=result)
            yield RouterStreamEvent(type="done")
            return

        if dispatch_result.fallback_reason is not None:
            yield RouterStreamEvent(
                type="meta",
                meta={
                    "intent": intent_result.intent,
                    "intent_confidence": intent_result.confidence,
                    "invoked_tools": [],
                    "chart_ids": [],
                    "fallback_reason": "unknown_fallback",
                    "dispatch_fallback": dispatch_result.fallback_reason,
                },
            )
            result = self._unknown_fallback_path(
                session,
                query=query,
                intent_result=intent_result,
                param_result=param_result,
                route=route,
                caller_type=caller_type,
                trigger=dispatch_result.fallback_reason,
                dispatch_result=dispatch_result,
            )
            yield RouterStreamEvent(type="final", result=result)
            yield RouterStreamEvent(type="done")
            return

        # ------------------------------------------------------------
        # Layer 3: Composer streams chunks; router aggregates + emits
        # a final event with the fully-swapped markdown.
        # ------------------------------------------------------------
        yield RouterStreamEvent(
            type="meta",
            meta={
                "intent": intent_result.intent,
                "intent_confidence": intent_result.confidence,
                "invoked_tools": dispatch_result.invoked_tool_names,
                "chart_ids": sorted(
                    dispatch_result.chart_registry.registered_ids()
                ),
            },
        )

        composer = MDComposerV2(llm_client=self.llm_client)
        compose_result: ComposeResult | None = None
        for event in composer.compose_stream(
            session, query=query, dispatch_result=dispatch_result,
        ):
            if event.type == "chunk":
                yield RouterStreamEvent(type="chunk", text=event.text)
            elif event.type == "final":
                compose_result = event.result
            elif event.type == "fallback":
                compose_result = event.result
                if event.result and event.result.fallback_reason:
                    yield RouterStreamEvent(
                        type="error",
                        reason=event.result.fallback_reason,
                    )

        if compose_result is None:
            # Composer stream ended without emitting final/fallback —
            # defensive; treat as empty_llm_output so the client sees
            # a terminating event with a stable fallback marker.
            compose_result = ComposeResult(
                markdown="", raw_markdown="",
                generated_ratio=0.0,
                fallback_reason="empty_llm_output",
            )
            yield RouterStreamEvent(
                type="error", reason="empty_llm_output",
            )

        summary = self._build_summary(
            route=route,
            caller_type=caller_type,
            intent_result=intent_result,
            param_result=param_result,
            dispatch_result=dispatch_result,
            compose_result=compose_result,
        )
        result = RouterResult(
            markdown=compose_result.markdown,
            raw_markdown=compose_result.raw_markdown,
            audit_summary=summary,
            intent=intent_result.intent,
            intent_confidence=intent_result.confidence,
            invoked_tools=dispatch_result.invoked_tool_names,
            fallback_reason=compose_result.fallback_reason,
            warnings=tuple(list(dispatch_result.warnings)
                           + list(compose_result.warnings)),
        )
        yield RouterStreamEvent(type="final", result=result)
        yield RouterStreamEvent(type="done")

    # ------------------------------------------------------------------ #
    # Fallback paths
    # ------------------------------------------------------------------ #

    def _unknown_fallback_path(
        self,
        session: Session,
        *,
        query: str,
        intent_result: IntentV2Result,
        param_result: ParamExtractionResult,
        route: RouteType,
        caller_type: CallerType,
        trigger: str,
        dispatch_result: DispatchResult | None = None,
    ) -> RouterResult:
        """§六 vector-only cross-type top-K fallback.

        Called when: intent==unknown, intent low_confidence, or the
        dispatcher couldn't produce tool results. Runs pgvector across
        all knowledge types (``kb=None``), then hands the flat hit list
        to Composer wrapped as a synthetic ``search_chunks`` tool result
        so the compose prompt has a stable shape.
        """
        chart_registry = (
            dispatch_result.chart_registry
            if dispatch_result is not None
            else ChartRegistry()
        )
        hits: list[dict[str, Any]] = []
        if self.pgvector_adapter is not None:
            try:
                hits = self.pgvector_adapter.search(
                    session,
                    query=query,
                    knowledge_type_code=None,
                    top_k=_UNKNOWN_FALLBACK_TOP_K,
                    similarity_threshold=_UNKNOWN_FALLBACK_SIMILARITY,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "router_v2: unknown fallback pgvector search failed: %s",
                    exc,
                )

        synthetic_result = DispatchResult(
            intent="unknown",
            tool_results=(ToolResult(
                tool_call_id="__unknown_fallback__",
                name="internal.search_chunks_by_semantic",
                arguments={
                    "query": query,
                    "kb": None,
                    "top_k": _UNKNOWN_FALLBACK_TOP_K,
                    "similarity_threshold": _UNKNOWN_FALLBACK_SIMILARITY,
                },
                ok=True,
                result={"hits": hits, "fallback_note": trigger},
            ),),
            chart_registry=chart_registry,
        )

        composer = MDComposerV2(llm_client=self.llm_client)
        compose_result = composer.compose(
            session, query=query, dispatch_result=synthetic_result,
        )

        summary_fields: RetrievalV2SummaryFields = {
            "route": route,
            "caller_type": caller_type,
            "intent": "unknown",
            "intent_confidence": intent_result.confidence,
            "invoked_tools": [],
            "missing_optional_params": param_result.missing_required,
            "dispatch_fallback": (
                trigger  # type: ignore[typeddict-item]
                if trigger in {"no_tool_call", "param_validation_failed"}
                else None
            ),
            "generated_ratio": compose_result.generated_ratio,
            "template_id": None,
            "chart_hallucination_ids": list(
                compose_result.chart_hallucination_ids
            ),
            "chart_unused_ids": list(compose_result.chart_unused_ids),
            "matched_queries": None,
            "expand_queries_status": None,
            "query_route": "v2",
        }
        summary = build_retrieval_v2_summary(fields=summary_fields)

        return RouterResult(
            markdown=compose_result.markdown,
            raw_markdown=compose_result.raw_markdown,
            audit_summary=summary,
            intent="unknown",
            intent_confidence=intent_result.confidence,
            invoked_tools=[],
            fallback_reason="unknown_fallback",
            warnings=(trigger,),
        )

    def _scenario_5_placeholder(
        self,
        *,
        query: str,
        intent_result: IntentV2Result,
        param_result: ParamExtractionResult,
        route: RouteType,
        caller_type: CallerType,
    ) -> RouterResult:
        """P0 stub — Agentic RAG template executor lands after B3a."""
        markdown = (
            "> ⚠️ 以下为模型推断内容，未匹配到平台资产\n"
            "> 人才培养方案（scenario_5）模板执行器尚在 P0 批次 B3b 内交付，"
            "本次仅返回意图识别结果。\n"
        )
        summary_fields: RetrievalV2SummaryFields = {
            "route": route,
            "caller_type": caller_type,
            "intent": "scenario_5",
            "intent_confidence": intent_result.confidence,
            "invoked_tools": [],
            "missing_optional_params": param_result.missing_required,
            "dispatch_fallback": None,
            "generated_ratio": 1.0,
            "template_id": "talent_cultivation_plan",
            "chart_hallucination_ids": [],
            "chart_unused_ids": [],
            "matched_queries": None,
            "expand_queries_status": None,
            "query_route": "v2",
        }
        return RouterResult(
            markdown=markdown,
            raw_markdown=markdown,
            audit_summary=build_retrieval_v2_summary(fields=summary_fields),
            intent="scenario_5",
            intent_confidence=intent_result.confidence,
            invoked_tools=[],
            fallback_reason="scenario_5_template_not_implemented",
        )

    # ------------------------------------------------------------------ #
    # Happy-path summary
    # ------------------------------------------------------------------ #

    def _build_summary(
        self,
        *,
        route: RouteType,
        caller_type: CallerType,
        intent_result: IntentV2Result,
        param_result: ParamExtractionResult,
        dispatch_result: DispatchResult,
        compose_result: ComposeResult,
    ) -> dict[str, Any]:
        intent_typed: IntentType = intent_result.intent  # type: ignore[assignment]
        summary_fields: RetrievalV2SummaryFields = {
            "route": route,
            "caller_type": caller_type,
            "intent": intent_typed,
            "intent_confidence": intent_result.confidence,
            "invoked_tools": dispatch_result.invoked_tool_names,
            "missing_optional_params": param_result.missing_required,
            "dispatch_fallback": None,
            "generated_ratio": compose_result.generated_ratio,
            "template_id": None,
            "chart_hallucination_ids": list(
                compose_result.chart_hallucination_ids
            ),
            "chart_unused_ids": list(compose_result.chart_unused_ids),
            "matched_queries": None,
            "expand_queries_status": None,
            "query_route": "v2",
        }
        return build_retrieval_v2_summary(fields=summary_fields)


__all__ = [
    "QueryRouterV2",
    "RouterResult",
    "RouterStreamEvent",
    "RouterStreamEventType",
]
