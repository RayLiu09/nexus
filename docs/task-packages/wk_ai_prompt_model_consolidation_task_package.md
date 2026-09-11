# Task Package: AI Prompt And Generative Model Consolidation

## Source Context

- `AGENTS.md`: NEXUS owns Prompt management through `ai_prompt_profile`; AI
  governance stays inside `metadata-service.ai-governance` and must retain
  schema, whitelist, redaction, rule, confidence, state-machine, and audit
  guardrails.
- `ARCHITECT.md`: Prompt profiles are save-to-activate, versioned, and auditable;
  governance consumes only `normalized_asset_ref` backed standardized content.
- `SPEC.md`: Governance Management owns Prompt configuration and governance
  traceability.
- `WORKFLOWS.md`: data-model, AI-governance, API-contract, permission/audit, and
  version-state changes require their corresponding Review Gates.

## Goal

- Make `ai_prompt_profile` the only runtime source for the five governance
  prompts: classification, level assessment, quality assessment, tagging, and
  knowledge inference.
- Retain `litellm_model_alias` and `max_input_tokens` physically on historical
  Prompt tables while removing both fields from effective configuration and
  runtime behavior.
- Route all NEXUS text-generation, structured-extraction, governance,
  normalization, knowledge-processing, and retrieval-orchestration calls through
  `DEFAULT_GOVERNANCE_MODEL`.
- Preserve independent embedding, tag-embedding, and reranking model settings.

## Scope

- `nexus-app` Prompt persistence/services, AI governance, normalization,
  knowledge extraction, body-markdown, domain LLM fallbacks, knowledge outline,
  Task Outline, evidence graph, retrieval, QA, configuration, scripts, models,
  schemas, and Alembic migrations.
- `nexus-api` internal Prompt and governance APIs.
- Backend tests, Docker/environment configuration, root contracts, runbooks,
  and review evidence.

## Out Of Scope

- `nexus-console` implementation or UX changes.
- LiteLLM provider, credential, routing, or gateway-limit management.
- Prompt approval workflow, draft state, gray release, or model A/B management.
- Consolidating embedding, tag-embedding, or reranking models.
- Physically dropping legacy Prompt columns or historical Prompt tables.

## Forbidden Changes

- Do not delete or rewrite historical `litellm_model_alias` or
  `max_input_tokens` values.
- Do not remove actual-model fields from AI run, analysis, retrieval, or audit
  records; they remain execution evidence.
- Do not let Prompt output bypass schema, field whitelist, redaction, rules,
  confidence thresholds, or version-state decisions.
- Do not merge assetize, normalize, AI governance, or Knowledge Pipeline stage
  ownership merely because they share a model alias.
- Do not add role-level authorization; retain the existing `/internal/v1`
  `require_user` boundary.
- Do not change governance targets away from `normalized_asset_ref`.

## Frozen Contracts

- The single effective generative-model source is
  `Settings.default_governance_model` (`DEFAULT_GOVERNANCE_MODEL`).
- Deprecated environment aliases and Profile model/token fields never override
  the effective model or LiteLLM call parameters.
- New Prompt rows populate retained non-null legacy columns with service-owned
  compatibility sentinels.
- Prompt mutations remain save-to-activate and immutable by version, with no
  draft state.
- Dry-run uses standardized input and the same validation/redaction path but
  persists no AI run, governance result, or asset-version state change.
- Quality AI output is advisory; deterministic quality rules own the final score,
  blockers, and disposition.
- Knowledge-type AI output is advisory; active governance rules own the official
  classification-to-primary-knowledge-type projection.

## Deliverables

- A bounded forward migration that seeds/migrates the five governance Prompt
  profiles and enforces at most one active version per `profile_name`.
- Unified runtime model resolution and removal of effective per-feature/model
  override behavior.
- Typed Prompt Profile lifecycle, validation, history, and dry-run APIs backed by
  `ai_prompt_profile`.
- Governance execution snapshots containing Prompt versions and the actual model
  resolved from `DEFAULT_GOVERNANCE_MODEL`.
- Focused model, migration, API, governance, redaction, fallback, retrieval, and
  audit tests.
- Updated architecture, product, repository, deployment, and review documents.

## Acceptance

- Changing legacy Prompt model/token columns or setting any deprecated model
  environment variable does not change runtime behavior.
- Normalize, governance, knowledge extraction/rendering, Task Outline subtype,
  evidence graph, retrieval orchestration, and QA resolve the same configured
  generative model.
- Embedding, tag-embedding, and reranker selection remains unchanged.
- Each governance Prompt name has at most one active version and history remains
  immutable.
- Five-stage governance uses `ai_prompt_profile`, validates every AI stage, and
  retains rule/state-machine authority.
- L3/L4 content cannot reach an unapproved external alias and logs contain no
  sensitive plaintext, API keys, or full prompts.
- Existing permissions remain unchanged while Prompt mutations record the
  authenticated actor and trace ID.
- Relevant `nexus-app` and `nexus-api` tests pass, including a PostgreSQL
  migration/constraint verification.

## Review Gates

- Data Model Gate: legacy fields retained, migration idempotency, active
  uniqueness, and no prohibited reverse pointers.
- AI Governance Gate: one runtime model source, immutable Prompt versions,
  redaction, stage validation, advisory AI quality/knowledge output, and audit.
- API Contract Gate: typed internal Prompt requests/responses and explicit legacy
  field deprecation.
- Permission And Audit Gate: unchanged authentication boundary, correct actor,
  traceability, and no sensitive logging.
- Version State Gate: governance admission remains governed by the existing state
  machine and single-available-version constraint.
- Acceptance Gate: focused and full backend verification evidence.
