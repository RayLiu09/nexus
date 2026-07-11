"""M-C.1 golden retrieval query contract.

Each ``queries.jsonl`` entry validates against :class:`GoldenQuery`.
The schema is deliberately layered so a query can assert as much or as
little as the author has confidence in:

* **Structural** — Pack status, sub_query count, involved domains /
  channels.  Cheap, low-flake; enforceable without seeded fixtures.
* **Behavioral** — Warnings that must / must not appear.  Catches
  regressions in Phase A short-circuits, DAG binding failures, rerank
  suppression semantics.
* **Content** — Record IDs the executor must return (or must NOT
  return).  Requires a matching fixture to be seeded via
  :attr:`GoldenQuery.fixture_setup`; skipped for queries without one.

M-C.1 delivers the schema + a seed set + a harness that runs the
executor path (via ``prebuilt_plan``) without touching LiteLLM /
pgvector.  Later milestones grow coverage: M-C.2 adds recorded
LiteLLM cassettes for intent + planner; M-C.3 adds real pgvector.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


GoldenCategory = Literal[
    "single_domain",       # one profile, no dependencies
    "aggregation",         # count_by / trend_by profile
    "tag_filter",          # narrows via Phase A tag_filters
    "multi_hop",           # DAG binding across two sub_queries
    "rerank",              # WEIGHTED combine op
    "edge_case",           # I-6 optional_bucket_empty, empty intersection
    "negative",            # expects failure or empty result
]


class GoldenQuery(BaseModel):
    """One line of ``queries.jsonl``.

    ``prebuilt_plan`` bypasses intent+planner entirely, letting the
    harness exercise the executor / DAG / rerank / audit path without a
    LiteLLM dependency.  When present, it is passed directly to the
    orchestrator's ``_execute_plan`` call path.  Absent means the case
    requires real intent+planner and is deferred to M-C.2.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    category: GoldenCategory
    domain_focus: str = Field(min_length=1)

    # Setup dispatch — the harness maps this string to a Python
    # function that seeds SQLite fixtures for the case.  ``None`` runs
    # the case against an empty DB (only structural assertions apply).
    fixture_setup: str | None = None

    # Skips the intent+planner and hands this plan directly to the
    # orchestrator's execution loop.  Free-form dict — validated by the
    # runtime ``RetrievalPlan`` Pydantic model at load time.
    prebuilt_plan: dict[str, Any] | None = None

    # M-C.2 — points to a cassette JSON file under
    # ``tests/fixtures/retrieval_golden/llm_cassettes/{id}.json``.  When
    # set (and ``prebuilt_plan`` is ``None``), the harness runs the full
    # ``RetrievalOrchestrator.run()`` loop with a
    # ``CassetteLiteLLMClient`` injected in place of the real LiteLLM
    # client, so intent recognition + planner + executors all execute
    # against recorded responses.  ``None`` means the case cannot yet
    # be run via the LLM path (either it has ``prebuilt_plan`` for
    # M-C.1 backward-compat, or its cassette is pending).
    llm_cassette_id: str | None = None

    # ---- Structural expectations ----

    expected_pack_status: Literal[
        "completed", "partial", "failed", "needs_clarification",
    ] | None = None
    expected_sub_query_count: int | None = None
    expected_channels: list[str] = Field(default_factory=list)
    expected_domains: list[str] = Field(default_factory=list)
    expected_result_shapes: list[str] = Field(default_factory=list)

    # ---- Behavioral expectations (warnings) ----

    expected_warnings_contains: list[str] = Field(default_factory=list)
    expected_warnings_not_contains: list[str] = Field(default_factory=list)

    # ---- Content expectations (per sub_query) ----

    # qid → record IDs that must appear in ``result.records`` (or
    # ``result.items`` for unstructured channel).  Empty list means "no
    # assertion for this sub_query".  Entries may contain
    # ``$fixture.<key>`` placeholders (e.g. ``$fixture.record_ids[0]``)
    # that the harness substitutes against the fixture return dict
    # before comparing.
    expected_record_ids_subset: dict[str, list[str]] = Field(default_factory=dict)
    # qid → record IDs that must NOT appear.  Useful for edge cases
    # where a tag_filter should have excluded a specific record.
    expected_record_ids_disjoint: dict[str, list[str]] = Field(default_factory=dict)
    # qid → minimum number of records the executor must return.  Useful
    # for xlsx-bootstrap fixtures where individual UUIDs are unstable
    # but structural cardinality is guaranteed by the sample content.
    expected_records_at_least: dict[str, int] = Field(default_factory=dict)

    # ---- Rerank expectations (WEIGHTED cases) ----

    # qid → ordered list of record IDs the rerank must produce.  Only
    # asserted when ``retrieval_rerank_enabled`` is on for the harness
    # invocation.
    expected_rerank_order: dict[str, list[str]] = Field(default_factory=dict)

    # ---- Editorial ----

    notes: str = ""
    tags: list[str] = Field(default_factory=list)

    @field_validator("case_id")
    @classmethod
    def _case_id_snake(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("case_id must not be empty")
        return stripped
