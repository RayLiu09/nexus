# Task Package: Finance-Commerce Professional Catalog Completion

## Status

Implementation verified; human Data Contract and API Contract Review Gates remain.

## Source Context

- User-provided code/name/level list, with one identical duplicate for `730704`.
- `AGENTS.md`: structured parsing precedes domain normalization; mutations are auditable.
- `WORKFLOWS.md`: bounded task package and Review Gates for data model and API changes.

## Goal

Provide a shared, read-only finance-commerce professional catalog and fill missing code, name, or level in professional asset parsing where identity is unambiguous.

## Scope

- Catalog helper and focused parsing entry points for occupational ability analysis, major distribution, professional introductions, teaching standards, and talent training plans.
- Persist occupational-ability `education_level` alongside its code and name; update the pending migration and internal API type.
- Tests, architecture/spec notes, and migration verification.

## Out Of Scope

- Overwriting source values or resolving contradictory source facts automatically.
- Inferring one code from a professional name shared by several levels without level evidence.
- Reclassifying assets or changing governance thresholds.

## Acceptance

- 52 unique codes with the supplied names and levels; `730704` is stored once.
- `730702` completes to `跨境电子商务` and `中职` in occupational-ability parsing and existing-row migration.
- Existing values remain unchanged; ambiguous name-only cases remain incomplete.
- Relevant parser and writer tests pass.

## Review Gates

- Data Contract: catalog values match the supplied list, and completion is evidence-bound and nullable.
- API Contract: occupational-ability `education_level` is additive on the internal list response.

## Verification Evidence

- The immutable catalog contains 52 unique code/name/level entries; the duplicate `730704` row is represented once.
- Focused application tests pass for catalog ambiguity, 13 workbook projections, major-profile metadata, talent-training plans, teaching-standard projection, major-distribution projection, and occupational-ability persistence.
- Eight internal API tests pass against local PostgreSQL after migration `20261021_0120`.
- Existing `730702` analysis row was backfilled to code `730702`, name `跨境电子商务`, and level `中职`; one `AbilityAnalysisPersisted` migration audit event exists for the row.
- Frontend TypeScript and six focused tests pass. ESLint remains unavailable because the local install lacks `eslint-plugin-testing-library`.
