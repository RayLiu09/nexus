# Console Prompt Management Review Evidence

Date: 2026-09-11

Task package: `docs/task-packages/wk_console_prompt_management_task_package.md`

## Outcome

The Console Prompt management implementation is ready for human Review Gate
approval.

- `/ai-prompts` is the single Prompt workspace; `/governance-prompts`
  redirects to it and Governance Management contains one `Prompt 提示词`
  navigation entry.
- The eight approved core business scenarios render in the frozen order. The
  first active Profile is selected and immediately editable when the backend
  returns the current Prompt Profile contract.
- Four additional runtime business Profiles are available under the
  default-collapsed domain group. Technical `*.body_markdown_render` Profiles
  and the currently unconsumed `retrieval.query_expansion_v2` Profile are not
  exposed.
- Prompt Markdown, allowed variables, structured JSON Schema, and runtime
  parameters form one continuous editor surface. Model alias and input-token
  controls are not exposed.
- History, reset, validation, governance candidate dry-run, and versioned
  save-to-activate flows are wired to authenticated internal APIs.

## Frontend UX Gate

Status: pass, pending human approval.

- Desktop uses a stable left scenario rail and right editor. Mobile turns the
  scenario rail into a compact horizontal selector and stacks the editor
  metadata, fields, and actions.
- Scenario name, description, active status, Profile version, Prompt version,
  actor/time, and short content hash are visible above the editor.
- The active Prompt is directly editable without an Edit action. The bottom
  action bar contains only `历史版本`, `重置`, `校验`, `试运行`, and
  `保存并生效`.
- Switching scenes or resetting a dirty draft requires confirmation. Saving
  requires a change summary. Historical versions render in a read-only drawer.
- Missing Profiles have a dedicated empty state. API errors retain the shared
  trace-aware state. A rolling deployment that returns the old Profile list
  projection now produces a diagnostic error and locks mutation controls
  instead of crashing or risking an overwrite.

Playwright verification used the existing local Console at
`http://localhost:3000/ai-prompts` with no mutations:

```text
Desktop 1440x1000: document width 1440, no horizontal overflow
Mobile   390x844:  document width 390, no horizontal overflow
Both: 8 core scenarios, 1 selected scene, 1 Prompt editor,
      1 Schema editor, 1 action bar, 0 browser errors
```

Desktop and mobile screenshots were inspected for overflow, clipping,
incoherent overlap, and action wrapping. No layout defect was observed.

## API Contract Gate

Status: pass, pending human approval.

- The server page requests active `/internal/v1/ai/prompt-profiles` Profiles;
  client interactions use same-origin BFF routes for history, validation,
  candidate dry-run, and active-version update.
- BFF routes preserve the existing access-cookie boundary and only forward
  allow-listed conditional/idempotency headers.
- `output_schema` remains a structured JSON object across candidate
  validation, dry-run, and save payloads.
- Save carries a generated `Idempotency-Key`; client error mapping recognizes
  both normal API envelopes and BFF top-level `message` errors.
- Public Console types and controls do not include `litellm_model_alias` or
  `max_input_tokens`.
- Focused tests cover endpoint selection, payload mapping, structured Schema,
  idempotency-key forwarding, error propagation, and the rolling-deployment
  incomplete-contract state.

Initial browser verification found that the running local `nexus-api` process
predated the current worktree contract and omitted `prompt_template`,
`output_schema`, and `content_hash` from list responses. The explicit rolling
upgrade guard correctly locked the editor instead of risking an overwrite.
After restarting `nexus-api` from the current worktree, a read-only contract
probe confirmed all 15 active Profiles contained the required fields, all
templates were non-empty, and all Schemas were JSON objects. Browser
verification then confirmed the guard disappeared and both editors were
mutable.

## AI Governance Gate

Status: pass, pending human approval.

- `ai_prompt_profile` remains the only Prompt source used by this page.
- Five governance dry-runs require `normalized_ref_id`, execute the existing
  candidate validation/governance path, and persist no governance result.
- Retrieval and domain dry-run actions stay disabled because no candidate
  adapters exist for their runtime-specific inputs.
- Each visible scenario has an explicit runtime variable allowlist. Governance
  requires `{{RULES}}` and `{{DOCUMENT}}`; retrieval allowlists match the
  placeholders consumed by intent, parameter extraction, and composition
  runtimes.
- Unknown and missing variables are rejected locally before backend
  validation. The backend remains authoritative for full Prompt validation,
  redaction policy, rules, and model resolution.
- Save creates a new active version and relies on the existing Prompt service
  to archive the preceding active version. No draft, publish, disable,
  deletion, A/B, or gray-release lifecycle was added.

## Permission And Audit Gate

Status: pass, pending human approval.

- Existing authenticated `/internal/v1` and steward-gated navigation behavior
  is retained. No business-facing Prompt API or new permission model was added.
- Console sessions accept only the backend-issued `platform_data_admin` and
  `business_expert` roles. `ops` is not a Console role, and `api_caller`
  remains exclusive to Open API authentication. Login rejects both with 403
  without setting cookies; middleware clears and redirects any retained
  non-Console session. Focused login, middleware, and navigation tests cover
  the complete boundary.
- Active-version updates forward the operator access token, idempotency key,
  request trace, change summary, and actor context to the existing audited
  Prompt service path.
- Prompt bodies, model output, normalized content, secrets, and API keys are
  not logged by the new Console or BFF code.
- No create, disable, delete, or bulk mutation control is exposed, reducing
  the mutation surface to the approved versioned save operation.

## Verification

Passing checks:

```text
npm run typecheck
npm run test -- --run lib/prompt-scenarios.test.ts \
  lib/prompt-profiles-api.test.ts \
  app/ai-prompts/_components/AiPromptsContent.test.tsx \
  lib/navigation.test.ts
# 4 files passed, 18 tests passed

npm run lint
# 0 errors, 63 pre-existing repository warnings

npm run build
# production build passed; all Prompt BFF and page routes recognized

git diff --check
```

The full Console Vitest run completed with 45 of 46 files and 266 of 267 tests
passing. The only failure is the pre-existing `lib/status.test.ts` count
assertion: the test expects 29 status definitions while the implementation has
35. It is unrelated to Prompt management and was not modified.

## Acceptance Gate

Status: task scope pass, pending human approval.

- The approved business scenarios, direct editor, structured Schema,
  version/history behavior, save guardrails, responsive layout, navigation,
  compatibility redirect, and documentation are implemented.
- No database migration, gateway management, release management, monitoring,
  generic dry-run adapter, technical Markdown-render editor, or P1/P2 feature
  was added.
- The local `nexus-api` was restarted from the current worktree and passed its
  health, startup-log, Prompt response-contract, and Console browser checks.
