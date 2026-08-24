# Task Package: Crawler Low-Value Activity News Gate

## Source Context

- `AGENTS.md`: governed inputs require usable normalized evidence; raw
  evidence is retained when a crawler candidate is rejected.
- `ARCHITECT.md`: crawler results enter Pipeline A only after quality
  admission; governance does not own search-result relevance ranking.
- `WORKFLOWS.md`: quality-gate changes require focused regression tests and
  auditable historical remediation.

## Goal

Keep crawler activity/news recaps that have no reusable policy, report, or
statistical evidence from becoming governed knowledge assets.

## Scope

- Treat multiple event-recap signals (for example opening a training class,
  signing/unveiling, co-hosting, participant counts, completion certificates)
  as low-value crawler content when no formal policy/report/statistical
  evidence exists.
- Reject explicitly framed human-interest/person-profile news when it has no
  formal policy/report/statistical evidence.
- Do not treat a generic domain word such as `产业` as report evidence.
- Add regression coverage for the identified training-event pattern and a
  statistical-report exception.
- Remediate assets `227e8073-a23b-4319-96fc-ecbfb8e7721c`,
  `98fe937c-cf51-4893-a4fa-1dd706f95e3b`, and
  `3cf5b83f-1952-4110-a20a-52bc693e3f14` to failed crawler-noise states while
  retaining raw evidence and audit records.

## Out Of Scope

- Search query expansion, local topic matching, LLM relevance scoring, or
  deletion of raw objects.

## Acceptance

- A training event recap is rejected as `low_value_activity` before
  assetization.
- A document with reusable statistical/report evidence remains admissible.
- The identified historical asset is no longer eligible for governance, RAG,
  or index processing and has a traceable failure reason.
