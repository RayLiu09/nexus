# Task Package: Asset Center Raw Jobs Excel Export

## Source Context

- Asset Center job-demand list reads crawler intake `raw_jobs`, not the retired Pipeline B projection.
- `SPEC.md` and Prototype v2.2 define the nine business columns in this list.

## Goal

Let users download all matching job-demand records as an Excel workbook.

## Scope

- Add a read-only internal XLSX export endpoint for `raw_jobs` with the list's keyword and industry filters.
- Expose the binary response through a Console-internal authenticated route.
- Add a list command with progress and error feedback.
- Test full-result export, columns, filtering, and spreadsheet formula handling.

## Out Of Scope

- Mutations, background export jobs, or changes to the raw job ingest model.

## Forbidden Changes

- Do not route the list or export through Pipeline B job-demand projections.
- Do not expose the Console proxy as an external business API.

## Acceptance

- Export includes all matching rows regardless of list pagination.
- Excel columns match the nine business columns shown in Asset Center.
- Untrusted cell text is written as data, not an executable formula.
