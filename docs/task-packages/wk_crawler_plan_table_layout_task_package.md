# Crawler Plan Table Layout

## Source Context

- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`: Crawler plans are managed in the data management console.
- `WORKFLOWS.md`: P0 console layout changes require Frontend UX review.

## Goal

Keep the crawler plan table stable when page size changes to 50 or 100 and long plan names enter the visible rows.

## Scope

- Fix the plan table column widths and truncate long plan names with a full-name tooltip.
- Add a focused component regression test and verify type checking.

## Out Of Scope

- API pagination behavior, crawler execution, run history, and data model changes.

## Acceptance

- The plan table uses a stable horizontal width at 20, 50, and 100 rows per page.
- Long plan names stay within their column and remain readable through a tooltip.
- Existing page-size requests and actions still work.

## Review Gate

- Frontend UX: no clipped controls or overlapping cells on narrow and desktop widths.
