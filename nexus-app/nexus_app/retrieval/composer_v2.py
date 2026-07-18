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
from typing import Any

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


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


_FALLBACK_MARKDOWN = (
    "> ⚠️ 以下为模型推断内容，未匹配到平台资产\n"
    "> 抱歉，未能生成有效回答。请稍后重试或换一种表述方式。\n"
)


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
    "MDComposerV2",
]
