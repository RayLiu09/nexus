# WORKFLOWS.md

This file defines how humans and AI Agents collaborate on NEXUS. It is part of the coding-agent contract together with `CLAUDE.md`, `AGENTS.md`, `ARCHTECT.md`, and `SPEC.md`.

The workflow is distilled from `docs/基于AI Agent的开发计划v1.0.md` and applies to the full repository unless a deeper workflow document explicitly overrides it.

## Operating Model

NEXUS development uses AI Agents as the primary implementation force and humans as task owners, reviewers, integrators, and final decision makers.

Recommended delivery rhythm:

- 6 weeks to reach an internal P0-acceptable build.
- 2 additional weeks reserved for defect convergence, external-system integration, demo hardening, and formal delivery.
- P1/P2 requests must not consume the 2-week buffer unless the user explicitly changes scope.

Core principle:

```text
contract first -> small task package -> AI implementation -> AI-assisted contract review
    -> human Review Gate -> tests and demo evidence -> small merge -> weekly demo slice
```

## Human And AI Collaboration

| Participant | Role | Responsibilities |
|-------------|------|------------------|
| Backend developer / project owner / AI engineer | Human owner | Task decomposition, architecture decisions, backend Review, AI governance Review, API acceptance, milestone reporting. |
| Frontend developer | Human owner | Frontend architecture, page Review, interaction acceptance, demo-path stability. |
| Business expert | Key stakeholder | Sample data, fields, rules, Prompt examples, quality scoring dimensions, search questions, permission cases, acceptance opinion. |
| Backend Agent | AI implementation lead | APIs, database models, migrations, jobs, governance, permissions, audit, backend tests. |
| Frontend Agent | AI implementation lead | Pages, components, forms, state labels, drawers, dialogs, API integration. |
| Test Agent | AI quality support | Unit tests, contract tests, E2E cases, permission cases, regression checklist. |
| Docs Agent | AI documentation support | API docs, deployment notes, rule docs, AI governance docs, acceptance materials. |
| Review Assistant Agent | AI review support | Check changes against `ARCHTECT.md`, `SPEC.md`, Prototype v2.2, and this workflow. |

AI Agents may work in parallel, but final merges, architecture decisions, and high-risk approvals are human responsibilities.

## Parallel Multi-Agent Division

Recommended parallelization:

- Backend Agent and Frontend Agent work in parallel only after API contracts, schemas, status enums, and UI state semantics are frozen.
- Test Agent works alongside feature development and must not be postponed to the end of a milestone.
- Docs Agent updates docs and acceptance evidence before milestone demonstrations.
- Review Assistant Agent checks contract drift before human review.

Do not parallelize in these ways:

- Multiple Agents editing the same core model or migration file at the same time.
- Frontend and backend large-scale implementation before API/schema contracts are frozen.
- One Agent producing a large cross-cutting patch that changes data model, backend, frontend, tests, and docs in one pass.
- Any Agent adding P1/P2 scope during the P0 delivery or formal buffer period.

## Parallel Contract First Rule

This rule applies only when a task cycle uses multiple AI Agents in parallel. It is not required for single-Agent or single-owner work.

When parallel AI Agent work exists, the task cycle must start by creating a parallel-agent contract before implementation begins.

The parallel-agent contract must define:

- Shared objective and milestone for the current task cycle.
- Participating Agents and human owner.
- Frozen API paths, request/response schemas, state enums, event names, UI state semantics, and data ownership boundaries.
- Disjoint write ownership for each Agent, including files, modules, pages, tests, and docs.
- Shared mock data or fixtures.
- Integration sequence and merge order.
- Review Gates that must be passed before integration.
- Conflict resolution rule if Agents produce incompatible assumptions.

Do not start parallel implementation before the contract is agreed. If parallelism is introduced after work has started, pause and create the parallel-agent contract before continuing.

## AI Agent Task Package

Every non-trivial AI Agent task must be framed as a task package. A task package must include:

```text
Task name:

Source context:
  - Reference specific constraints from ARCHTECT.md, SPEC.md, Prototype v2.2, or WORKFLOWS.md.

Goal:
  - User value or engineering capability to deliver.

Scope:
  - Allowed modules, files, APIs, pages, tests, and docs.

Out of scope:
  - Explicitly excluded work.

Forbidden changes:
  - Do not introduce enterprise IAM.
  - Do not develop llm-gateway.
  - Do not create an independent ai-governance-orchestrator.
  - Do not add document_asset.current_version_id.
  - Do not add document_version.normalized_ref_id.
  - Do not add a quality-report reverse pointer on document_version.
  - Do not let AI output bypass rule guardrails into governance_result.
  - Do not add P1/P2 features unless the user explicitly changes scope.

Deliverables:
  - Code.
  - Migration, if needed.
  - Tests.
  - API/page documentation, if affected.
  - Audit or traceability evidence, if affected.

Acceptance:
  - Runnable test command or verification steps.
  - Demo path, if user-facing.
  - Key assertions.
```

Task size rule:

- Prefer 0.5 to 1.5 days of work per task package.
- Split larger work by bounded ownership: model, API, worker, frontend page, tests, docs.
- Do not let one task package own unrelated write sets.

## Standard Workflow

1. Confirm the contract.

Read `ARCHTECT.md`, `SPEC.md`, Prototype v2.2, and relevant root agent instructions before implementation.

2. Freeze the interface.

For cross-cutting features, freeze API path, request/response schema, state enum, error codes, UI state labels, audit events, and test expectations before parallel coding.

3. Assign task packages.

Create bounded task packages with allowed files, forbidden changes, deliverables, and acceptance evidence.

4. Implement with AI Agents.

Agents implement code, tests, and docs inside their assigned ownership. Agents must not silently change architecture or product behavior to simplify implementation.

5. Run AI-assisted contract review.

Review Assistant Agent checks for drift against `ARCHTECT.md`, `SPEC.md`, Prototype v2.2, and this workflow.

6. Run human Review Gate.

Human owners review high-risk changes using the gates below.

7. Verify.

Run relevant tests, check demo path, inspect audit/traceability evidence, and confirm no P1/P2 creep.

8. Merge small.

Merge only bounded, reviewed, tested changes. Avoid large late integration.

9. Demonstrate weekly.

Maintain at least one demonstrable slice per week and a formal milestone every two weeks.

## API Implementation Constraints

API implementation must follow these ownership and style rules:

- Business-facing APIs for upper systems, API callers, smart apps, integration clients, search, QA, jobs, assets, governance execution, and auth verification are owned by the `nexus-api` package.
- `nexus-api` is the service boundary for externally consumed business APIs. Do not implement business-facing integration APIs inside `nexus-console`.
- `nexus-console` owns control-plane APIs required by the admin console and implements them with the Next.js full-stack pattern, such as route handlers or server actions where appropriate.
- In principle, `nexus-console` control-plane APIs are internal to the admin console and must not be exposed as business-facing APIs for external callers.
- `nexus-console` control-plane APIs must not bypass `nexus-api` ownership for business-facing capabilities. If a console action exposes a capability that upper systems also need, the canonical API belongs in `nexus-api`.
- All APIs must follow RESTful style: resource-oriented paths, HTTP methods with conventional semantics, status codes with explicit error bodies, stable request/response schemas, and idempotency for mutating operations where required.
- Keep `/v1` as the external business API prefix for `nexus-api`.
- Console-only control APIs may use the Next.js app routing conventions, but their resource naming, method semantics, errors, and schemas must remain RESTful and documented.
- API contract changes require API Contract Gate review before parallel backend/frontend Agent work begins.

## Weekly Task Start Rule

Every weekly implementation cycle must start by reading the corresponding task package under `docs/task-packages/`.

Required startup sequence:

1. Identify the target week and open `docs/task-packages/wk_<week>_task_package.md`.
2. Read the week goal, Agent division, task packages, Review Gates, and done definition.
3. Select or create the specific task package for the current implementation slice.
4. Reconfirm allowed scope, out-of-scope items, forbidden changes, deliverables, and acceptance evidence before editing code.
5. If the task is not covered by the weekly package, update or create a bounded task package before implementation.

Do not start implementation from memory, chat context, or broad product documents alone. The weekly task package is the operational entry point for AI Agent work.

## Review Gate

The following changes require human approval before merge.

| Gate | Trigger | Human review focus |
|------|---------|--------------------|
| Data Model Gate | New or changed master tables, status fields, relation fields, migrations | No reverse pointers; single-direction references; correct uniqueness; audit fields; no `current_version_id`; no `normalized_ref_id`. |
| AI Governance Gate | LiteLLM calls, Prompt config, AI output adoption, quality scoring | Still depends on LiteLLM; Prompt is versioned; L3/L4 is redacted; AI output passes Schema, whitelist, redaction, rule guardrails, confidence and audit. |
| Rule Engine Gate | Rule expressions, save-to-activate rule changes, conflict handling | No arbitrary code execution; input is standardized object context; conflicts are traceable; rule save/disable is audited. |
| Permission And Audit Gate | Search, QA, API Key, org scope, L3/L4 exception masking, audit logs | Auth before return; no permission leakage; high-sensitivity exception data is masked by default; key actions audited; trace_id present. |
| Version State Gate | `processing`, `available`, `review_required`, `archived`, `disabled`, `failed` transitions | Only one available version; correct review triggers; index status consistency; state changes audited. |
| RAGFlow Integration Gate | Chunking, indexing, retrieval, QA citations | `index_manifest` is queryable; failures recoverable; results trace to version, normalized ref, chunk, and raw object. |
| API Contract Gate | New or changed `/v1` API behavior | Request/response schema stable; errors defined; idempotency addressed; frontend mapping updated; tests added. |
| Frontend UX Gate | P0 console flow, high-risk dialogs, state labels | Prototype v2.2 aligned; no NEXUS AI gateway management page; disabled states and errors clear. |
| Acceptance Gate | Milestone or final acceptance | E2E evidence, permission leakage 0, traceability 100%, audit coverage 100%, no P1/P2 creep. |

## Review Checklist

Before merging, check:

- The change does not violate v2.4 architecture boundaries.
- The change does not introduce P1/P2 scope.
- The change includes tests or explicit verification evidence.
- Failure paths and disabled states are handled.
- Audit logs and `trace_id` are present for key actions.
- Permission filtering and masking happen before returning sensitive content.
- Results can trace to asset version, normalized reference, chunk, and raw object where applicable.
- API, field, or page documentation is updated if behavior changed.
- AI output cannot directly write official governance state without rule guardrails.
- Logs do not contain API keys, L3/L4 plaintext, or large raw content.

## Quality Gates

| Gate | Requirement |
|------|-------------|
| Build/static checks | Backend and frontend baseline checks pass. |
| Unit tests | State transitions, rule execution, AI output validation, permission filtering, idempotency are covered where touched. |
| Contract tests | `/v1` request/response, Pydantic schemas, and frontend field mappings stay consistent. |
| E2E tests | Cover static document ingest, crawler JSON, AI auto-adoption, conflict review, rule re-governance, permission isolation, QA citation, reprocess, index failure recovery, idempotency, no-DingTalk local identity, AI re-score. |
| Security tests | L3/L4 exception data masked by default; API keys are not logged; cross-org access denied by default; rule expressions cannot execute arbitrary code. |
| Audit tests | Prompt, rules, permissions, version status, AI adoption, human override, API Key changes are auditable. |
| Demo gate | A milestone must have a working end-to-end demo path and evidence. |

## Milestone Evidence

| Milestone | Evidence required |
|-----------|-------------------|
| M1 Ingest To Asset | Ingest request, raw object, job record, normalized reference, asset catalog, asset detail, current version read model. |
| M2 AI Governance And Rules | Prompt config version, LiteLLM alias, AI run, `governance_result.quality_summary`, rule hit, `governance_result.decision_trail`, `available` and `review_required` examples. |
| M3 P0 Full Flow | RAGFlow index manifest, search/QA result, permission filtering, L3/L4 exception masking, source traceability, reprocess, re-governance, AI re-score, audit log. |
| M4 Formal Acceptance | 12 E2E results, NFR metrics, Go/No-Go table, business acceptance opinion, known issues by severity, delivery docs. |

## Buffer Rules

The final buffer period is for quality and formal delivery only.

- Do not accept new P1/P2 features.
- Do not refactor already accepted P0 flows unless the refactor is needed for a blocking defect.
- Fix only issues that block acceptance, security, traceability, demo stability, or required docs.
- Every buffer-period fix needs test evidence or explicit acceptance evidence.
