# Task Package: Hide Course Standard Asset Center Entry

## Source Context

- `AGENTS.md` and `WORKFLOWS.md`: keep Console changes bounded and verify the page flow.
- Prototype v2.2 section 4.1A: Asset Center resource links and preserved routes.
- User request: hide the "课程标准" entry in the Asset Center.

## Goal

Remove the course-standard link and static card description from the Asset Center overview.

## Scope

- Asset Center overview visibility and card copy, focused component and E2E assertions,
  and page documentation.

## Out Of Scope

- Resource registry, direct route, counts API, classification, permissions, and stored assets.

## Forbidden Changes

- Do not change backend services, governance behavior, or resource routes.

## Acceptance

- The overview has no "课程标准" link or static description and retains "课程教材" and "教学案例".
- Existing visible links and counts retain their behavior.
- Focused component test and Console typecheck pass.
- Frontend UX Review Gate: confirm overview links and responsive layout against Prototype v2.2.
