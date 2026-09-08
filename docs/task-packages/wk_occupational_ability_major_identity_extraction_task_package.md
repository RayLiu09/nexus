# Task Package: Occupational Ability Major Identity Extraction

## Status

Complete.

## Source Context

- `AGENTS.md`: Pipeline B governance and domain projection must consume the
  normalized-record contract; raw workbook data must not be reopened after
  structured parsing.
- `WORKFLOWS.md`: non-trivial parsing changes require a bounded task package,
  focused tests, and contract review evidence.
- `SPEC.md`: occupational ability analysis is a professional-data business
  view whose professional identity must be available to list and graph
  consumers.
- Existing `ability_analysis.pgsd.v1` contract: the domain writer persists
  `record_body.analysis.major_name` into `occupational_ability_analysis`.

## Goal

Populate the professional name while projecting a parsed PGSD occupational
ability workbook so the domain row and Asset Center list retain the source's
professional identity.

## Frozen Extraction Contract

- An explicit non-empty `profile.evidence.major_name` remains the highest
  priority source.
- When that field is absent, derive the name conservatively from
  `ParsedWorkbook.source_filename` only when the filename carries the
  occupational-ability-analysis suffix.
- Remove file extensions, bounded sequence/category wrappers, the analysis
  type suffix, and the immediately preceding `专业` marker; retain the actual
  professional name.
- Use the shared professional-name normalizer for suffix normalization.
- Do not infer from task names, PGSD ability text, `major_profile`, or an
  unrelated asset.
- If neither source provides evidence, leave `major_name` absent rather than
  inventing a value.

## Scope

- `nexus-app/nexus_app/structured_parse/record_body_adapter.py`
- `nexus-app/nexus_app/profile_detect/detector.py`
- `nexus-app/nexus_app/capability_graph/major_normalizer.py`
- Focused tests for profile evidence, record-body projection, writer
  persistence, and idempotent rebuild behavior.
- Backfill the existing development occupational-ability domain row after
  tests pass, then verify the internal business list without creating a
  duplicate asset version.

## Out Of Scope

- Database migrations or new columns.
- Frontend fallback logic or API response changes.
- Changes to classification, governance thresholds, lifecycle, graph facts,
  or other professional domain projections.
- Mobile adaptation or broad Markdown formatting.

## Forbidden Changes

- Do not read raw workbook bytes in domain normalization or governance.
- Do not use `major_profile` as an identity source.
- Do not overwrite explicit structured professional identity with a filename.
- Do not modify unrelated user files or reformat existing Markdown documents.

## Deliverables

- Deterministic occupational-ability filename identity extraction in the
  profile evidence and normalized-record projection.
- Regression tests for explicit precedence, suffix cleanup, missing evidence,
  and idempotent domain reconstruction.
- Real-data rebuild evidence showing the Asset Center list has a professional
  name and retains its existing statistics.

## Acceptance

- `电子商务职业能力分析表.xlsx` projects `major_name=电子商务`.
- `电子商务专业职业能力分析表.xlsx` projects `major_name=电子商务`.
- A numbered/category-prefixed filename such as
  `2.（职业能力分析）大数据技术应用专业职业能力分析表.xlsx` projects
  `major_name=大数据技术应用`.
- Explicit `profile.evidence.major_name` takes precedence over the filename.
- A generic filename does not produce a professional name.
- Rebuilding the same normalized reference remains idempotent and preserves
  the derived name.

## Review Gates

- **Data Contract Review**: extraction is deterministic, evidence-bound, and
  leaves the existing normalized-record/API schemas unchanged.
- **Acceptance Gate**: focused tests and the rebuilt development record agree
  on the extracted professional name and unchanged PGSD counts.

## Verification Evidence

- Data Contract Review: Profile detection and normalized-record projection
  both retain the evidence-bound professional name. The change introduces no
  schema, API, lifecycle, classification-confidence, or raw-input changes.
- Focused application tests: 161 tests pass across profile detection, shared
  name normalization, record-body projection, domain writer behavior, and the
  Pipeline B profile-detection integration path.
- API surface: no request/response code changed; the authenticated running
  internal list endpoint was verified against the corrected development row.
- Development backfill: the one existing analysis row was updated in place
  with an `AbilityAnalysisPersisted` audit event; no duplicate asset version or
  analysis row was created.
- Authenticated internal-list verification: one row is returned with
  `major_name=大数据技术应用`, `task_count=4`, and G/D/P/S counts
  `15/12/69/17`.
- `compileall`, service health, and `git diff --check` pass. Ruff was not
  available in the project virtual environment.
