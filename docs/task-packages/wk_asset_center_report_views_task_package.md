# Task Package: Asset Center Report Views

## Source Context

- `ARCHITECT.md` and `SPEC.md`: normalized assets and governance remain the source of truth.
- Prototype v2.2 Asset Center IA-1: industry and sector reports have separate resource routes.

## Goal

Show industry and sector report documents in useful business lists with direct document actions.

## Scope

- Read-only catalog projections for `industry_report` and `sector_report` classifications.
- Report name, industry, publication date, content tags, knowledge-block view, and original preview.
- Remove the generic knowledge-block entry from asset detail.
- Focused API tests and frontend type/lint checks.

## Out Of Scope

- New report persistence, governance changes, editing, or search filters.

## Forbidden Changes

- Do not change normalized ref or governance ownership, status rules, or external business APIs.

## Acceptance

- Each route lists only assets with its official classification and supports pagination.
- Document actions read the row's normalized ref and are disabled without one.
- Asset detail has no knowledge-block tab.
