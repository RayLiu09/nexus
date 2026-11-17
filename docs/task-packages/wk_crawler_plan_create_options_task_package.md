# Task Package: Crawler Plan Creation Options

Date: 2026-11-17. Single-agent frontend change.

## Source And Goal

- User requests only 1年 / 2年 / 3年 for the Crawler plan time-range selector;
  existing plans must keep their saved data.
- User additionally hides quick-start creation; backend stays unchanged.
- Follow SPEC.md Crawler Console flows, Prototype v2.2, WORKFLOWS.md frontend
  review evidence, and nexus-console/AGENTS.md client-component guidance.

## Bounded Scope

- New plans default to generic configuration (`custom`) with no quick-start tab.
- Copy creates a new generic plan; an unsupported copied historical time range
  defaults to one year, while supported one/two/three-year selections persist.
- Editing existing plans preserves their mode and saved time range, including
  legacy three/six-month/five-year values unless the user changes them.
- Time-range dropdown offers only one/two/three years. Legacy current values
  still have readable labels when editing, without reintroducing dropdown items.
- No backend, API contract, migration, saved-plan rewrite or runtime changes.
- Update relevant Console component checks and narrow product documentation.

## Verification And Review

- Existing plan-edit/copy submission tests plus legacy WebSearch preservation
  verify mode/time-range compatibility and absence of automatic writes.
- Focused Vitest, TypeScript and targeted ESLint checks; diff whitespace check.
- Frontend review evidence records changed creation entry, legacy editing,
  empty/error behavior inherited from the existing form, and no backend changes.

## Verification Results And Frontend Review Evidence

- Focused `CrawlerPlansPanel.test.tsx`: **10 passed**. Covers generic-only
  creation/copy, the exact one/two/three-year dropdown, and a legacy five-year
  quick-start plan. Opening edit/copy sends no mutation; saving the existing
  plan preserves its mode and five-year range, while a new copy uses custom
  mode and one year without mutating its source.
- `npm run typecheck`: passed.
- Repository ESLint config cannot load: installed dependencies lack
  `eslint-plugin-testing-library` (the config also imports a Vitest plugin).
  No dependency/config files were changed for this task.
- Targeted ESLint using the installed Next core-web-vitals/TypeScript configs
  and the repository's existing warning severities: **0 errors, 1 existing
  set-state-in-effect warning** at the unchanged config-loading effect.
- `git diff --check`: passed.
- Existing validation/error messages, cancel/save controls and backend request
  paths remain in place. New mode defaults are explicit; historical mode/range
  values remain readable and preserved when editing. No server/data migration,
  saved-plan update, service restart or deployment was performed.
- SPEC.md, ARCHITECT.md and readme.md describe the current frontend choices and
  historical compatibility. Human merge review remains under WORKFLOWS.md.

## Commit And Push Authorization

- User explicitly requests committing and pushing the completed frontend change.
- Include only the Crawler component/tests, this task package and the three
  updated root contracts. Preserve unrelated workspace files.
