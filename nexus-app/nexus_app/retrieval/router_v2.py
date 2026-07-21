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
import time
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
from nexus_app.retrieval.semantic_context import (
    assemble_semantic_context,
    resolve_semantic_scope,
    weak_evidence_chunk_ids,
)
from nexus_app.retrieval.subject_routing import (
    apply_subject_route_guard,
    resolve_query_subject,
)
from nexus_app.retrieval.tools_registry import (
    ToolRegistry,
    get_default_tool_registry,
)
from nexus_app.retrieval.web_search import AIWebSearchClient, WebSearchOutcome

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


RouterStreamEventType = Literal[
    "meta", "step", "chunk", "final", "done", "error",
]

StepId = Literal[
    "intent_classify",
    "param_extract",
    "dispatch",
    "compose",
    "unknown_fallback",
    "scenario_5_placeholder",
]

StepStatus = Literal["running", "completed", "failed"]


@dataclass(frozen=True)
class StepPayload:
    """One layer of the Agentic pipeline, captured for the UI timeline.

    Emitted twice per step — once with ``status="running"`` (input
    snapshot only) and once with ``status="completed"`` OR
    ``"failed"`` (output snapshot appended, latency filled).
    Consumers dedupe by ``id`` (last-write wins).  ``label`` is a
    Chinese-friendly display name so the frontend doesn't have to
    maintain its own translation map.
    """

    id: StepId
    status: StepStatus
    label: str
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    started_at_ms: int = 0
    completed_at_ms: int = 0
    error: str | None = None


@dataclass(frozen=True)
class RouterStreamEvent:
    """One event on the ``QueryRouterV2.run_stream`` iterator.

    * ``meta`` — first event, always. Carries ``intent`` /
      ``intent_confidence`` / ``invoked_tools`` (empty when the
      fallback path fires) / registered ``chart_ids`` so the frontend
      can pre-allocate placeholders before any prose arrives.
    * ``step`` — pipeline stage transition. Payload is a
      ``StepPayload`` describing which layer (intent_classify /
      param_extract / dispatch / compose / fallback) started or
      completed, plus its input/output snapshots for the Agentic
      timeline. Emitted twice per stage (running + completed).
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
    step: StepPayload | None = None


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
    external_web_results: tuple[dict[str, Any], ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


_UNKNOWN_FALLBACK_TOP_K = 20
_UNKNOWN_FALLBACK_SIMILARITY = 0.3


# Cap on how much of a tool result payload we ship into the step
# event's ``output.tool_calls[].result_preview``. Large chunk lists
# would blow the SSE frame; the frontend can drill into the full
# payload via a subsequent audit query if it ever needs the tail.
_TOOL_RESULT_PREVIEW_CHARS = 2000


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def _step_running(
    step_id: StepId,
    label: str,
    *,
    input: dict[str, Any],
    started_at_ms: int,
) -> RouterStreamEvent:
    return RouterStreamEvent(
        type="step",
        step=StepPayload(
            id=step_id,
            status="running",
            label=label,
            input=input,
            started_at_ms=started_at_ms,
        ),
    )


def _step_completed(
    step_id: StepId,
    label: str,
    *,
    input: dict[str, Any],
    output: dict[str, Any],
    started_at_ms: int,
    error: str | None = None,
) -> RouterStreamEvent:
    return RouterStreamEvent(
        type="step",
        step=StepPayload(
            id=step_id,
            status="failed" if error else "completed",
            label=label,
            input=input,
            output=output,
            started_at_ms=started_at_ms,
            completed_at_ms=_now_ms(),
            error=error,
        ),
    )


def _truncate_preview(value: Any) -> Any:
    """JSON-safe truncated preview of a tool_result payload for the
    step event. Non-mutating: takes the raw dict/list and returns a
    shallow-copied structure with long strings capped."""
    import json as _json
    try:
        rendered = _json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"__preview_error__": "non-serialisable payload"}
    if len(rendered) <= _TOOL_RESULT_PREVIEW_CHARS:
        return value
    return {
        "__truncated__": True,
        "preview": rendered[:_TOOL_RESULT_PREVIEW_CHARS],
        "original_size_chars": len(rendered),
    }


@dataclass
class QueryRouterV2:
    """Top-level orchestrator for query-router-v2.

    Constructor deps:
    * ``llm_client`` — shared client for intent / param / dispatcher / composer.
    * ``executor_registry`` — real ToolExecutor callables.
    * ``pgvector_adapter`` — used for the §六 unknown-fallback path.
    * ``tool_registry`` — optional override for the tool registry.
    * ``model_alias`` — LiteLLM alias for dispatcher function-calling
      turns.  When None we resolve from
      ``settings.default_governance_model`` on first use so
      deployments don't have to thread the alias through every caller.

    Threading the same ``llm_client`` through every layer keeps the
    LiteLLM alias + retry behaviour consistent across the request.
    """

    llm_client: LiteLLMClientProtocol
    executor_registry: ToolExecutorRegistry
    pgvector_adapter: PgvectorSearchAdapter | None = None
    tool_registry: ToolRegistry | None = None
    web_search_client: AIWebSearchClient | None = None
    model_alias: str | None = None

    def _effective_model_alias(self) -> str:
        """Resolve alias lazily from settings when unset.

        Kept as a method so tests can subclass / patch without touching
        the dataclass default. Missing config raises at first request
        (rather than at import) so tests that stub the LLM don't need
        settings to be loaded.
        """
        if self.model_alias:
            return self.model_alias
        from nexus_app.config import get_settings
        alias = get_settings().default_governance_model
        if not alias:
            raise RuntimeError(
                "QueryRouterV2.model_alias is unset and "
                "settings.default_governance_model is not configured."
            )
        return alias

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
        intent_result = apply_subject_route_guard(
            intent_result, resolve_query_subject(session, query), query,
        )

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
            model_alias=self._effective_model_alias(),
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
            if _is_web_search_eligible_intent(intent_result.intent):
                return self._semantic_tool_fallback_path(
                    session,
                    query=query,
                    intent_result=intent_result,
                    param_result=param_result,
                    route=route,
                    caller_type=caller_type,
                    trigger=dispatch_result.fallback_reason,
                    dispatch_result=dispatch_result,
                )
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
                preserve_intent_for_web_search=_is_web_search_eligible_intent(
                    intent_result.intent,
                ),
            )

        # ------------------------------------------------------------
        # Layer 3: composer
        # ------------------------------------------------------------
        web_search_outcome = None
        local_retrieval_failed = _has_local_retrieval_failure(dispatch_result)
        if local_retrieval_failed:
            compose_result = _local_retrieval_failure_compose_result(
                intent_result.intent,
            )
        else:
            web_search_outcome = self._maybe_web_search(
                query=query,
                intent=intent_result.intent,
                dispatch_result=dispatch_result,
            )
            if _requires_no_evidence_result(intent_result.intent, dispatch_result):
                compose_result = _no_evidence_compose_result(
                    intent_result.intent, web_search_outcome,
                )
            else:
                compose_result = MDComposerV2(llm_client=self.llm_client).compose(
                    session, query=query, dispatch_result=dispatch_result,
                )
        summary = self._build_summary(
            route=route,
            caller_type=caller_type,
            intent_result=intent_result,
            param_result=param_result,
            dispatch_result=dispatch_result,
            compose_result=compose_result,
            web_search_outcome=web_search_outcome,
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
                           + list(compose_result.warnings)
                           + ([web_search_outcome.warning]
                              if web_search_outcome and web_search_outcome.warning else [])),
            external_web_results=tuple(
                item.to_api_dict() for item in web_search_outcome.results
            ) if web_search_outcome else (),
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
        2. ``step`` events pair-wise (running → completed) per
           pipeline stage (intent_classify / param_extract / dispatch
           / compose / fallback), each carrying an input snapshot on
           ``running`` and an output snapshot on ``completed``.
        3. Zero or more ``chunk`` events during Composer streaming
           (interleaved with the ``compose`` step's running / completed
           pair — the compose step wraps the entire chunk sequence).
        4. Exactly one ``final`` event (or ``fallback`` from Composer
           translated into a final event with fallback_reason set).
        5. Exactly one ``done`` event.

        Unknown-intent / dispatcher-fallback / scenario_5 paths bypass
        Composer streaming entirely — they emit ``meta`` + a shortened
        step list (intent_classify → unknown_fallback OR
        intent_classify → param_extract → scenario_5_placeholder) →
        the pre-baked ``final`` payload → ``done`` (no ``chunk``
        events). This keeps the client's rendering path uniform:
        whenever a ``final`` event arrives, the accumulated chunk text
        should be discarded in favour of ``result.markdown``.
        """
        registry = self.tool_registry or get_default_tool_registry()

        # ------------------------------------------------------------
        # Step 1 — Layer 1a: intent classification
        # ------------------------------------------------------------
        intent_started = _now_ms()
        yield _step_running(
            "intent_classify", "意图分类",
            input={"query": query, "threshold": 0.6},
            started_at_ms=intent_started,
        )
        intent_classifier = IntentClassifierV2(llm_client=self.llm_client)
        intent_result = intent_classifier.classify(session, query)
        intent_result = apply_subject_route_guard(
            intent_result, resolve_query_subject(session, query), query,
        )
        yield _step_completed(
            "intent_classify", "意图分类",
            input={"query": query, "threshold": 0.6},
            output={
                "intent": intent_result.intent,
                "confidence": intent_result.confidence,
                "low_confidence": intent_result.low_confidence,
                "fallback_reason": intent_result.fallback_reason,
                "warnings": list(intent_result.warnings),
            },
            started_at_ms=intent_started,
        )

        # ------------------------------------------------------------
        # Step 2 — Layer 1b: parameter extraction
        # ------------------------------------------------------------
        param_started = _now_ms()
        yield _step_running(
            "param_extract", "参数抽取",
            input={"query": query, "intent": intent_result.intent},
            started_at_ms=param_started,
        )
        param_extractor = ParameterExtractorV2(
            llm_client=self.llm_client, registry=registry,
        )
        param_result = param_extractor.extract(
            session, query=query, intent=intent_result.intent,
        )
        yield _step_completed(
            "param_extract", "参数抽取",
            input={"query": query, "intent": intent_result.intent},
            output={
                "extracted_params": dict(param_result.extracted_params),
                "missing_required": list(param_result.missing_required),
                "fallback_reason": param_result.fallback_reason,
            },
            started_at_ms=param_started,
        )

        # ------------------------------------------------------------
        # Short-circuit unknown / low-confidence — no chunk stream.
        # Emit a single "unknown_fallback" step wrapping the pgvector
        # top-K search + composer pre-baked answer.
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
            fallback_started = _now_ms()
            yield _step_running(
                "unknown_fallback", "兜底检索",
                input={
                    "query": query,
                    "trigger": trigger,
                    "top_k": _UNKNOWN_FALLBACK_TOP_K,
                    "similarity_threshold": _UNKNOWN_FALLBACK_SIMILARITY,
                },
                started_at_ms=fallback_started,
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
            yield _step_completed(
                "unknown_fallback", "兜底检索",
                input={"query": query, "trigger": trigger},
                output={
                    "markdown_length": len(result.markdown),
                    "warnings": list(result.warnings),
                    "fallback_reason": result.fallback_reason,
                },
                started_at_ms=fallback_started,
            )
            yield RouterStreamEvent(type="final", result=result)
            yield RouterStreamEvent(type="done")
            return

        # ------------------------------------------------------------
        # Step 3 — Layer 2: dispatcher (non-streaming; tool exec is parallel).
        # ------------------------------------------------------------
        dispatch_started = _now_ms()
        yield _step_running(
            "dispatch", "工具调度",
            input={
                "intent": intent_result.intent,
                "extracted_params": dict(param_result.extracted_params),
                "model_alias": self._effective_model_alias(),
            },
            started_at_ms=dispatch_started,
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
            model_alias=self._effective_model_alias(),
        )
        yield _step_completed(
            "dispatch", "工具调度",
            input={
                "intent": intent_result.intent,
                "extracted_params": dict(param_result.extracted_params),
            },
            output={
                "invoked_tools": dispatch_result.invoked_tool_names,
                "tool_calls": [
                    {
                        "tool_call_id": r.tool_call_id,
                        "name": r.name,
                        "arguments": r.arguments,
                        "ok": r.ok,
                        "error": r.error,
                        "chart_ids": list(r.chart_ids),
                        "result_preview": _truncate_preview(r.result),
                    }
                    for r in dispatch_result.tool_results
                ],
                "fallback_reason": dispatch_result.fallback_reason,
                "warnings": list(dispatch_result.warnings),
            },
            started_at_ms=dispatch_started,
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
            s5_started = _now_ms()
            yield _step_running(
                "scenario_5_placeholder", "培养方案模板（P0 占位）",
                input={"template_id": "talent_cultivation_plan"},
                started_at_ms=s5_started,
            )
            result = self._scenario_5_placeholder(
                query=query,
                intent_result=intent_result,
                param_result=param_result,
                route=route,
                caller_type=caller_type,
            )
            yield _step_completed(
                "scenario_5_placeholder", "培养方案模板（P0 占位）",
                input={"template_id": "talent_cultivation_plan"},
                output={
                    "markdown_length": len(result.markdown),
                    "fallback_reason": result.fallback_reason,
                },
                started_at_ms=s5_started,
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
            fallback_started = _now_ms()
            yield _step_running(
                "unknown_fallback", "兜底检索",
                input={
                    "query": query,
                    "trigger": dispatch_result.fallback_reason,
                    "top_k": _UNKNOWN_FALLBACK_TOP_K,
                    "similarity_threshold": _UNKNOWN_FALLBACK_SIMILARITY,
                },
                started_at_ms=fallback_started,
            )
            if _is_web_search_eligible_intent(intent_result.intent):
                result = self._semantic_tool_fallback_path(
                    session,
                    query=query,
                    intent_result=intent_result,
                    param_result=param_result,
                    route=route,
                    caller_type=caller_type,
                    trigger=dispatch_result.fallback_reason,
                    dispatch_result=dispatch_result,
                )
            else:
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
            yield _step_completed(
                "unknown_fallback", "兜底检索",
                input={
                    "query": query,
                    "trigger": dispatch_result.fallback_reason,
                },
                output={
                    "markdown_length": len(result.markdown),
                    "warnings": list(result.warnings),
                    "fallback_reason": result.fallback_reason,
                },
                started_at_ms=fallback_started,
            )
            yield RouterStreamEvent(type="final", result=result)
            yield RouterStreamEvent(type="done")
            return

        # ------------------------------------------------------------
        # Step 4 — Layer 3: Composer streams chunks; router aggregates
        # + emits a final event with the fully-swapped markdown. The
        # compose step wraps the entire chunk sequence.
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

        compose_started = _now_ms()
        yield _step_running(
            "compose", "Markdown 汇总",
            input={
                "intent": intent_result.intent,
                "tool_result_count": len(dispatch_result.tool_results),
                "chart_ids": sorted(
                    dispatch_result.chart_registry.registered_ids()
                ),
            },
            started_at_ms=compose_started,
        )
        compose_result: ComposeResult | None = None
        web_search_outcome = None
        local_retrieval_failed = _has_local_retrieval_failure(dispatch_result)
        if local_retrieval_failed:
            compose_result = _local_retrieval_failure_compose_result(
                intent_result.intent,
            )
            yield RouterStreamEvent(type="chunk", text=compose_result.raw_markdown)
        else:
            web_search_outcome = self._maybe_web_search(
                query=query,
                intent=intent_result.intent,
                dispatch_result=dispatch_result,
            )
            if _requires_no_evidence_result(intent_result.intent, dispatch_result):
                compose_result = _no_evidence_compose_result(
                    intent_result.intent, web_search_outcome,
                )
                yield RouterStreamEvent(type="chunk", text=compose_result.raw_markdown)
            else:
                composer = MDComposerV2(llm_client=self.llm_client)
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
            web_search_outcome=web_search_outcome,
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
                           + list(compose_result.warnings)
                           + ([web_search_outcome.warning]
                              if web_search_outcome and web_search_outcome.warning else [])),
            external_web_results=tuple(
                item.to_api_dict() for item in web_search_outcome.results
            ) if web_search_outcome else (),
        )
        yield _step_completed(
            "compose", "Markdown 汇总",
            input={
                "intent": intent_result.intent,
                "tool_result_count": len(dispatch_result.tool_results),
                "chart_ids": sorted(
                    dispatch_result.chart_registry.registered_ids()
                ),
            },
            output={
                "generated_ratio": compose_result.generated_ratio,
                "markdown_length": len(compose_result.markdown),
                "raw_markdown_length": len(compose_result.raw_markdown),
                "chart_hallucination_ids": list(
                    compose_result.chart_hallucination_ids
                ),
                "chart_unused_ids": list(compose_result.chart_unused_ids),
                "fallback_reason": compose_result.fallback_reason,
                "warnings": list(compose_result.warnings),
            },
            started_at_ms=compose_started,
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
        preserve_intent_for_web_search: bool = False,
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
        scope = resolve_semantic_scope(
            session,
            query=query,
            # Fallback has no reliable domain label. Resolve only within the
            # refs returned by its broad first pass, never across all textbook
            # outlines, so industry/report queries cannot be captured by an
            # unrelated textbook heading.
            allow_auto_scope=False,
        )
        scope_fallback = False
        if self.pgvector_adapter is not None:
            try:
                hits = self.pgvector_adapter.search(
                    session,
                    query=query,
                    knowledge_type_code=None,
                    top_k=_UNKNOWN_FALLBACK_TOP_K,
                    similarity_threshold=_UNKNOWN_FALLBACK_SIMILARITY,
                )
                candidate_ref_ids = {
                    str(hit.get("normalized_ref_id") or "")
                    for hit in hits
                    if hit.get("normalized_ref_id")
                }
                scope = resolve_semantic_scope(
                    session,
                    query=query,
                    allowed_normalized_ref_ids=candidate_ref_ids,
                )
                if scope.applied and scope.chunk_ids:
                    scoped_hits = self.pgvector_adapter.search(
                        session,
                        query=query,
                        knowledge_type_code=None,
                        top_k=_UNKNOWN_FALLBACK_TOP_K,
                        similarity_threshold=_UNKNOWN_FALLBACK_SIMILARITY,
                        chunk_ids=list(scope.chunk_ids),
                    )
                    if scoped_hits:
                        hits = scoped_hits
                    else:
                        scope_fallback = True
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "router_v2: unknown fallback pgvector search failed: %s",
                    exc,
                )

        fallback_intent = (
            intent_result.intent if preserve_intent_for_web_search else "unknown"
        )
        synthetic_result = DispatchResult(
            intent=fallback_intent,
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
                result={
                    "hits": hits,
                    "fallback_note": trigger,
                    "scope": scope.to_api_dict(
                        fallback_to_unscoped=scope_fallback,
                    ),
                    "answer_contexts": assemble_semantic_context(
                        session, query=query, hits=hits,
                    ),
                    "weak_evidence_chunk_ids": weak_evidence_chunk_ids(
                        session, hits,
                    ),
                },
            ),),
            chart_registry=chart_registry,
        )

        web_search_outcome = self._maybe_web_search(
            query=query,
            intent=fallback_intent,
            dispatch_result=synthetic_result,
        )
        if _requires_no_evidence_result(fallback_intent, synthetic_result):
            compose_result = _no_evidence_compose_result(
                fallback_intent, web_search_outcome,
            )
        else:
            compose_result = MDComposerV2(llm_client=self.llm_client).compose(
                session, query=query, dispatch_result=synthetic_result,
            )

        summary_fields: RetrievalV2SummaryFields = {
            "route": route,
            "caller_type": caller_type,
            "intent": fallback_intent,
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
            **_web_search_audit_fields(web_search_outcome),
        }
        summary = build_retrieval_v2_summary(fields=summary_fields)

        return RouterResult(
            markdown=compose_result.markdown,
            raw_markdown=compose_result.raw_markdown,
            audit_summary=summary,
            intent=fallback_intent,
            intent_confidence=intent_result.confidence,
            invoked_tools=[],
            fallback_reason="unknown_fallback",
            warnings=tuple([trigger] + ([web_search_outcome.warning]
                if web_search_outcome and web_search_outcome.warning else [])),
            external_web_results=tuple(
                item.to_api_dict() for item in web_search_outcome.results
            ) if web_search_outcome else (),
        )

    def _semantic_tool_fallback_path(
        self,
        session: Session,
        *,
        query: str,
        intent_result: IntentV2Result,
        param_result: ParamExtractionResult,
        route: RouteType,
        caller_type: CallerType,
        trigger: str,
        dispatch_result: DispatchResult,
    ) -> RouterResult:
        """Run the single semantic tool deterministically after dispatch failure.

        Scenario 1/4 are semantic-chunk retrieval scenarios. If the LLM
        dispatcher returns no tool call or fails, the router should still try
        the registered NEXUS semantic retrieval before public-web fallback.
        """
        tool_name = "internal.search_chunks_by_semantic"
        executor = self.executor_registry.get(tool_name)
        chart_registry = dispatch_result.chart_registry
        if executor is None:
            compose_result = _local_retrieval_failure_compose_result(
                intent_result.intent,
            )
            synthetic_result = DispatchResult(
                intent=intent_result.intent,
                tool_results=(ToolResult(
                    tool_call_id="__semantic_dispatch_fallback__",
                    name=tool_name,
                    arguments={},
                    ok=False,
                    error="no executor registered",
                ),),
                chart_registry=chart_registry,
                warnings=(
                    *dispatch_result.warnings,
                    trigger,
                    "semantic_tool_unavailable",
                ),
            )
            summary = self._build_summary(
                route=route,
                caller_type=caller_type,
                intent_result=intent_result,
                param_result=param_result,
                dispatch_result=synthetic_result,
                compose_result=compose_result,
                web_search_outcome=None,
                dispatch_fallback=trigger,
            )
            return RouterResult(
                markdown=compose_result.markdown,
                raw_markdown=compose_result.raw_markdown,
                audit_summary=summary,
                intent=intent_result.intent,
                intent_confidence=intent_result.confidence,
                invoked_tools=[],
                fallback_reason=compose_result.fallback_reason,
                warnings=synthetic_result.warnings,
            )

        arguments = _semantic_fallback_arguments(
            query=query,
            intent=intent_result.intent,
            extracted_params=param_result.extracted_params,
        )
        try:
            payload = executor(
                session=session,
                arguments=arguments,
                tool_call_id="__semantic_dispatch_fallback__",
                chart_registry=chart_registry,
            )
            tool_result = ToolResult(
                tool_call_id="__semantic_dispatch_fallback__",
                name=tool_name,
                arguments=arguments,
                ok=True,
                result=payload,
            )
            warnings = (
                *dispatch_result.warnings,
                trigger,
                "semantic_tool_fallback",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "router_v2: semantic dispatch fallback failed: %s",
                exc,
            )
            tool_result = ToolResult(
                tool_call_id="__semantic_dispatch_fallback__",
                name=tool_name,
                arguments=arguments,
                ok=False,
                error=type(exc).__name__,
            )
            warnings = (
                *dispatch_result.warnings,
                trigger,
                "semantic_tool_fallback_failed",
            )

        semantic_result = DispatchResult(
            intent=intent_result.intent,
            tool_results=(tool_result,),
            chart_registry=chart_registry,
            warnings=warnings,
        )
        web_search_outcome = None
        local_retrieval_failed = _has_local_retrieval_failure(semantic_result)
        if local_retrieval_failed:
            compose_result = _local_retrieval_failure_compose_result(
                intent_result.intent,
            )
        else:
            web_search_outcome = self._maybe_web_search(
                query=query,
                intent=intent_result.intent,
                dispatch_result=semantic_result,
            )
            if _requires_no_evidence_result(intent_result.intent, semantic_result):
                compose_result = _no_evidence_compose_result(
                    intent_result.intent, web_search_outcome,
                )
            else:
                compose_result = MDComposerV2(llm_client=self.llm_client).compose(
                    session, query=query, dispatch_result=semantic_result,
                )

        summary = self._build_summary(
            route=route,
            caller_type=caller_type,
            intent_result=intent_result,
            param_result=param_result,
            dispatch_result=semantic_result,
            compose_result=compose_result,
            web_search_outcome=web_search_outcome,
            dispatch_fallback=trigger,
        )
        return RouterResult(
            markdown=compose_result.markdown,
            raw_markdown=compose_result.raw_markdown,
            audit_summary=summary,
            intent=intent_result.intent,
            intent_confidence=intent_result.confidence,
            invoked_tools=semantic_result.invoked_tool_names,
            fallback_reason=compose_result.fallback_reason,
            warnings=tuple(list(semantic_result.warnings)
                           + list(compose_result.warnings)
                           + ([web_search_outcome.warning]
                              if web_search_outcome and web_search_outcome.warning else [])),
            external_web_results=tuple(
                item.to_api_dict() for item in web_search_outcome.results
            ) if web_search_outcome else (),
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
        web_search_outcome: WebSearchOutcome | None = None,
        dispatch_fallback: str | None = None,
    ) -> dict[str, Any]:
        intent_typed: IntentType = intent_result.intent  # type: ignore[assignment]
        summary_fields: RetrievalV2SummaryFields = {
            "route": route,
            "caller_type": caller_type,
            "intent": intent_typed,
            "intent_confidence": intent_result.confidence,
            "invoked_tools": dispatch_result.invoked_tool_names,
            "missing_optional_params": param_result.missing_required,
            "dispatch_fallback": dispatch_fallback,  # type: ignore[typeddict-item]
            "generated_ratio": compose_result.generated_ratio,
            "template_id": None,
            "chart_hallucination_ids": list(
                compose_result.chart_hallucination_ids
            ),
            "chart_unused_ids": list(compose_result.chart_unused_ids),
            "matched_queries": None,
            "expand_queries_status": None,
            "query_route": "v2",
            **_web_search_audit_fields(web_search_outcome),
        }
        return build_retrieval_v2_summary(fields=summary_fields)

    def _maybe_web_search(
        self,
        *,
        query: str,
        intent: str,
        dispatch_result: DispatchResult,
    ) -> WebSearchOutcome | None:
        """Use public-web search only for eligible no-local-evidence queries."""
        if intent not in {"scenario_1", "scenario_4"}:
            return None
        if _has_local_retrieval_failure(dispatch_result):
            return None
        if _has_usable_local_evidence(dispatch_result):
            return None
        if self.web_search_client is None:
            return WebSearchOutcome(
                warning="external_search_unavailable",
                error_type="not_configured",
            )
        return self.web_search_client.search(query)


def _has_usable_local_evidence(dispatch_result: DispatchResult) -> bool:
    """Return true only for actual local retrieval evidence, not an empty call."""
    for tool_result in dispatch_result.tool_results:
        if not tool_result.ok or not isinstance(tool_result.result, dict):
            continue
        payload = tool_result.result
        if isinstance(payload.get("hits"), list) and payload["hits"]:
            return True
        if isinstance(payload.get("answer_contexts"), list) and payload["answer_contexts"]:
            return True
        count = payload.get("count")
        if payload.get("found") is True or (
            isinstance(count, int) and count > 0
        ):
            return True
        if any(isinstance(payload.get(key), list) and payload[key]
               for key in ("records", "analyses", "items", "results")):
            return True
        units = payload.get("units")
        if isinstance(units, dict) and any(
            isinstance(unit, dict)
            and unit.get("status") in {"structured", "chunk_fallback"}
            for unit in units.values()
        ):
            return True
    return False


def _has_local_retrieval_failure(dispatch_result: DispatchResult) -> bool:
    """True means local NEXUS retrieval failed, not that assets are absent."""
    for tool_result in dispatch_result.tool_results:
        if tool_result.ok:
            continue
        if _is_semantic_retrieval_tool(tool_result.name):
            return True
        error = tool_result.error or ""
        if "EmbeddingClientError" in error or "embedding" in error.lower():
            return True
    return False


def _is_semantic_retrieval_tool(name: str) -> bool:
    return name == "internal.search_chunks_by_semantic"


def _is_web_search_eligible_intent(intent: str) -> bool:
    return intent in {"scenario_1", "scenario_4"}


def _semantic_fallback_arguments(
    *,
    query: str,
    intent: str,
    extracted_params: dict[str, Any],
) -> dict[str, Any]:
    fallback_query = extracted_params.get("query")
    if not isinstance(fallback_query, str) or not fallback_query.strip():
        fallback_query = query
    arguments: dict[str, Any] = {
        "query": fallback_query.strip(),
        "top_k": 10,
        "expand_queries": True,
    }
    if intent == "scenario_1":
        arguments["kb"] = "industry_research_kb"
    return arguments


def _requires_no_evidence_result(
    intent: str,
    dispatch_result: DispatchResult,
) -> bool:
    return intent in {"scenario_1", "scenario_2", "scenario_3", "scenario_4"} and not _has_usable_local_evidence(dispatch_result)


def _no_evidence_compose_result(
    intent: str,
    outcome: WebSearchOutcome | None,
) -> ComposeResult:
    """Return a bounded no-data response without invoking the Composer LLM."""
    if intent in {"scenario_1", "scenario_4"}:
        if outcome and outcome.results:
            markdown = (
                "> NEXUS 当前没有检索到可核验的已治理资料。\n\n"
                "已在下方返回公开网络实时结果；这些结果未纳入 NEXUS 治理与验证。"
            )
        elif outcome and outcome.warning:
            markdown = (
                "> NEXUS 当前没有检索到可核验的已治理资料。\n\n"
                "公开网络检索当前不可用或未返回结果。"
            )
        else:
            markdown = "> NEXUS 当前没有检索到可核验的已治理资料。"
    elif intent == "scenario_2":
        markdown = "> 未检索到匹配的岗位需求、职业能力或专业布点结构化数据。"
    else:
        markdown = "> 未检索到可核验的专业信息或专业图谱数据。"
    return ComposeResult(
        markdown=markdown,
        raw_markdown=markdown,
        generated_ratio=0.0,
    )


def _local_retrieval_failure_compose_result(intent: str) -> ComposeResult:
    if intent in {"scenario_1", "scenario_4"}:
        markdown = (
            "> NEXUS 本地语义检索链路当前不可用，未能完成平台资产检索。\n\n"
            "本次不会启用公开网络检索兜底；请稍后重试或检查 LiteLLM embedding 服务状态。"
        )
    else:
        markdown = "> NEXUS 本地检索链路当前不可用，未能完成平台资产检索。"
    return ComposeResult(
        markdown=markdown,
        raw_markdown=markdown,
        generated_ratio=0.0,
        fallback_reason="local_retrieval_unavailable",
    )


def _web_search_audit_fields(
    outcome: WebSearchOutcome | None,
) -> dict[str, Any]:
    if outcome is None:
        return {"online_search_requested": False}
    return {
        "online_search_requested": True,
        "web_search_provider": outcome.provider,
        "external_result_count": len(outcome.results),
        "external_result_domains": outcome.domains,
        "external_search_latency_ms": outcome.latency_ms,
        "external_search_error_type": outcome.error_type,
    }


__all__ = [
    "QueryRouterV2",
    "RouterResult",
    "RouterStreamEvent",
    "RouterStreamEventType",
    "StepId",
    "StepPayload",
    "StepStatus",
]
