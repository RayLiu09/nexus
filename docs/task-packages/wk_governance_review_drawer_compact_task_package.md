# Task Package: Compact Governance Review Drawer

## Source Context

- `SPEC.md` requires business experts to submit one final governance decision with classification, level, structured tags, quality disposition, org scope, and review reason.
- `WORKFLOWS.md` Frontend UX Gate applies to the governance review flow.

## Goal

Reduce routine reviewer input while keeping the final decision explicit and editable.

## Scope

- Collapse org scope and the requested specialized tag fields by default.
- Preserve prefilled tag values when the section is collapsed.
- Prefill quality and review reasons with the approved text, while allowing edits.
- Verify the initial drawer state and submission behavior.

## Out Of Scope

- Backend decision rules, taxonomy changes, automatic submission, or audit behavior.

## Acceptance

- Reviewer sees classification, level, topic tags, quality disposition, and two editable prefilled reasons initially.
- Org scope, region, industry, occupation, ability, major, and time tags can be expanded and edited.
- Collapsed values are still submitted, and required-field errors reveal the section.
