# Task Package: Pipeline A Office Document Reliability

## Source Context

- `AGENTS.md`: Pipeline A keeps `assetize` and `normalize` separate; MinerU
  parses Office documents; governance input is only `normalized_document` via
  `normalized_asset_ref`.
- `ARCHITECT.md` and `SPEC.md`: Pipeline A stores extracted images beside the
  parse artifact, carries full quality and lineage fields on the normalized
  reference, and routes low-quality assets through existing governance rules.
- Deployment baseline: MinerU is pinned to `mineru[core]>=3.0.0`; no version
  or capability-probe mechanism belongs to this slice.
- `WORKFLOWS.md`: a pipeline reliability change needs focused tests and the
  Version State and AI Governance review checks.

## Goal

Make Pipeline A reliably consume MinerU native DOCX and PPTX response ZIPs,
preserve their parse evidence safely, and expose deterministic Office parsing
quality signals to the existing normalization/governance path.

## Scope

- `nexus-app/nexus_app/mineru.py`: deterministic MinerU ZIP result selection,
  safe image identity preservation, and response metadata.
- `nexus-app/nexus_app/pipeline/stages.py`: normalized-document Office parse
  quality summary and anomaly propagation.
- `config/normalize_schemas.json`: add the PPTX document contract.
- Remove the deprecated normalize-stage `classification_hint_whitelist`; formal
  classification remains owned by AI governance's active registry and rules.
- Existing Console upload accept lists and raw-ledger MIME label mapping for
  the already-supported PPTX intake path.
- The real-sample E2E harness preflight, limited to validating only the
  pipeline feature flags required by files selected for the current run.
- Focused MinerU, Pipeline A, normalize, and routing regression tests.

## Out Of Scope

- MinerU version/capability probes, migration to asynchronous MinerU tasks,
  format conversion, antivirus scanning, schema/database migrations, new
  API endpoints, new Console flows, prompt/rule changes, and generic Office
  file parsers.
- Routing DOCX/PPTX to Pipeline B. Template-specific structured Office input
  remains a separate Pipeline B task.

## Forbidden Changes

- Do not change `Job.payload.pipeline_type` at worker runtime.
- Do not make raw files or MinerU raw output governance inputs.
- Do not replace the removed hint with a second classification registry or
  pre-populate governance classification from normalize.
- Do not add reverse pointers, new status enums, migrations, or a direct
  `available` / `review_required` state transition.
- Do not log raw Office content, model credentials, or large MinerU payloads.

## Deliverables

- Deterministic selection of the substantive MinerU JSON result in a ZIP.
- Collision-safe, path-safe extracted image identities and storage paths.
- Office parse-quality summary in `normalized_document.quality` and matching
  anomaly items that the existing governance layer may consume.
- DOCX/PPTX contracts and focused automated regression tests.

## Acceptance

- DOCX/PPTX keep `pipeline_type=document`, parse with the existing `pipeline`
  backend, and normalize to `normalized_document`.
- A ZIP with incidental JSON files selects the actual parse payload, not the
  first archive entry.
- Same-basename images from distinct archive paths both persist without path
  traversal or overwrite.
- Empty or structurally unusable Office output is recorded as a normalization
  quality anomaly; it does not become a raw-input governance shortcut.
- Focused tests run without a real MinerU endpoint and preserve existing PDF
  behavior.

## Review Gates

- Version State Gate: quality signals do not bypass the existing state machine.
- AI Governance Gate: only normalized-document quality/anomaly fields flow to
  governance; no prompt, adoption, or guardrail bypass is introduced.
