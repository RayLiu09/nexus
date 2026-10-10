# Task Package: Asset Center Industry Policy View

## Goal

Provide a business list view for industry-policy assets with policy identity,
region, industry, publication date, content tags, and document actions.

## Scope

- Add a paginated `/internal/v1/industry-policies` read projection over the
  existing asset catalog, normalized reference metadata, and typed tag index.
- Add the Asset Center policy list columns and actions for RAG knowledge-block
  view and normalized original-content preview.
- Remove the generic knowledge-block tab from technical asset detail after
  moving those two document views to the policy list actions.

## Out Of Scope

- New policy persistence tables, policy editing, governance mutation, or tag
  editing.

## Acceptance

- The list includes asset name, region, industry, publication date, and content
  tags.
- Knowledge-block and original-preview actions use the existing normalized-ref
  APIs and are unavailable when no normalized reference exists.
- Asset detail no longer exposes the knowledge-block tab.
