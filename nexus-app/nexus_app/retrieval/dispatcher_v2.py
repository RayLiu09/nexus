"""B4 (§10 阶段 B) — Layer-2 dispatcher for query-router-v2.

Given a classified intent + Layer-1 extracted parameters, ask the LLM
(via ``call_with_tools``) which of the scenario's registered tools to
invoke, validate the arguments against each tool's JSON schema, then
execute the chosen tools in parallel and return their results plus the
staged chart registry for Layer 3.

Design notes (aligned to §4.2.2):

* When intent is ``unknown`` or the scenario carries no tools
  (``scenario_5``), the dispatcher short-circuits with a fallback
  reason — the caller (B6/B7 entrypoints) is responsible for routing
  to the §六 unknown-fallback path or the §五 template executor.
* When the LLM returns 0 tool_calls, we do **not** retry — per §1.11
  decision #4, that's an immediate fallback to the unknown path.
* When arguments fail JSON-schema validation, we allow **one** LLM
  retry with a corrective system note; a second failure fallbacks
  with reason ``param_validation_failed``.
* Tool execution runs in a ``ThreadPoolExecutor`` so blocking I/O
  (HTTP calls to nexus-api, DB reads) can parallelise. The registry
  of tool executors is supplied by the caller — B4 itself owns no
  wire-format knowledge of the internal tools.
* Chart data assembled by a tool executor is registered into the
  request-scoped ``ChartRegistry`` (`chart_adapter`) so Layer 3 can
  reference ``[[CHART:xxx]]`` placeholders that the backend replaces
  after Composer finishes streaming (§7.3).
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
    ToolCall,
    ToolCallingResult,
)
from nexus_app.retrieval.chart_adapter import ChartRegistry
from nexus_app.retrieval.tools_registry import (
    ToolRegistry,
    ToolSpec,
    get_default_tool_registry,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolInvocation:
    """One tool_call as chosen by the LLM (after JSON parse + validation).

    ``validation_error`` is populated when the LLM's arguments failed
    the tool's JSON schema check on the FINAL attempt. In that case the
    invocation is not executed but is kept in the record so audit +
    fallback debugging surfaces the failure.
    """

    tool_call_id: str
    name: str
    arguments: dict[str, Any]
    validation_error: str | None = None


@dataclass(frozen=True)
class ToolResult:
    """Outcome of one executed tool invocation.

    ``result`` is the raw dict returned by the tool executor (whose
    shape is tool-specific — Composer knows how to read each of them
    via the compose_v2 prompt). ``chart_ids`` lists any chart ids the
    executor registered on the shared ``ChartRegistry`` for this call.
    """

    tool_call_id: str
    name: str
    arguments: dict[str, Any]
    ok: bool
    result: Any = None
    error: str | None = None
    chart_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DispatchResult:
    """What B4 hands to B5.

    ``fallback_reason`` — non-null when the dispatcher couldn't produce
    real tool results. Values:
    * ``unknown_intent`` — caller routes to §六 vector fallback.
    * ``scenario_5_template`` — caller runs the §五 template executor.
    * ``no_tool_call`` — LLM answered without tool use; §1.11 decision
      #4 says fallback to unknown.
    * ``param_validation_failed`` — arguments invalid after retry.
    * ``llm_call_failed`` — network / rate limit / server error.
    * ``no_tools_registered`` — every chosen tool lacks an executor.
    """

    intent: str
    tool_invocations: tuple[ToolInvocation, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    chart_registry: ChartRegistry = field(default_factory=ChartRegistry)
    fallback_reason: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def invoked_tool_names(self) -> list[str]:
        """List of tool names that ran successfully — feeds the audit
        ``invoked_tools`` field verbatim."""
        return [r.name for r in self.tool_results if r.ok]


# ---------------------------------------------------------------------------
# Executor protocol + registry
# ---------------------------------------------------------------------------


class ToolExecutor(Protocol):
    """Callable that runs one tool.

    Executors receive:
    * ``session`` — the SQLAlchemy session for the request (executors
      may open sub-sessions internally if they need thread safety).
    * ``arguments`` — the already-validated arg dict from the LLM.
    * ``tool_call_id`` — passed through so executors that emit charts
      can use it to build the deterministic chart_id.
    * ``chart_registry`` — the request-scoped registry; executors that
      return graph payloads register the chart JSON here and include
      the returned chart_id in their response dict (via a ``chart_id``
      or ``chart_ids`` field) so Composer can reference it in the
      ``[[CHART:xxx]]`` placeholders.

    Executors return an arbitrary JSON-serialisable dict — the shape
    is documented per-tool in the tool registry description; Composer
    reads it as free-form context.
    """

    def __call__(
        self,
        *,
        session: Session,
        arguments: dict[str, Any],
        tool_call_id: str,
        chart_registry: ChartRegistry,
    ) -> dict[str, Any]: ...


@dataclass
class ToolExecutorRegistry:
    """Name → executor lookup.

    Kept as a bare dict wrapper so the caller (B6/B7 wiring) can
    register real executors at startup and tests can substitute lambdas.
    """

    executors: dict[str, ToolExecutor] = field(default_factory=dict)

    def register(self, name: str, executor: ToolExecutor) -> None:
        self.executors[name] = executor

    def get(self, name: str) -> ToolExecutor | None:
        return self.executors.get(name)


# ---------------------------------------------------------------------------
# JSON-schema validation (lightweight — enough for the registry contract)
# ---------------------------------------------------------------------------


def _validate_arguments(
    schema: dict[str, Any], arguments: dict[str, Any],
) -> str | None:
    """Return None on success, error string on failure.

    Covers the schema features the registry actually uses:
    * ``required`` — every listed field must be present and non-null.
    * ``anyOf`` — at least one alternative's required set must satisfy.
    * ``properties[*].const`` — value equality.
    * ``properties[*].enum`` — value membership.
    * ``properties[*].type`` — coarse Python type check.
    * ``properties[*].pattern`` — regex full-match.

    Unknown keys in ``arguments`` are ignored (not a hard error) so
    tolerant of LLM adding a legal-looking extra field; the executor
    itself will drop unrecognised args.
    """
    properties = schema.get("properties", {})

    required = schema.get("required", []) or []
    for name in required:
        if name not in arguments or arguments[name] is None:
            return f"missing required argument {name!r}"

    any_of = schema.get("anyOf")
    if any_of:
        satisfied = False
        alt_errors: list[str] = []
        for alt in any_of:
            alt_required = alt.get("required", []) or []
            missing = [n for n in alt_required
                       if n not in arguments or arguments[n] is None]
            if not missing:
                satisfied = True
                break
            alt_errors.append(
                f"missing {sorted(missing)!r}"
            )
        if not satisfied:
            return (
                "anyOf constraint unsatisfied: "
                + " OR ".join(alt_errors)
            )

    for name, value in arguments.items():
        prop = properties.get(name)
        if prop is None:
            continue  # tolerate hallucinated fields — executor drops them
        if value is None:
            continue  # optional field explicitly nulled out

        const = prop.get("const")
        if const is not None and value != const:
            return (
                f"argument {name!r} must equal const {const!r}, got {value!r}"
            )

        enum = prop.get("enum")
        if enum is not None and value not in enum:
            return (
                f"argument {name!r} must be one of {enum!r}, got {value!r}"
            )

        expected_type = prop.get("type")
        if expected_type and not _type_matches(expected_type, value):
            return (
                f"argument {name!r} expected type {expected_type!r}, "
                f"got {type(value).__name__}"
            )

        pattern = prop.get("pattern")
        if pattern and isinstance(value, str):
            if re.fullmatch(pattern, value) is None:
                return (
                    f"argument {name!r} does not match pattern {pattern!r}"
                )

    return None


_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


def _type_matches(expected_type: str | list[str], value: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_type_matches(t, value) for t in expected_type)
    # bool is a subclass of int — reject "integer" for booleans to match
    # OpenAPI/JSON Schema semantics where types are disjoint.
    if expected_type == "integer" and isinstance(value, bool):
        return False
    if expected_type == "number" and isinstance(value, bool):
        return False
    types = _TYPE_MAP.get(expected_type)
    if types is None:
        return True  # unknown type keyword — don't fail on it
    return isinstance(value, types)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


_DEFAULT_MAX_WORKERS: int = 4
_RETRY_HINT = (
    "Your previous tool_calls failed argument validation. Fix the "
    "specific issue noted below and re-emit tool_calls. Do not answer "
    "in free text."
)


@dataclass
class DispatcherV2:
    """Layer-2 dispatcher.

    Constructor deps:
    * ``llm_client`` — implements ``LiteLLMClientProtocol.call_with_tools``.
    * ``executor_registry`` — name → callable map for real tool execution.
    * ``registry`` — tool spec registry; falls back to the on-disk default.
    * ``max_workers`` — thread pool size for parallel tool execution.
    """

    llm_client: LiteLLMClientProtocol
    executor_registry: ToolExecutorRegistry
    registry: ToolRegistry | None = None
    max_workers: int = _DEFAULT_MAX_WORKERS

    def dispatch(
        self,
        session: Session,
        *,
        query: str,
        intent: str,
        extracted_params: dict[str, Any],
        model_alias: str,
        temperature: float = 0.0,
    ) -> DispatchResult:
        chart_registry = ChartRegistry()

        # Short-circuit paths --------------------------------------------------
        if intent == "unknown":
            return DispatchResult(
                intent=intent,
                fallback_reason="unknown_intent",
                chart_registry=chart_registry,
            )

        registry = self.registry or get_default_tool_registry()
        try:
            tools = registry.for_scenario(intent)
        except KeyError:
            return DispatchResult(
                intent=intent,
                fallback_reason="unknown_intent",
                chart_registry=chart_registry,
            )
        if not tools:
            # scenario_5 legitimately has zero tools — Agentic RAG runs
            # a template executor (see §五) instead of LLM tool choice.
            return DispatchResult(
                intent=intent,
                fallback_reason="scenario_5_template",
                chart_registry=chart_registry,
            )

        function_schemas = [t.to_function_schema() for t in tools]
        tool_by_name: dict[str, ToolSpec] = {t.name: t for t in tools}

        base_messages = self._build_messages(
            query=query,
            intent=intent,
            extracted_params=extracted_params,
            tools=tools,
        )

        try:
            first = self.llm_client.call_with_tools(
                model_alias,
                base_messages,
                tools=function_schemas,
                tool_choice="auto",
                temperature=temperature,
            )
        except LiteLLMCallError as exc:
            logger.warning(
                "dispatcher_v2: LLM call_with_tools failed error_type=%s",
                exc.error_type,
            )
            return DispatchResult(
                intent=intent,
                fallback_reason="llm_call_failed",
                warnings=(str(exc.error_type),),
                chart_registry=chart_registry,
            )

        if not first.tool_calls:
            return DispatchResult(
                intent=intent,
                fallback_reason="no_tool_call",
                chart_registry=chart_registry,
            )

        invocations = self._parse_and_validate(first.tool_calls, tool_by_name)

        # Retry once on ANY validation failure (§4.2.2 step 5).
        if any(inv.validation_error for inv in invocations):
            retry_messages = base_messages + [
                {"role": "user", "content": _RETRY_HINT + "\n\n"
                    + _describe_errors(invocations)},
            ]
            try:
                retry = self.llm_client.call_with_tools(
                    model_alias,
                    retry_messages,
                    tools=function_schemas,
                    tool_choice="auto",
                    temperature=temperature,
                )
            except LiteLLMCallError as exc:
                return DispatchResult(
                    intent=intent,
                    tool_invocations=tuple(invocations),
                    fallback_reason="llm_call_failed",
                    warnings=(str(exc.error_type),),
                    chart_registry=chart_registry,
                )
            if not retry.tool_calls:
                return DispatchResult(
                    intent=intent,
                    tool_invocations=tuple(invocations),
                    fallback_reason="no_tool_call",
                    chart_registry=chart_registry,
                )
            invocations = self._parse_and_validate(
                retry.tool_calls, tool_by_name,
            )
            if any(inv.validation_error for inv in invocations):
                return DispatchResult(
                    intent=intent,
                    tool_invocations=tuple(invocations),
                    fallback_reason="param_validation_failed",
                    chart_registry=chart_registry,
                )

        # Execute valid invocations --------------------------------------------
        valid_invocations = [
            inv for inv in invocations if inv.validation_error is None
        ]
        if not valid_invocations:
            return DispatchResult(
                intent=intent,
                tool_invocations=tuple(invocations),
                fallback_reason="param_validation_failed",
                chart_registry=chart_registry,
            )

        # scenario_3 dual-path soft check — the design (§1.15) says both
        # tools SHOULD fire together; we surface a warning rather than
        # fallback because a single-tool answer is still usable and the
        # retry above already gave the LLM a chance to correct.
        warnings: list[str] = []
        if intent == "scenario_3":
            unique_names = {inv.name for inv in valid_invocations}
            expected = {t.name for t in tools}
            missing = expected - unique_names
            if missing:
                warnings.append(
                    f"scenario_3_dual_path_missing:{sorted(missing)}"
                )

        tool_results = self._execute_in_parallel(
            session,
            invocations=valid_invocations,
            chart_registry=chart_registry,
        )

        if not any(r.ok for r in tool_results):
            # Everything failed to execute — treat as no useful tool
            # result and let the caller fall back to unknown.
            return DispatchResult(
                intent=intent,
                tool_invocations=tuple(invocations),
                tool_results=tuple(tool_results),
                fallback_reason="no_tools_registered"
                    if all("no executor" in (r.error or "")
                           for r in tool_results if not r.ok)
                    else "tool_execution_failed",
                warnings=tuple(warnings),
                chart_registry=chart_registry,
            )

        return DispatchResult(
            intent=intent,
            tool_invocations=tuple(invocations),
            tool_results=tuple(tool_results),
            chart_registry=chart_registry,
            warnings=tuple(warnings),
        )

    # ---------------------------------------------------------------- #
    # Helpers
    # ---------------------------------------------------------------- #

    def _build_messages(
        self,
        *,
        query: str,
        intent: str,
        extracted_params: dict[str, Any],
        tools: list[ToolSpec],
    ) -> list[dict[str, str]]:
        """The dispatcher system prompt is intentionally short — the
        tool schemas passed as ``tools=`` carry the real behavioural
        contract. We only tell the model:

        * what the user asked (the query),
        * the pre-extracted params (Layer 1 hints — the model may use
          them verbatim or adjust based on the tool's schema),
        * which scenario we're in (so scenario_3 knows to fire both
          tools, per §1.15).
        """
        scenario_note = ""
        if intent == "scenario_3":
            scenario_note = (
                "\n\n**Scenario 3 双路约束**：请同时调用 "
                + ", ".join(f"`{t.name}`" for t in tools)
                + " 两个 tool；单独调用一个会被视为不完整。"
            )

        content = (
            "你是 NEXUS 数据检索的 Layer-2 dispatcher。根据用户 query 和已抽取"
            "参数，从工具列表中选择合适的 tool 并填入 arguments。\n\n"
            f"**用户查询**：{query}\n\n"
            f"**命中意图**：`{intent}`\n\n"
            "**Layer 1 已抽取参数**（可作为 arguments 的默认值参考）："
            f"\n```json\n{json.dumps(extracted_params, ensure_ascii=False, indent=2)}\n```\n\n"
            "**要求**：\n"
            "1. 严格按照每个 tool 的 parameters schema 提供 arguments\n"
            "2. 必填字段必须填齐；无法确定的值宁可放弃调用也不要臆造\n"
            "3. 若一个 query 需要多个 tool 才能完整回答，请一次发出多个 tool_calls"
            + scenario_note
        )
        return [{"role": "user", "content": content}]

    def _parse_and_validate(
        self,
        tool_calls: list[ToolCall],
        tool_by_name: dict[str, ToolSpec],
    ) -> list[ToolInvocation]:
        """Turn ``ToolCall`` payloads into typed ``ToolInvocation`` entries.

        Errors surface as ``validation_error`` on the invocation so we
        can retry / audit them; we never raise from this method.
        """
        out: list[ToolInvocation] = []
        for tc in tool_calls:
            tool = tool_by_name.get(tc.name)
            if tool is None:
                out.append(ToolInvocation(
                    tool_call_id=tc.id,
                    name=tc.name,
                    arguments={},
                    validation_error=(
                        f"unknown tool {tc.name!r} for this scenario"
                    ),
                ))
                continue
            try:
                args = json.loads(tc.arguments) if tc.arguments else {}
            except (TypeError, ValueError) as exc:
                out.append(ToolInvocation(
                    tool_call_id=tc.id,
                    name=tc.name,
                    arguments={},
                    validation_error=f"arguments not valid JSON: {exc}",
                ))
                continue
            if not isinstance(args, dict):
                out.append(ToolInvocation(
                    tool_call_id=tc.id,
                    name=tc.name,
                    arguments={},
                    validation_error="arguments JSON must be an object",
                ))
                continue
            err = _validate_arguments(tool.parameters, args)
            out.append(ToolInvocation(
                tool_call_id=tc.id,
                name=tc.name,
                arguments=args,
                validation_error=err,
            ))
        return out

    def _execute_in_parallel(
        self,
        session: Session,
        *,
        invocations: list[ToolInvocation],
        chart_registry: ChartRegistry,
    ) -> list[ToolResult]:
        results: list[ToolResult] = [None] * len(invocations)  # type: ignore[list-item]

        def _one(idx: int, inv: ToolInvocation) -> tuple[int, ToolResult]:
            executor = self.executor_registry.get(inv.name)
            if executor is None:
                return idx, ToolResult(
                    tool_call_id=inv.tool_call_id,
                    name=inv.name,
                    arguments=inv.arguments,
                    ok=False,
                    error=f"no executor registered for tool {inv.name!r}",
                )
            before_ids = chart_registry.registered_ids()
            try:
                payload = executor(
                    session=session,
                    arguments=inv.arguments,
                    tool_call_id=inv.tool_call_id,
                    chart_registry=chart_registry,
                )
            except Exception as exc:  # noqa: BLE001 — surface any executor error
                logger.warning(
                    "dispatcher_v2: tool %s failed: %s",
                    inv.name, exc,
                )
                return idx, ToolResult(
                    tool_call_id=inv.tool_call_id,
                    name=inv.name,
                    arguments=inv.arguments,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            new_ids = tuple(sorted(chart_registry.registered_ids() - before_ids))
            return idx, ToolResult(
                tool_call_id=inv.tool_call_id,
                name=inv.name,
                arguments=inv.arguments,
                ok=True,
                result=payload,
                chart_ids=new_ids,
            )

        # Single-tool case: skip the thread pool to keep tests simple
        # and avoid the pool creation cost for the common path.
        if len(invocations) == 1:
            _, result = _one(0, invocations[0])
            return [result]

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [
                pool.submit(_one, idx, inv)
                for idx, inv in enumerate(invocations)
            ]
            for fut in as_completed(futures):
                idx, result = fut.result()
                results[idx] = result

        return results


def _describe_errors(invocations: list[ToolInvocation]) -> str:
    lines = []
    for inv in invocations:
        if inv.validation_error is None:
            continue
        lines.append(f"- tool `{inv.name}`: {inv.validation_error}")
    return "\n".join(lines)


__all__ = [
    "DispatcherV2",
    "DispatchResult",
    "ToolExecutor",
    "ToolExecutorRegistry",
    "ToolInvocation",
    "ToolResult",
]
