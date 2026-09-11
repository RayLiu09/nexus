# Task Package: Console Prompt Management

## Source Context

- `AGENTS.md`: Prompt management belongs to NEXUS through
  `ai_prompt_profile`; Prompt mutations are versioned and audited.
- `ARCHITECT.md` and `SPEC.md`: Prompt profiles use save-to-activate
  semantics, archive the preceding active version, and do not expose a draft
  or model-gateway lifecycle.
- `WORKFLOWS.md`: this UI slice requires Frontend UX, API Contract, AI
  Governance, and Permission And Audit review.
- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`: NX-13 is the
  Prompt configuration surface under Governance Management.

## Goal

Replace the two overlapping Prompt pages with one usable `/ai-prompts`
workspace. Operators select a known runtime business scenario, edit its active
Prompt and structured output Schema in one document-like surface, validate it,
inspect immutable history, and save a new active `ai_prompt_profile` version.

## Scope

- Canonical `/ai-prompts` Console page, scenario registry, and responsive
  left/right editor experience.
- Eight fixed core scenarios plus a collapsed group of four editable domain
  scenarios.
- Browser-to-API proxies for profile history, candidate validation, and
  governance candidate dry-run.
- `/governance-prompts` compatibility redirect and navigation de-duplication.
- Focused Console tests and Prompt update idempotency header forwarding.
- Root architecture/product/readme and Prototype UI contract alignment.

## Out Of Scope

- Database migrations or changes to `ai_prompt_profile` fields and state.
- Prompt creation, deletion, disabling, drafts, approval, A/B tests, or gray
  release.
- LiteLLM provider, credential, route, model alias, or token-limit management.
- Runtime integration of `retrieval.query_expansion_v2`.
- Editing technical `body_markdown_render` profiles.
- Non-governance dry-run adapters. Their action stays visibly unavailable until
  each runtime can execute an unsaved candidate with its own input contract.

## Forbidden Changes

- Do not use `governance_prompt_template` as the page source of truth.
- Do not expose retained `litellm_model_alias` or `max_input_tokens` columns.
- Do not flatten `output_schema` into unparsed Prompt prose.
- Do not let operators introduce placeholders outside the scenario-owned
  runtime variable allowlist.
- Do not log full Prompt text, dry-run input/output, API keys, or sensitive
  normalized content.
- Do not change governance inputs or targets away from
  `normalized_asset_ref`.

## Frozen UI Contract

- Governance Management contains `治理审核`, `治理追踪`, `规则配置`, and
  `Prompt 提示词`; `/ai-prompts` is canonical.
- The first core scenario, `数据资产分类`, is selected by default.
- The right header shows scenario name/description, active status,
  `profile_version`, `prompt_version`, update actor/time, and a short content
  hash.
- Prompt text, allowed variables, output requirements, and structured JSON
  Schema are sequential sections of one central editor surface. The active
  version is editable immediately and has no Edit button.
- Bottom actions are `历史版本`, `重置`, `校验`, `试运行`, and `保存并生效`.
- Switching scenarios with unsaved changes requires confirmation. History is
  read-only. Save requires a change summary and creates a new active version.

## Deliverables

- Typed scenario registry and Prompt Profile Console client.
- Required Next.js route handlers.
- Rebuilt Prompt management page and focused component/registry/navigation
  tests.
- Updated architecture/product/prototype documentation and review evidence.

## Acceptance

- Core scenarios render in the frozen order and the first is selected.
- Domain business prompts are collapsed by default; Markdown-render and query
  expansion profiles never appear.
- Prompt and Schema edits are resettable, locally checked against the variable
  allowlist, and server validated before save.
- Save submits once with an idempotency key and required change summary; the
  returned active version replaces the editor baseline.
- History can be inspected without mutating the active draft.
- Governance dry-run accepts a `normalized_ref_id` and persists no result;
  unsupported scenario dry-run controls are explicitly disabled.
- API, component, navigation, type, lint, build, and diff checks pass, subject
  to available local services.

## Review Gates

- Frontend UX Gate: split layout, direct editing, responsive behavior,
  unsaved-change guard, action states, errors, and empty/missing-profile states.
- API Contract Gate: active/history/validate/dry-run/update mappings preserve
  typed envelopes, structured Schema, and idempotency headers.
- AI Governance Gate: one Prompt source, scenario variable allowlists,
  candidate validation, governance-only dry-run, immutable version history,
  and save-to-activate semantics.
- Permission And Audit Gate: existing authenticated internal boundary is
  retained; navigation remains steward-gated; mutations preserve actor and
  trace audit behavior without logging Prompt or model content.
