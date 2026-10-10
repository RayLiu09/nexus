# Task Package: Hide Inactive Asset Center Entries

## Source Context

- `AGENTS.md` and `WORKFLOWS.md`: keep Console changes bounded and verify the page flow.
- Prototype v2.2 section 4.1A: Asset Center domain cards and resource links.
- User request: hide the user behavior card and the certificate data entry.

## Goal

Show only the currently requested Asset Center cards and resource links.

## Scope

- Asset Center overview presentation, page heading, focused tests, and prototype note.
- Hide the user behavior domain card and the certificate resource link on the overview.
- Arrange the four visible cards in two columns on wider screens.

## Out Of Scope

- Domain registry entries and routes, direct resource routes, counts API, governance classifications,
  permissions, and asset data.

## Forbidden Changes

- Do not introduce new backend services, APIs, or governance behavior.

## Acceptance

- The overview shows four domain cards and no certificate resource link.
- Existing visible links and counts retain their behavior.
- Focused component test and Console typecheck pass.
- Frontend UX Review Gate: verify the updated page against Prototype v2.2 and
  confirm responsive layout and navigation remain usable.
