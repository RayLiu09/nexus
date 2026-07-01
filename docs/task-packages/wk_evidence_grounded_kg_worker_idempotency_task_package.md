# Task Package: Evidence-grounded KG Worker + Idempotency

## Source Context

- `docs/evidence_grounded_kg_implementation_plan.md`: Evidence Graph build submit and Console view are implemented, but pending builds are not yet consumed by background processing.
- `nexus-api/nexus_api/api/internal/evidence_graph.py`: build submit currently creates duplicate pending envelopes when no succeeded build exists.
- `nexus-app/nexus_app/evidence_graph/`: candidate selection, extractors, and evidence-bound persistence already exist.
- `nexus-app/nexus_app/worker/loop.py`: P0 worker loop polls and executes job-table work; this slice adds lightweight polling for pending graph builds without introducing a new queue.

## Goal

Make Evidence Graph construction operational end to end for pending build envelopes while preserving idempotency: the same normalized asset version/profile/strategy cannot create duplicate active graph builds.

## Scope

- Build submit idempotency for `normalized_ref_id + graph_profile + strategy_version`.
- Evidence Graph build processor that selects candidates, extracts facts, persists graph rows, and marks build terminal.
- WorkerLoop integration that claims pending graph builds opportunistically.
- Cleanup migration for duplicate residual active build envelopes.
- Unit/API tests for idempotency and worker processing.

## Out Of Scope

- Public/open Evidence Graph APIs.
- Productized graph operations center.
- Distributed queue adoption.
- Large-scale graph rebuild scheduling.

## Forbidden Changes

- Do not bypass normalized_asset_ref as graph input.
- Do not run heavyweight graph extraction inline in API request handlers.
- Do not mix Evidence Graph tables with Pipeline B capability graph staging tables.
- Do not delete succeeded/review_required/failed graph history.

## Acceptance

- Submitting the same build repeatedly returns the existing active/succeeded build instead of creating duplicates.
- A pending Evidence Graph build is claimed by the worker and reaches `succeeded`, `review_required`, or `failed`.
- Formal graph rows are evidence-bound through `knowledge_graph_evidence`.
- Duplicate residual active envelopes are deprecated by migration, keeping one active build per ref/profile/strategy and enforcing the key with a partial unique index.
- Tests cover idempotent submit, pending worker processing, and duplicate cleanup behavior.
