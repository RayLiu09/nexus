# Task Package: Teaching Standard Knowledge Pipeline Recovery

## Task name

Recover admitted teaching-standard assets whose completed asset pipeline has no
knowledge chunks or semantic index because `knowledge_emissions` were absent
or became visible after the initial chunking stage.

## Source context

- `ARCHITECT.md`: Knowledge Pipeline is independent from Asset Pipeline and is
  anchored by `normalized_asset_ref`; chunks and graph evidence remain
  traceable to that ref.
- `SPEC.md`: an index failure must be recoverable and traced in
  `index_manifest`; a completed pipeline must not falsely imply indexed
  retrieval availability.
- `nexus_app.pipeline.stages`: governance materializes deterministic
  `knowledge_emissions`, then chunking and index submission consume them.
- `nexus_app.evidence_graph`: graph builds are asynchronous worker envelopes,
  never inline LLM extraction in a request or long-lived transaction.

## Goal

Make the governed knowledge-processing tail self-healing and observable:
rederive deterministic emissions from the latest validated governance run when
an admitted ref is missing them, construct and index chunks idempotently, and
queue a graph build only when an explicit graph knowledge emission exists.

## Scope

- `nexus-app/nexus_app/pipeline/stages.py`
- `nexus-app/nexus_app/ai_governance/knowledge_type_inference.py`
- `config/governance_rules_v2.json`
- focused pipeline and knowledge-emission tests under `nexus-app/tests/`
- this task package and root contracts only if automatic graph enqueue changes
  a stated behavior.

## Out of scope

- A productized graph operations center or public graph API.
- Treating every available asset as graph-worthy.
- Task Outline generation for teaching standards; that remains textbook-only.
- Backfilling production rows manually before the recovery path is tested.
- New queues, Celery, RabbitMQ, or an LLM gateway.

## Forbidden changes

- Do not use raw file, raw JSON, or MinerU output as governance or graph
  input; use `normalized_asset_ref` and `knowledge_chunk` only.
- Do not run graph extraction or embeddings inside a long database transaction.
- Do not bypass governance/rule guardrails or create reverse master-data
  pointers.
- Do not convert a genuinely non-applicable knowledge type into an error.

## Deliverables

- Deterministic emission recovery before an admitted ref is skipped for missing
  emissions, with precise stage and audit detail.
- Idempotent graph-build envelope enqueue for an explicit graph emission after
  chunk construction, without inline graph extraction.
- A teaching-standard structural co-emission rule that has evidence-based,
  bounded lexical criteria.
- Regression tests for the historical late-emission case, index continuation,
  graph enqueue idempotency, and non-applicable skip behavior.

## Acceptance

```bash
cd nexus-app
uv run pytest tests/governance/test_pipeline_integration.py \
  tests/ai_governance/test_knowledge_emissions_e2e.py
```

- An `available` and index-admitted teaching standard with a valid latest AI
  run but missing `metadata_summary.knowledge_emissions` rebuilds emissions,
  chunks, and index manifests on a retry/catch-up run.
- An explicit graph emission creates at most one pending graph build for the
  same ref/profile/strategy; Worker execution remains asynchronous.
- A ref with no applicable deterministic emission remains `skipped` with an
  explicit reason rather than being reported as indexed.
