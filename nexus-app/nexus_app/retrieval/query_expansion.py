"""A5 (§10 阶段 A + §1.15 §4.2.6) — synonym / paraphrase query expansion.

v1 shipped no query-expansion primitive; §1.11 决策 #2 mandated a fresh
implementation. §1.11 决策 #3 explicitly ruled out rerank-based fusion
for P0 — this module produces the expansion list, then hands off to a
plain `chunk_id → max score` dedup after each expanded query is issued
against `PgvectorSearchAdapter.search`.

Two moving parts:

* `QueryExpansionProvider` — Protocol for generating N synonym queries
  given the original query. `LiteLLMQueryExpansionProvider` is the
  production implementation; tests / FakeLiteLLM builds inject a
  simpler stub.
* `merge_and_dedup_hits` — combines the raw-query hits + expansion
  hits into a single list, keeping the max score per chunk and
  recording every query that matched each chunk under
  `metadata["matched_queries"]`.

Failure mode (per §4.2.6): a provider that raises falls back to the
raw-query-only path with `metadata["expand_queries_status"] =
"false_due_to_error"`; the search never fails outright.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — declared here (not §1.15 duplicated) so callers reading this
# module see the defaults in one place.
# ---------------------------------------------------------------------------

DEFAULT_EXPANSION_COUNT_MIN = 3
DEFAULT_EXPANSION_COUNT_MAX = 5

# Prompt scenario key for `ai_prompt_profile` — B1 will populate the
# actual template in phase B. For phase A the Fake provider bypasses
# LiteLLM entirely.
PROMPT_PROFILE_SCENARIO = "retrieval.query_expansion_v2"


# ---------------------------------------------------------------------------
# Provider Protocol
# ---------------------------------------------------------------------------


class QueryExpansionProvider(Protocol):
    def generate(
        self,
        query: str,
        *,
        min_count: int = DEFAULT_EXPANSION_COUNT_MIN,
        max_count: int = DEFAULT_EXPANSION_COUNT_MAX,
    ) -> list[str]:  # pragma: no cover - interface
        """Return a list of paraphrase / synonym queries for `query`.

        Guaranteed by contract to return between `min_count` and
        `max_count` strings (inclusive); the caller may choose to raise
        or fall back if the returned list is out of bounds.
        """
        ...


# ---------------------------------------------------------------------------
# LiteLLM implementation
# ---------------------------------------------------------------------------


_LITE_LLM_SYSTEM = (
    "你是一个语义扩展助手。给定用户的检索问题，输出 3-5 条同义或相近含义的查询，"
    "覆盖用户可能使用的不同表述。仅输出 JSON 数组字符串，每条 <= 60 字，"
    "不要重复原句，不要添加解释。"
)


def _lite_llm_user_prompt(query: str, min_count: int, max_count: int) -> str:
    return (
        f"原始问题：{query}\n"
        f"请输出 {min_count}-{max_count} 条同义 / 近义查询，JSON 数组格式。"
    )


@dataclass
class LiteLLMQueryExpansionProvider:
    """Production provider — hands off to the shared LiteLLM client.

    B1 (phase B) will populate the corresponding `ai_prompt_profile`
    entry so the prompt can be versioned; for phase A the messages are
    inlined here so A5 has no cross-phase dependency.
    """

    llm_client: Any  # LiteLLMClientProtocol (avoid hard import cycle)
    model_alias: str = "primary-llm"

    def generate(
        self,
        query: str,
        *,
        min_count: int = DEFAULT_EXPANSION_COUNT_MIN,
        max_count: int = DEFAULT_EXPANSION_COUNT_MAX,
    ) -> list[str]:
        messages = [
            {"role": "system", "content": _LITE_LLM_SYSTEM},
            {"role": "user", "content": _lite_llm_user_prompt(query, min_count, max_count)},
        ]
        content, _summary = self.llm_client.call(
            self.model_alias,
            messages,
            temperature=0.3,
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        parsed = _parse_expansion_payload(content)
        return _clip_expansion_list(parsed, query, min_count, max_count)


def _parse_expansion_payload(content: str) -> list[str]:
    """Accept either a bare JSON array or an object wrapping ``queries``.

    Historic LLM outputs (and OpenAI's json_object mode) tend to return
    objects; the prompt requests a bare array. Handle both to keep the
    provider tolerant of prompt drift.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Best-effort: pluck any bracketed list of strings from the text.
        match = re.search(r"\[(?:.|\n)*?\]", content)
        if not match:
            raise
        data = json.loads(match.group(0))

    if isinstance(data, dict):
        for key in ("queries", "expansions", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = list(data.values())
    if not isinstance(data, list):
        raise ValueError("expansion payload is not a list")
    return [str(item).strip() for item in data if str(item).strip()]


def _clip_expansion_list(
    items: list[str], original: str, min_count: int, max_count: int,
) -> list[str]:
    """Deduplicate against the original query and clip to bounds.

    Order-preserving dedup — the LLM tends to put its best paraphrase
    first, so the caller can prioritise leading entries if it ever wants
    to weight them.
    """
    seen: set[str] = {original.strip()}
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= max_count:
            break
    if len(out) < min_count:
        logger.info(
            "query expansion returned %s items < min_count=%s (query=%s)",
            len(out), min_count, original[:60],
        )
    return out


# ---------------------------------------------------------------------------
# Search-time dedup / merge
# ---------------------------------------------------------------------------


def merge_and_dedup_hits(
    grouped_hits: dict[str, list[dict[str, Any]]],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    """Merge hits from several (query → hits) buckets, keeping max score.

    §1.11 决策 #3 explicitly rules out multi-path rerank fusion for P0;
    plain dedup by chunk id is what we need. When the same chunk is
    matched by multiple queries the winner is the highest score, and
    every matching query is recorded under
    ``metadata["matched_queries"]`` so downstream audit rows can attribute
    the retrieval breadth.

    Sort is deterministic (score DESC → chunk_id ASC) — the second key
    keeps tests reproducible when scores tie.
    """
    best_by_id: dict[str, dict[str, Any]] = {}
    matched_by_id: dict[str, list[str]] = {}

    for query_key, hits in grouped_hits.items():
        for hit in hits:
            chunk_id = str(hit.get("nexus_chunk_id") or "")
            if not chunk_id:
                continue
            existing = best_by_id.get(chunk_id)
            if existing is None or float(hit.get("score", 0.0)) > float(existing.get("score", 0.0)):
                # Shallow copy — the caller decides ownership of the
                # embedded metadata dict; we mutate our copy freely.
                best_by_id[chunk_id] = dict(hit)
                # Preserve any pre-existing metadata but let us rewrite
                # matched_queries below.
                if best_by_id[chunk_id].get("metadata") is not None:
                    best_by_id[chunk_id]["metadata"] = dict(
                        best_by_id[chunk_id]["metadata"]
                    )
                else:
                    best_by_id[chunk_id]["metadata"] = {}
            matched_by_id.setdefault(chunk_id, [])
            if query_key not in matched_by_id[chunk_id]:
                matched_by_id[chunk_id].append(query_key)

    for chunk_id, hit in best_by_id.items():
        hit["metadata"]["matched_queries"] = matched_by_id[chunk_id]

    ordered = sorted(
        best_by_id.values(),
        key=lambda h: (-float(h.get("score", 0.0)), str(h.get("nexus_chunk_id", ""))),
    )
    return ordered[:top_k]


# ---------------------------------------------------------------------------
# Expansion runner — orchestrates provider call + fallback
# ---------------------------------------------------------------------------


@dataclass
class ExpansionResult:
    """Outcome of an attempted expansion run.

    Callers use this to (a) pick which queries to actually run through
    the vector search and (b) tag the resulting metadata with a stable
    `expand_queries_status` for the audit summary.
    """

    queries: list[str]                 # queries to run (always includes original)
    status: str                        # "true" | "false" | "false_due_to_error"
    error_message: str | None = None


def build_expansion_queries(
    *,
    original_query: str,
    provider: QueryExpansionProvider | None,
    expand_queries: bool,
    min_count: int = DEFAULT_EXPANSION_COUNT_MIN,
    max_count: int = DEFAULT_EXPANSION_COUNT_MAX,
) -> ExpansionResult:
    """Return the list of queries to run (original + optional expansions).

    * `expand_queries=False` → returns just `[original_query]`, status
      "false". Zero provider dependency; guarantees v1 behaviour.
    * `expand_queries=True` + provider is None → same as False, but
      status "false_due_to_error" (misconfiguration surfaces as an audit
      signal rather than a silent skip).
    * `expand_queries=True` + provider raises → same fallback with
      `error_message` populated.
    """
    if not expand_queries:
        return ExpansionResult(queries=[original_query], status="false")
    if provider is None:
        logger.warning(
            "expand_queries=True but provider not configured; falling back",
        )
        return ExpansionResult(
            queries=[original_query],
            status="false_due_to_error",
            error_message="provider_not_configured",
        )
    try:
        expansions = provider.generate(
            original_query, min_count=min_count, max_count=max_count,
        )
    except Exception as exc:  # noqa: BLE001 - never fail search on expansion
        logger.warning("query expansion failed: %s", exc)
        return ExpansionResult(
            queries=[original_query],
            status="false_due_to_error",
            error_message=str(exc)[:200],
        )
    return ExpansionResult(
        queries=[original_query, *expansions],
        status="true",
    )


__all__ = [
    "DEFAULT_EXPANSION_COUNT_MAX",
    "DEFAULT_EXPANSION_COUNT_MIN",
    "ExpansionResult",
    "LiteLLMQueryExpansionProvider",
    "PROMPT_PROFILE_SCENARIO",
    "QueryExpansionProvider",
    "build_expansion_queries",
    "merge_and_dedup_hits",
]
