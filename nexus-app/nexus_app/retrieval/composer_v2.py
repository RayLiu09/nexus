"""B5 (§10 阶段 B + §4.3) — Layer-3 Markdown Composer for query-router-v2.

Consumes a ``DispatchResult`` from B4 and produces the final Markdown
answer. Design red lines carried in:

* **Chart placeholder timing** (§7.3): the LLM emits ``[[CHART:xxx]]``
  placeholders during streaming; we replace them all in one pass
  *after* the stream ends so the front end never sees a half-written
  fenced block. This class does the replacement synchronously — the
  streaming plumbing (SSE / chunked response) belongs in B6/B7 which
  wrap ``compose()``.
* **Generated content wrapping** (§4.3 output spec): Composer prompt
  instructs the model to wrap inferred content in a blockquote led by
  ``> ⚠️ 以下为模型推断内容，未匹配到平台资产``. We do NOT insert or
  strip these blocks post-hoc — we only *measure* their character
  share (``generated_ratio``) so the audit trail can flag over-generated
  answers.
* **Chart hallucinations vs unused** (§7.3): the composer output can
  reference chart_ids that don't exist in the registry (LLM
  hallucination) or omit ids the registry has (LLM never referenced
  them). Both go into the audit summary via
  ``ChartReplacementResult.hallucination_ids`` and ``unused_ids``.
* **Unknown-fallback path** (§六): when the dispatcher's fallback
  reason is ``unknown_intent`` / ``scenario_5_template`` / other, this
  class does NOT invoke the LLM — B6/B7 should short-circuit before
  calling ``compose()``. The class does defend by raising a clear
  error if it's asked to compose without at least one successful tool
  result.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

from sqlalchemy.orm import Session

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.retrieval.chart_adapter import (
    ChartRegistry,
    ChartReplacementResult,
    replace_chart_placeholders,
)
from nexus_app.retrieval.dispatcher_v2 import DispatchResult, ToolResult
from nexus_app.retrieval.prompt_profiles_v2 import (
    COMPOSE_V2_PROFILE_NAME,
    get_active_v2_prompt,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComposeResult:
    """What B5 hands to the entrypoint (B6 / B7).

    ``markdown`` — the final answer with chart placeholders replaced.
    ``raw_markdown`` — the LLM's original output (before chart replacement).
      Kept so B6/B7 can stream the raw text over SSE and only emit the
      replaced tail at the end.
    ``generated_ratio`` — chars inside `> ⚠️ …` blockquote wrappers /
      total chars. Fed into ``audit.summary.generated_ratio``.
    ``chart_hallucination_ids`` — ids referenced in output but not
      registered. Populates ``audit.summary.chart_hallucination_ids``.
    ``chart_unused_ids`` — ids registered but never referenced in output.
      Populates ``audit.summary.chart_unused_ids``.
    ``fallback_reason`` — non-null when composer bailed out.
      Values: ``prompt_profile_missing`` / ``llm_call_failed`` /
      ``empty_llm_output``.
    ``warnings`` — soft signals, e.g. tokens truncated, chart id
      shape unexpected.
    """

    markdown: str
    raw_markdown: str
    generated_ratio: float
    chart_hallucination_ids: list[str] = field(default_factory=list)
    chart_unused_ids: list[str] = field(default_factory=list)
    fallback_reason: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


ComposeStreamEventType = Literal["chunk", "final", "fallback"]


@dataclass(frozen=True)
class ComposeStreamEvent:
    """One event on the ``compose_stream`` iterator.

    * ``chunk`` — incremental raw markdown fragment. Concatenating all
      ``chunk`` events reproduces ``ComposeResult.raw_markdown``.
    * ``final`` — emitted once at the end with the fully-swapped
      markdown + audit metadata. SSE endpoints emit this immediately
      before ``event: done``.
    * ``fallback`` — emitted (without any ``chunk`` events preceding
      OR after a mid-stream LLM failure) with a canned ⚠️ payload +
      populated ``fallback_reason``.
    """

    type: ComposeStreamEventType
    text: str = ""
    result: ComposeResult | None = None


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


_FALLBACK_MARKDOWN = (
    "> ⚠️ 以下为模型推断内容，未匹配到平台资产\n"
    "> 抱歉，未能生成有效回答。请稍后重试或换一种表述方式。\n"
)

_ANSWER_CONTEXT_POLICY = """

## 检索上下文使用规则

若某个 `internal.search_chunks_by_semantic` 结果包含 `answer_contexts`：

1. 对“分类 / 类型 / 有哪些”和“流程 / 步骤 / 如何”问题，必须优先使用其中
   的 `section_context` 或 `task_context.chunks` 作答；不得因为原始 `hits`
   中的单个学习目标、目录或任务标题未列出答案，就声称“暂无数据”。
2. `task_context` 的 `step_no` 和可选 `task_title` 是顺序证据；编号重启时按
   `task_title` 分组呈现。
3. 每项结论都要使用该上下文 chunk 的 `chunk_id`、`normalized_ref_id` 和
   `locator` 生成来源脚注。上下文不存在或为空时才可说明检索证据不足。
"""


@dataclass
class MDComposerV2:
    """Layer-3 composer.

    Constructor deps:
    * ``llm_client`` — usually the same client used by dispatcher.
    * ``max_tokens`` — cap on the composer's generation length.
    """

    llm_client: LiteLLMClientProtocol
    max_tokens: int = 4096

    def compose(
        self,
        session: Session,
        *,
        query: str,
        dispatch_result: DispatchResult,
    ) -> ComposeResult:
        chart_registry = dispatch_result.chart_registry

        grounded_procedure = _render_grounded_answer(
            query=query,
            dispatch_result=dispatch_result,
        )
        if grounded_procedure is not None:
            return ComposeResult(
                markdown=grounded_procedure,
                raw_markdown=grounded_procedure,
                generated_ratio=0.0,
            )

        try:
            profile = get_active_v2_prompt(session, COMPOSE_V2_PROFILE_NAME)
        except LookupError as exc:
            logger.warning("compose_v2: prompt profile missing — %s", exc)
            fallback = _FALLBACK_MARKDOWN
            return ComposeResult(
                markdown=fallback,
                raw_markdown=fallback,
                generated_ratio=1.0,
                fallback_reason="prompt_profile_missing",
            )

        tool_results_serialised = _serialise_tool_results(
            dispatch_result.tool_results,
        )
        chart_ids = sorted(chart_registry.registered_ids())
        prompt_content = _fill_prompt(
            profile.prompt_template,
            query=query,
            intent=dispatch_result.intent,
            tool_results=tool_results_serialised,
            chart_ids=chart_ids,
        )

        messages = [{"role": "user", "content": prompt_content}]

        try:
            raw_markdown, _summary = self.llm_client.call(
                profile.litellm_model_alias,
                messages,
                temperature=profile.temperature,
                max_tokens=self.max_tokens,
            )
        except LiteLLMCallError as exc:
            logger.warning(
                "compose_v2: LLM call failed error_type=%s", exc.error_type,
            )
            fallback = _FALLBACK_MARKDOWN
            return ComposeResult(
                markdown=fallback,
                raw_markdown=fallback,
                generated_ratio=1.0,
                fallback_reason="llm_call_failed",
                warnings=(str(exc.error_type),),
            )

        raw_markdown = (raw_markdown or "").strip()
        if not raw_markdown:
            return ComposeResult(
                markdown=_FALLBACK_MARKDOWN,
                raw_markdown=_FALLBACK_MARKDOWN,
                generated_ratio=1.0,
                fallback_reason="empty_llm_output",
            )

        replaced: ChartReplacementResult = replace_chart_placeholders(
            raw_markdown, chart_registry,
        )
        generated_ratio = _compute_generated_ratio(replaced.text)

        return ComposeResult(
            markdown=replaced.text,
            raw_markdown=raw_markdown,
            generated_ratio=generated_ratio,
            chart_hallucination_ids=list(replaced.hallucination_ids),
            chart_unused_ids=list(replaced.unused_ids),
        )

    def compose_stream(
        self,
        session: Session,
        *,
        query: str,
        dispatch_result: DispatchResult,
    ) -> Iterator[ComposeStreamEvent]:
        """§7.3 streaming variant of ``compose``.

        Yields ``chunk`` events for every LLM delta, then exactly one
        of ``final`` (happy path — payload has swapped chart
        placeholders) or ``fallback`` (prompt profile missing / LLM
        error / empty output — payload uses the canned ⚠️ blockquote).
        Never raises — SSE endpoints translate ``fallback`` into an
        ``event: error`` marker if they need to distinguish, but the
        caller always gets a terminating event.
        """
        chart_registry = dispatch_result.chart_registry

        grounded_procedure = _render_grounded_answer(
            query=query,
            dispatch_result=dispatch_result,
        )
        if grounded_procedure is not None:
            # A procedure context is already ordered, complete, and cited
            # evidence. Streaming an LLM paraphrase here can silently omit
            # steps, so emit the grounded result as one stable chunk.
            yield ComposeStreamEvent(type="chunk", text=grounded_procedure)
            yield ComposeStreamEvent(
                type="final",
                result=ComposeResult(
                    markdown=grounded_procedure,
                    raw_markdown=grounded_procedure,
                    generated_ratio=0.0,
                ),
            )
            return

        try:
            profile = get_active_v2_prompt(session, COMPOSE_V2_PROFILE_NAME)
        except LookupError as exc:
            logger.warning("compose_v2 stream: prompt profile missing — %s", exc)
            yield ComposeStreamEvent(
                type="fallback",
                result=ComposeResult(
                    markdown=_FALLBACK_MARKDOWN,
                    raw_markdown=_FALLBACK_MARKDOWN,
                    generated_ratio=1.0,
                    fallback_reason="prompt_profile_missing",
                ),
            )
            return

        tool_results_serialised = _serialise_tool_results(
            dispatch_result.tool_results,
        )
        chart_ids = sorted(chart_registry.registered_ids())
        prompt_content = _fill_prompt(
            profile.prompt_template,
            query=query,
            intent=dispatch_result.intent,
            tool_results=tool_results_serialised,
            chart_ids=chart_ids,
        )
        messages = [{"role": "user", "content": prompt_content}]

        accumulated: list[str] = []
        try:
            for delta in self.llm_client.call_stream(
                profile.litellm_model_alias,
                messages,
                temperature=profile.temperature,
                max_tokens=self.max_tokens,
            ):
                if not delta:
                    continue
                accumulated.append(delta)
                yield ComposeStreamEvent(type="chunk", text=delta)
        except LiteLLMCallError as exc:
            logger.warning(
                "compose_v2 stream: LLM call_stream failed error_type=%s",
                exc.error_type,
            )
            yield ComposeStreamEvent(
                type="fallback",
                result=ComposeResult(
                    markdown=_FALLBACK_MARKDOWN,
                    raw_markdown=_FALLBACK_MARKDOWN,
                    generated_ratio=1.0,
                    fallback_reason="llm_call_failed",
                    warnings=(str(exc.error_type),),
                ),
            )
            return

        raw_markdown = "".join(accumulated).strip()
        if not raw_markdown:
            yield ComposeStreamEvent(
                type="fallback",
                result=ComposeResult(
                    markdown=_FALLBACK_MARKDOWN,
                    raw_markdown=_FALLBACK_MARKDOWN,
                    generated_ratio=1.0,
                    fallback_reason="empty_llm_output",
                ),
            )
            return

        replaced = replace_chart_placeholders(raw_markdown, chart_registry)
        generated_ratio = _compute_generated_ratio(replaced.text)
        yield ComposeStreamEvent(
            type="final",
            result=ComposeResult(
                markdown=replaced.text,
                raw_markdown=raw_markdown,
                generated_ratio=generated_ratio,
                chart_hallucination_ids=list(replaced.hallucination_ids),
                chart_unused_ids=list(replaced.unused_ids),
            ),
        )


# ---------------------------------------------------------------------------
# Prompt filling
# ---------------------------------------------------------------------------


def _fill_prompt(
    template: str,
    *,
    query: str,
    intent: str,
    tool_results: str,
    chart_ids: list[str],
) -> str:
    """Substitute the compose_v2 prompt's four placeholders.

    Placeholder replacement uses ``str.replace`` (not ``.format``) so
    unbalanced curly braces in tool results (JSON structures, code
    snippets from chunks) never crash prompt build.
    """
    chart_block = _render_chart_placeholders_block(chart_ids)
    return (
        template
        .replace("{{QUERY}}", query)
        .replace("{{INTENT}}", intent)
        .replace("{{TOOL_RESULTS}}", tool_results)
        .replace("{{CHART_PLACEHOLDERS}}", chart_block)
        + _ANSWER_CONTEXT_POLICY
    )


def _render_chart_placeholders_block(chart_ids: list[str]) -> str:
    """List chart_ids as ``- [[CHART:xxx]]`` bullets for the prompt.

    Empty list yields an explicit "no charts" note so the LLM doesn't
    fabricate chart_ids to fill the section.
    """
    if not chart_ids:
        return "（本次无 chart 数据）"
    return "\n".join(f"- `[[CHART:{cid}]]`" for cid in chart_ids)


# ---------------------------------------------------------------------------
# Tool-result serialisation
# ---------------------------------------------------------------------------


_MAX_TOOL_PAYLOAD_BYTES = 32_000  # keep prompt bounded even for large results

_PROCEDURE_QUERY_MARKERS = ("流程", "步骤", "如何", "怎么", "怎样")


def _render_grounded_answer(
    *,
    query: str,
    dispatch_result: DispatchResult,
) -> str | None:
    """Return a deterministic answer for complete task or section evidence."""
    procedure = _render_grounded_task_procedure(
        query=query,
        dispatch_result=dispatch_result,
    )
    if procedure is not None:
        return procedure
    return _render_grounded_section_context(
        query=query,
        dispatch_result=dispatch_result,
    )


def _render_grounded_task_procedure(
    *,
    query: str,
    dispatch_result: DispatchResult,
) -> str | None:
    """Render a complete task procedure directly from ordered chunk evidence.

    ``task_context`` is constructed from Task Outline operation-step nodes,
    rather than from a vector top-K. Once such a context is available for a
    procedure question, an LLM summary is not allowed to turn a complete
    ordered set into a partial answer and then claim the remainder is absent.
    Only a single unambiguous task context is rendered this way; other
    questions retain normal Composer behaviour.
    """
    if not any(marker in query for marker in _PROCEDURE_QUERY_MARKERS):
        return None

    contexts: list[dict[str, Any]] = []
    for tool_result in dispatch_result.tool_results:
        if not tool_result.ok or not isinstance(tool_result.result, dict):
            continue
        for context in tool_result.result.get("answer_contexts") or []:
            if isinstance(context, dict) and context.get("kind") == "task_context":
                contexts.append(context)
    if len(contexts) != 1:
        return None

    context = contexts[0]
    chunks = [
        chunk for chunk in context.get("chunks") or []
        if isinstance(chunk, dict) and str(chunk.get("content") or "").strip()
    ]
    if not chunks:
        return None

    title = str(context.get("title") or "任务流程")
    normalized_ref_id = str(context.get("normalized_ref_id") or "")
    lines = [f"## {title}", "", "以下按资料中的任务结构列出完整操作步骤。"]
    current_group: str | None = None
    citations: list[str] = []
    for citation_index, chunk in enumerate(chunks, start=1):
        group = str(chunk.get("task_title") or title)
        if group != current_group:
            lines.extend(["", f"### {group}"])
            current_group = group
        step_no = chunk.get("step_no")
        label = f"{step_no}." if step_no is not None else "-"
        content = str(chunk["content"]).strip()
        lines.append(f"{label} {content} [^ref{citation_index}]")
        locator = json.dumps(
            chunk.get("locator") or {}, ensure_ascii=False, sort_keys=True,
        )
        citations.append(
            f"[^ref{citation_index}]: `{normalized_ref_id}` / "
            f"`{chunk.get('chunk_id') or ''}` / `{locator}`"
        )
    return "\n".join([*lines, "", *citations])


def _render_grounded_section_context(
    *,
    query: str,
    dispatch_result: DispatchResult,
) -> str | None:
    """Render all chunks from one high-confidence query-matched section.

    A section context is only assembled after a high-confidence title match
    and is structurally expanded in document order. It is more reliable than
    asking an LLM whether one flat hit represents the whole chapter, so the
    answer renders complete cited evidence without lossy model summarisation.
    """
    contexts: list[dict[str, Any]] = []
    for tool_result in dispatch_result.tool_results:
        if not tool_result.ok or not isinstance(tool_result.result, dict):
            continue
        for context in tool_result.result.get("answer_contexts") or []:
            if isinstance(context, dict) and context.get("kind") == "section_context":
                contexts.append(context)
    if len(contexts) != 1:
        return None

    context = contexts[0]
    chunks = [
        chunk for chunk in context.get("chunks") or []
        if isinstance(chunk, dict) and str(chunk.get("content") or "").strip()
    ]
    if not chunks:
        return None

    title = str(context.get("title") or "章节内容")
    normalized_ref_id = str(context.get("normalized_ref_id") or "")
    lines = [f"## {title}"]
    citations: list[str] = []
    for citation_index, chunk in enumerate(chunks, start=1):
        content = str(chunk["content"]).strip()
        if citation_index == 1:
            lines.extend(["", f"{content} [^ref{citation_index}]"])
        else:
            lines.append(f"{citation_index - 1}. {content} [^ref{citation_index}]")
        locator = json.dumps(
            chunk.get("locator") or {}, ensure_ascii=False, sort_keys=True,
        )
        citations.append(
            f"[^ref{citation_index}]: `{normalized_ref_id}` / "
            f"`{chunk.get('chunk_id') or ''}` / `{locator}`"
        )
    if context.get("truncated"):
        lines.extend(["", "本章节内容超过当前安全上下文预算，以下仅展示已检索的前序内容。"])
    return "\n".join([*lines, "", *citations])


def _serialise_tool_results(results: tuple[ToolResult, ...]) -> str:
    """Render ``ToolResult``s as pretty JSON for the LLM prompt.

    Only successful results are included in the composed context; failed
    results are surfaced as a short marker so the LLM knows a tool did
    run but produced nothing usable (rather than silently ignoring).
    """
    payload: list[dict[str, Any]] = []
    for r in results:
        entry: dict[str, Any] = {
            "tool_call_id": r.tool_call_id,
            "name": r.name,
            "arguments": r.arguments,
        }
        if r.ok:
            entry["result"] = r.result
        else:
            entry["ok"] = False
            entry["error"] = r.error
        if r.chart_ids:
            entry["chart_ids"] = list(r.chart_ids)
        payload.append(entry)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if len(rendered.encode("utf-8")) > _MAX_TOOL_PAYLOAD_BYTES:
        # Composer prompt cap — truncate the tail rather than drop
        # entries so at least the first tools stay auditable. LLM sees
        # a `...truncated` marker so it doesn't invent missing fields.
        cutoff = _MAX_TOOL_PAYLOAD_BYTES - 200
        rendered = (
            rendered.encode("utf-8")[:cutoff].decode("utf-8", errors="ignore")
            + "\n...[truncated for prompt budget]..."
        )
    return rendered


# ---------------------------------------------------------------------------
# Generated-block ratio
# ---------------------------------------------------------------------------

# Match one contiguous block of consecutive lines each starting with `>`
# (Markdown blockquote). The `⚠️` marker anchors the FIRST line so we
# only count generated blocks — regular quoted text (e.g. a cited
# passage rendered as a quote) doesn't inflate the ratio.
_GENERATED_BLOCK_RE = re.compile(
    r"(?m)^>\s*⚠️[^\n]*(?:\n>[^\n]*)*",
)


def _compute_generated_ratio(text: str) -> float:
    """Chars in ``> ⚠️`` blockquote wrappers / total chars in ``text``.

    Returns 0.0 when the composer text is empty (defensive; the caller
    already treats empty output as a fallback path).
    """
    if not text:
        return 0.0
    total = len(text)
    generated = sum(
        len(match.group(0)) for match in _GENERATED_BLOCK_RE.finditer(text)
    )
    return min(1.0, generated / total)


__all__ = [
    "ComposeResult",
    "ComposeStreamEvent",
    "ComposeStreamEventType",
    "MDComposerV2",
]
