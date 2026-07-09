# Task Package: Knowledge Outline LLM v2 — Contract-Compliant

Upgrade the v1 LLM heading-classifier prototype into a production
knowledge-outline builder that fully satisfies the NEXUS AI Governance
Contract (see `CLAUDE.md` §"AI Governance Contract").

## Source Context

- `nexus-app/nexus_app/knowledge_outline/llm_classifier.py` — v1 prototype
  landed in commit `7565d4e`.
- `nexus-app/scripts/rebuild_knowledge_outline_llm_v1.py` — v1 CLI.
- `nexus-app/nexus_app/models.py:687` `AIPromptProfile` — target home for
  the classifier prompt (versioned, snapshot-able).
- `nexus-app/nexus_app/models.py:798` `AIGovernanceRun` — target home for
  each rebuild's per-heading classification result.
- `nexus-app/nexus_app/enums.py:161` `PromptProfileStatus`,
  `AIGovernanceRunValidationStatus`, `AIGovernanceRunAdoptionStatus`.
- `nexus-app/nexus_app/ai_governance/services.py` — existing
  `PromptProfileService` (create/update/deactivate).
- Two golden textbooks:
  - `4b910214-372c-4dea-9dc7-5bb286154837` (新形态项目 X 教材) —
    401 headings → v1: 8 chapters + 68 knowledge_points.
  - `59901821-a154-4704-a220-56ace3dbf8c6` (普通职教第 X 章教材) —
    613 headings → v1: 11 chapters + 200 knowledge_points.

## Goal

Replace the v1 prototype call path with a contract-compliant pipeline:

1. **Prompt persistence**: classifier prompt lives in `AIPromptProfile`,
   is versioned + editable via the existing console AI Prompts page.
2. **Per-rebuild governance run**: each rebuild writes a single
   `AIGovernanceRun` (per-heading suggestions inside `ai_output`),
   linked to the outline via `knowledge_outline_node.metadata.ai_run_id`.
3. **Confidence-based adoption**: high-confidence auto-adopts, mid-range
   goes to a review queue, low-confidence is rejected — surfaced to SME
   for override.
4. **v1 fixes**: root title fallback ordering; adjacent chapter merge;
   100% chunk backfill via head/tail span extension.
5. **Human override**: SME can flip any heading's label via API; the
   override persists across rebuilds.

## Scope

### Backend

- v1 fixes (module-level in `llm_classifier.py`):
  - Root title: `payload.title` > `asset.title` > LLM `book_title` > `"全文"`.
  - Adjacent-chapter merge: if `chapter[i]` matches short prefix
    (`^项目\s?[一二三…]$` or `^第.*章$` with no trailing content) and
    `chapter[i+1]` is within 3 blocks, merge into one node with combined
    title.
  - Chunk backfill 100%: blocks before the first kept heading → attach
    to root; blocks after the last kept heading → attach to the last
    chapter's chunk span.
- New Pydantic schemas in `knowledge_outline/schemas.py`:
  - `HeadingClassificationOutput` (LLM response schema)
  - `KnowledgeOutlineReviewItemCreate` / `Read`
- Extend `nexus_app.enums.AuditEventType` with:
  - `KNOWLEDGE_OUTLINE_REVIEW_ITEM_CREATED`
  - `KNOWLEDGE_OUTLINE_REVIEW_ITEM_OVERRIDDEN`
- Alembic migration:
  - New table `knowledge_outline_review_item`
    `(id, normalized_ref_id, heading_block_id, ai_run_id, llm_label,
 llm_confidence, llm_reason, sme_override_label, sme_override_by,
 sme_override_at, status)` + indexes.
  - `ALTER TYPE auditeventtype ADD VALUE ...`.
- Seed data (`seed_data.py`):
  - Insert `AIPromptProfile` row with
    `profile_name="knowledge_outline_heading_classifier"`,
    `task_type="knowledge_outline_heading_classification"`,
    `scenario="course_textbook"`, `prompt_template=<SYSTEM_PROMPT>`,
    `output_schema_version="1.0"`,
    `litellm_model_alias=<settings.default_governance_model>`,
    `temperature=0.1`.
- Refactor `llm_classifier.py`:
  - Read the active prompt profile (via
    `PromptProfileService.get_active`) instead of the hard-coded
    `SYSTEM_PROMPT` constant.
  - For each rebuild:
    - Create one `AIGovernanceRun` row.
    - Compute `input_hash = sha256(json.dumps(heading_texts_ordered))`.
    - After LLM calls, apply schema validation (Pydantic).
    - Compute confidence bucketing per heading:
      - `≥0.85` → applied to tree.
      - `[0.5, 0.85)` → applied to tree **only** if no SME override
        exists; row goes into `knowledge_outline_review_item` for
        confirmation.
      - `<0.5` → default `label=noise` (dropped from tree); row goes
        into review queue for possible SME rescue.
    - Adopt SME overrides: on rebuild, `sme_override_label` beats
      `llm_label` regardless of confidence.
    - Set `AIGovernanceRun.adoption_status`:
      - `auto_adopted` if ≥90% of headings are `≥0.85` and no
        `sme_override_at IS NULL` blockers.
      - `review_required` if any heading needs SME check.
      - `rejected` if schema validation fails.
    - Set `validation_status = schema_valid` / `schema_invalid`.
- Extend service layer:
  - `service.build_and_persist_outline` dispatches to LLM v2 when a
    caller-supplied `strategy="llm_v2"` (or when
    `task_outline_profile.textbook_subtype == "theory_knowledge"` and a
    feature flag is on).
  - Rules-based v0 remains available for `strategy="rules"` (backward
    compat + non-textbook fallback).
- Persistence rules:
  - `knowledge_outline_node.metadata` carries
    `{"ai_run_id", "heading_block_id", "llm_label", "llm_confidence",
  "sme_override_by"}`.
  - `KNOWLEDGE_OUTLINE_BUILT` audit summary carries `ai_run_id`,
    `prompt_profile_id`, `prompt_version`, `model_alias`, `input_hash`,
    `label_distribution`, `sme_override_count`.

### API (nexus-api)

- New router `api/internal/knowledge_outline_review.py`:
  - `GET /internal/v1/normalized-refs/{ref_id}/knowledge-outline-reviews`
    — cursor-paginated list of pending review items.
  - `POST /internal/v1/knowledge-outline-reviews/{item_id}/override`
    body `{ "label": <string>, "reason": <string> }`.
  - `POST /internal/v1/knowledge-outline-reviews/{item_id}/approve`
    accepts current LLM label (no change).
  - `GET /internal/v1/knowledge-outline-reviews/{item_id}` — detail.
- Feed override results into the next rebuild via
  `knowledge_outline_review_item.sme_override_label`.

### Frontend (nexus-console)

- New section on the AssetDetailTabs → "知识块" → "知识点大纲" tab:
  - Small badge showing pending-review count.
  - Modal or drawer listing review items with per-item label dropdown
    - approve button.
- New Next.js proxy routes for the four review endpoints.
- Reuse existing `KnowledgeOutlineView`.

### Tests

- Backend:
  - `test_llm_classifier_v2_prompt_profile.py` — resolves active
    profile, no hard-coded prompt.
  - `test_llm_classifier_v2_ai_run.py` — one run per rebuild, correct
    validation + adoption status per confidence mix.
  - `test_llm_classifier_v2_v1_fixes.py` — root title fallback,
    adjacent chapter merge, chunk-100% backfill.
  - `test_review_item_lifecycle.py` — create / override / approve.
- API:
  - `test_knowledge_outline_review_api.py` — GET list / POST override /
    approve; 404 when item missing; permission inheritance.
- Frontend:
  - Vitest spec extending existing `KnowledgeOutlineView.test.tsx`
    with review badge + override modal.

## Out Of Scope

- Full SME edit UX (inline heading label editing on the outline nodes).
  v2.5 scope.
- Diff view between rebuilds. v3 scope.
- Automatic prompt A/B regression testing. v3 scope.
- Cross-book concept alignment (still P3 as per prior task package).
- LLM streaming / partial results.
- Real-time collaboration on review queue.

## Forbidden Changes

- Do not hard-code the classifier prompt in code; must come from
  `AIPromptProfile`.
- Do not send L3/L4 chunk text to the LLM; only heading text + short
  paragraph excerpts (existing behavior).
- Do not silently drop a review item; every low-mid confidence must
  either land in the queue or be explicitly SME-approved.
- Do not delete `ai_governance_run` rows on rebuild replacement; keep
  full audit history.
- Do not overwrite an SME override on rebuild — override always wins
  until the SME explicitly rescinds it.
- Do not persist raw LLM responses containing chunk plaintext to logs.

## Deliverables

### Backend

- `nexus-app/alembic/versions/YYYYMMDD_NNNN_knowledge_outline_review_item.py`
- `nexus-app/nexus_app/models.py` — new `KnowledgeOutlineReviewItem` class
- `nexus-app/nexus_app/enums.py` — 2 new audit event types
- `nexus-app/nexus_app/ai_governance/seed_data.py` — new profile seed
- `nexus-app/nexus_app/knowledge_outline/schemas.py` — Pydantic v2 shapes
- `nexus-app/nexus_app/knowledge_outline/llm_classifier.py` — refactor to
  use profile + ai_run
- `nexus-app/nexus_app/knowledge_outline/service.py` — strategy dispatch
- `nexus-app/nexus_app/knowledge_outline/review_service.py` — new module
- `nexus-app/scripts/rebuild_knowledge_outline_llm_v1.py` — retain, mark
  v1; add `--strategy=v2` variant

### API

- `nexus-api/nexus_api/api/internal/knowledge_outline_review.py`
- Register in `internal/__init__.py`

### Frontend

- `nexus-console/lib/api.ts` — new review types
- `nexus-console/app/api/normalized-refs/[refId]/knowledge-outline-reviews/route.ts`
- `nexus-console/app/api/knowledge-outline-reviews/[itemId]/override/route.ts`
- `nexus-console/app/api/knowledge-outline-reviews/[itemId]/approve/route.ts`
- `nexus-console/app/api/knowledge-outline-reviews/[itemId]/route.ts`
- `nexus-console/app/assets/[assetId]/_components/KnowledgeOutlineView.tsx` —
  review-badge integration

### Tests

- 5 backend + 1 API + 1 frontend spec (listed above)

## Acceptance

- A `theory_knowledge` ref rebuild dispatches to the LLM v2 path when the
  feature flag is on; runs against the active `AIPromptProfile` for
  `task_type="knowledge_outline_heading_classification"` without hard-
  coded prompt text.
- Exactly one `AIGovernanceRun` row is created per rebuild; its
  `ai_output` contains the per-heading classifications; `input_hash` is
  reproducible for the same block set.
- Confidence bucketing:
  - Headings with `confidence ≥ 0.85` land in the tree without review.
  - Headings in `[0.5, 0.85)` land in the tree AND get a
    `knowledge_outline_review_item` for SME approval.
  - Headings with `confidence < 0.5` do NOT land in the tree; a review
    item is still created so SME can rescue them.
- SME override via `POST /override` persists; next rebuild uses
  `sme_override_label` regardless of new LLM confidence.
- v1 fix acceptance:
  - Book 1 root title = "短视频拍摄与剪辑" (not the series name).
  - `[50] 项目一` and `[51] 短视频认知` merge into one chapter
    "项目一 短视频认知".
  - Chunk backfill coverage ≥ 99% (was 86.5% in v1).
- Audit events `KNOWLEDGE_OUTLINE_BUILT` carry `ai_run_id`,
  `prompt_profile_id`, `prompt_version`, `sme_override_count`.
- No plaintext content in `raw_output` logs beyond heading titles + <150
  char paragraph excerpts.
- Both golden textbooks rebuild successfully end-to-end; results match
  the expected node counts (±5%): book 1 = ~77 nodes, book 2 = ~212
  nodes.
- `git grep "SYSTEM_PROMPT"` in `nexus_app/knowledge_outline` returns
  zero matches (prompt moved to DB).
- `pytest nexus-app nexus-api` and console `typecheck` all pass.

## Review Gate

- **DDL Review**: FK cascade on review_item → normalized_ref;
  `ON DELETE CASCADE` from ref, `ON DELETE SET NULL` from ai_run.
- **Prompt Seed Review**: seed uses `INSERT ... ON CONFLICT DO NOTHING`
  so re-seeding does not duplicate the row.
- **AI Governance Contract Compliance**: verify no plaintext leaks; no
  raw governance rule bypass; adoption gate is deterministic.
- **Review UX**: PR includes a screenshot of the review drawer + one
  SME override end-to-end.
- **Feature Flag Retirement**: default v2 to `off` for existing refs on
  first ship; flip to `on` after one week of golden book validation.

## Open Follow-ups (v3+)

- Inline SME editing on outline nodes (drag / relabel).
- Diff view between rebuilds (added / removed / relabeled nodes).
- Automatic prompt A/B regression testing (compare label distribution
  across prompt versions).
- Cross-book concept alignment.
- LLM streaming so long rebuilds show progress in the console.
