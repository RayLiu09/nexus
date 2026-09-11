# AI Prompt And Generative Model Consolidation Review Evidence

Date: 2026-09-11

Task package: `docs/task-packages/wk_ai_prompt_model_consolidation_task_package.md`

Target Alembic revision: `20260911_0102`

## Outcome

The backend implementation is ready for human Review Gate approval.

- `ai_prompt_profile` is the sole runtime source for the five governance
  Prompts.
- All NEXUS text generation and structured extraction paths resolve through
  `DEFAULT_GOVERNANCE_MODEL`.
- The retained `litellm_model_alias` and `max_input_tokens` columns are not
  exposed by Prompt APIs and do not affect runtime behavior.
- Embedding, tag-embedding, and reranking configuration remains independent.
- No `nexus-console` files were changed.

## Data Model Gate

Status: pass, pending human approval.

- Migration `20260911_0102` adds `output_schema`, `content_hash`, and
  `change_summary` to `ai_prompt_profile`.
- `litellm_model_alias` and `max_input_tokens` remain physically present.
- New/migrated rows use `__runtime_default_governance_model__` and `0` as
  compatibility sentinels; historical rows are not rewritten merely to change
  their legacy values.
- The historical `governance_prompt_template` table remains present.
- The partial unique index `uq_ai_prompt_profile_name_active` enforces at most
  one active row per `profile_name`.
- No reverse pointer or governance target was added. Governance still targets
  `normalized_asset_ref`.

Fresh-database verification found and fixed four pre-existing blockers in the
historical migration chain:

- `0011` and `0012`: PostgreSQL enums were explicitly created and then created
  a second time by SQLAlchemy. Table columns now reference the existing types
  with `create_type=False`.
- `0030`: JSON metadata is explicitly cast to JSONB before using the JSONB
  containment operator.
- `0072`: the outline-node index migration now skips the index already created
  by `0065`.
- `0078`: the conditional aggregate insert now emits zero rows when an active
  knowledge-inference Prompt already exists.

These fixes do not alter already-applied schemas; they make clean PostgreSQL
installation and migration replay deterministic.

## PostgreSQL Evidence

Status: pass.

An isolated PostgreSQL 15 instance with pgvector was created without a mounted
data volume. The complete migration chain from an empty database to head
completed successfully. Both temporary containers were removed afterward.

The `.env.dev` target database was then checked at `20260909_0101` and upgraded
only through:

```text
20260909_0101 -> 20260911_0102
```

Post-migration checks on the target database confirmed:

- `alembic_version = 20260911_0102`.
- Exactly five active `metadata_governance` Profiles exist:
  `governance.classification`, `governance.level_assessment`,
  `governance.quality_assessment`, `governance.tagging`, and
  `governance.knowledge_inference`.
- All five migrated Profiles contain the compatibility alias and token
  sentinels.
- No `profile_name` has more than one active row.
- Both `ai_prompt_profile` and `governance_prompt_template` exist.
- Both legacy columns exist.
- A transaction-scoped attempt to insert a second active
  `governance.classification` row was rejected by
  `uq_ai_prompt_profile_name_active`; the transaction was rolled back.

## AI Governance Gate

Status: pass, pending human approval.

- Governance Prompt registry reads only the five fixed active
  `ai_prompt_profile` names.
- Classification executes first. Dependent stages are not called if
  classification fails.
- Classification context is passed into level, tagging, quality, and knowledge
  inference stages.
- Every stage uses a typed Pydantic output validator and registry-based
  whitelists where applicable.
- Redaction, L3/L4 private-model policy, rules, confidence thresholds, and the
  governance state machine remain in the execution path.
- AI quality output is advisory; `QualityScoringService` remains authoritative
  for official score, blockers, and disposition.
- AI knowledge inference is advisory; active rules remain authoritative for
  official knowledge emissions.
- `AIGovernanceRun.model_alias` remains and records the model actually resolved
  from `DEFAULT_GOVERNANCE_MODEL`.
- Execution snapshots record Profile ID/name/version, Prompt version, content
  hash, model alias, and model source.

## API Contract Gate

Status: pass, pending human approval.

- Internal Prompt APIs provide create, versioned update, disable, list filters,
  history, validation, saved-profile dry-run, and unsaved-candidate dry-run.
- Request/response schemas omit `litellm_model_alias` and `max_input_tokens`.
- OpenAPI component checks confirm both fields are absent from
  `PromptProfileCreate`, `PromptProfileUpdate`, and `PromptProfileRead`.
- The historical `/admin/governance-prompts` compatibility routes now read and
  write `ai_prompt_profile`; tests confirm they do not insert into
  `governance_prompt_template`.
- Candidate and saved-profile dry-runs use normalized refs and the production
  validation/redaction path, and do not persist governance runs or results.
- Create remains protected by the existing idempotency dependency. Existing
  update/disable route semantics were not broadened in this task.

The installed AnyIO/Starlette test combination blocks all synchronous FastAPI
routes in the test thread pool, including a minimal one-route application.
Therefore the new focused API tests call the route functions directly while
exercising the real schemas, services, session, versioning, and audit writes.
This is a test-environment limitation, not an observed production endpoint
deadlock. Existing TestClient coverage remains affected independently of this
change.

## Permission And Audit Gate

Status: pass, pending human approval.

- The existing `/internal/v1` authenticated-user boundary is unchanged.
- No role-level authorization was added.
- Prompt create, update, disable, and compatibility-route mutations pass the
  authenticated user ID and request trace ID to the service.
- Focused tests verify `created_by`, Profile `trace_id`, audit `actor_id`, audit
  `trace_id`, event type, and target ID.
- Deprecated environment warnings log variable names only, never values.
- Prompt bodies, credentials, raw L3/L4 content, and API keys are not added to
  mutation audit summaries.

## Version State Gate

Status: pass, pending human approval.

- Prompt save archives the previous active version and inserts a new active
  version.
- Prompt history remains immutable and ordered by descending version.
- Disabling a Prompt does not invent a new status value.
- Governance admission and asset-version state transitions remain owned by the
  existing decision/state-machine services.
- The single-available-asset-version constraint and review triggers are
  unchanged.

## Verification

Focused tests, all passing:

```text
AI governance, validation, redaction, retry, consolidation: 77 passed
Retrieval intent/planning/composition/routing/expansion:     167 passed
Knowledge/body/task/evidence/teaching-standard flows:       182 passed
Prompt API contract tests:                                    5 passed
Total focused:                                              431 passed
```

Additional checks, all passing:

```text
python3 -m compileall -q nexus-app/nexus_app nexus-api/nexus_api nexus-app/alembic/versions
cd nexus-app && .venv/bin/alembic heads
# output: 20260911_0102 (head)
git diff --check
```

Production-code scans return no matches for reads of Prompt/Profile legacy
model or token fields, and no matches for removed per-feature model Settings
properties. Deprecated environment names remain only in the warning-name list
and explicit deprecation tests.

## Acceptance Gate

Status: task scope pass, pending human approval.

- Prompt source consolidation, five-stage maintenance, runtime model
  consolidation, migration, permission preservation, audit traceability, and
  documentation are implemented.
- PostgreSQL clean-install migration, target-database migration, data backfill,
  and uniqueness constraints were verified.
- No frontend, model-gateway, provider credential, release-management,
  operations-center, or P1/P2 feature was added.

The repository-wide test suite still contains unrelated existing failures in
tag projection/whitelists, pipeline stage-order expectations, capability graph
whitelists, environment expectations, transaction-boundary tests, and tool
schema alignment. Focused tests covering every changed runtime area pass; those
baseline failures were not modified as part of this bounded task.
