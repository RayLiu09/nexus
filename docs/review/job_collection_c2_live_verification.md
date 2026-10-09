# Job Collection C2 Live Verification

Date: 2026-10-08. Upstream: `http://10.100.11.51:8080`, OpenAPI `0.2.0`. Source: `zhaopin`. Query: keyword `数据化运营助理`, region `杭州市`, `pageLimit=10`, `collectionMode=full`. External Job ID: `0408249e-d22b-41ec-82b2-8b216e27e049`.

This report contains no tenant key, access token, source URL, company name, or job-description text. The Job was submitted directly to crawler-api for protocol verification; no NEXUS sync plan, run, or raw-record sink was created.

## Observed Results

| Check | Result |
| --- | --- |
| Readiness and OpenAPI | HTTP 200; declared API version `0.2.0`. |
| Token exchange | HTTP 200; Bearer, `expiresIn=3600`, scopes `collection:write`, `collection:read`, `collection:control`. Invalid key: 401. Malformed auth body: 422. |
| Submit | HTTP 202; Job initially `queued`. Identical submit replay: 202 with the same Job ID. Same identifiers with changed pageLimit: 409. pageLimit 31: 422. |
| Status | `queued -> running -> pausing -> paused -> queued -> running -> succeeded`; final `processedCount=49`, one succeeded Task, no final failure codes. |
| Pause | HTTP 200 returned `status=pausing`, `desiredState=paused`; subsequent status read reached `paused` about 10 seconds later. |
| Resume | HTTP 200 returned `status=queued`, `desiredState=running`; collection then resumed. |
| Terminal cancel | HTTP 409: terminal Job rejects control transition. Active cancellation was intentionally not performed on the only requested Job. |
| Transient failure | One `agent_runtime_error` appeared with the Task requeued and zero processed records; the Agent retried and the Job ultimately succeeded. Public Job events exposed acceptance and control events, not Task error detail. |
| Early records read | During `running` with `processedCount=0`, HTTP 200 returned zero items and `nextCursor=null`. A null cursor alone cannot establish completion. |
| Final records read | Five API pages at limit 10: 10 + 10 + 10 + 10 + 9 = 49 records; final cursor null. A limit 200 read returned all 49. Replaying the final page's input cursor returned the same nine record IDs and null next cursor. |
| Record identity and scope | 49 unique `recordId` values; one `taskId`; all records had source `zhaopin`, requested keyword/region, required IDs, source URL, title, and valid SHA-256 payload hash. Source page numbers covered 1 through 10. |
| Optional content | 2/49 records lacked nonempty full description; 15/49 lacked nonempty `jobResponsibilitiesText`. Preserve these as source facts and quality markers. |
| Pagination errors | `limit=201`: HTTP 422; invalid opaque cursor: HTTP 400. |

Source-page record counts were 20, 7, 1, 1, 2, 5, 4, 2, 3, and 4 for pages 1-10. These are upstream crawl page numbers, distinct from the five NEXUS read API pages.

## Contract Consequences

1. Token exchange uses `tenantKey` only and camelCase response fields. The first issued token later received 401; an immediate probe with a newly issued token succeeded, and that token worked for all remaining calls. The cause of the first rejection was not established. Adapter tests must cover one 401 refresh and must not assume a 200 token issue guarantees every subsequent request succeeds.
2. A successful synchronous pause HTTP response means the request was accepted. It does not mean the external Job is already paused. Keep external status and desired state distinct; update NEXUS stable run state only after a confirming status read. This changes the earlier NEXUS control-state assumption and needs API Contract Review Gate approval before live controls are enabled.
3. The runtime must poll for upstream terminal state before treating an empty page with null cursor as complete. On `succeeded` or `partially_succeeded`, drain records through a durable result receiver before marking the NEXUS run terminal.
4. A 10-page upstream query produced 49 records, not an assumed fixed number per page. Record receiver validation must allow nullable content fields and preserve the upstream `jobResponsibilitiesText`/`jobRequirementsText` names or apply an explicit versioned mapping.
5. Submit retry with an existing Job ID is safe. If a submit times out before NEXUS receives that ID, the upstream API has no documented lookup by `externalRequestId`; a 409 without a returned Job ID may require upstream lookup support to recover automatically.

## Not Exercised

- Insufficient-scope 403 and `awaiting_human` behavior: the issued token had all three scopes and this Job did not require human intervention.
- Active cancel behavior: cancelling the only requested Job would have prevented verification of all 10 source pages.
- Provider adapter, NEXUS result persistence, restart recovery, and Console behavior: these belong to later implementation task packages.

API Contract and Permission/Audit Review Gates remain pending human review.
