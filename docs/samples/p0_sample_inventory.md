# P0 Sample Inventory And Acceptance Notes

Source: `docs/task-packages/wk_1_task_package.md` TP-W1-07.

Status as of 2026-05-06: real business samples are still pending business expert review. A live-commerce textbook file under `docs/samples` has been used for a technical Week 2 end-to-end path check, but it is not yet a formally approved/desensitized business acceptance sample. The entries below remain placeholders for business-approved samples and must be replaced or attached with reviewed files or payloads before formal acceptance.

## D1-D4 Sample List

| Sample ID | Domain | Type | Candidate Content | Sensitivity | Purpose |
|-----------|--------|------|-------------------|-------------|---------|
| `S-D1-CRAWLER-001` | D1 | crawler JSON | Public program announcement payload | L1/L2 only | Structured/crawler ingest and normalized record path. |
| `S-D2-STRUCT-001` | D2 | JSON/CSV | Course or training catalog metadata | L1/L2 only | Structured record governance and tags. |
| `S-D3-DOC-001` | D3 | Office/PDF | Internal policy excerpt, desensitized | L2/L3 masked | Document parsing and rule conflict sample. |
| `S-D4-PDF-001` | D4 | PDF | Static D4 knowledge document, desensitized | L2/L3 masked | Week 2 static document ingest demo. |
| `S-D4-PDF-002` | D4 | PDF | Low-quality scanned sample, desensitized | L2/L3 masked | Quality failure and `review_required` demo. |

## Minimum Static Document Samples

1. `S-D4-PDF-001`: high-quality static PDF expected to reach `available` after parse, AI governance, quality, and rules pass.
2. `S-D4-PDF-002`: low-quality or incomplete PDF expected to trigger `review_required` due to quality admission failure.

## Minimum Crawler JSON Sample

`S-D1-CRAWLER-001` should include:

- source system;
- source URL;
- crawl time;
- external record ID;
- title;
- body or structured fields;
- checksum candidate;
- org scope hint;
- data domain hint.

No unmasked L3/L4 plain text should be included in samples used for external model calls.

## Permission Isolation Samples

| Case | Caller/User | Org Scope | Data Level | Expected Result |
|------|-------------|-----------|------------|-----------------|
| `P-ORG-DENY-001` | Caller A, User A | Org A | L2 | Cannot access Org B asset. |
| `P-L4-MASK-001` | Caller B, User B | Org B | L4 | Metadata visible only when authorized; content masked by default. |

## Governance Candidate Samples

| Case | Sample | Expected Governance Outcome |
|------|--------|-----------------------------|
| `G-AUTO-001` | `S-D4-PDF-001` | High-confidence AI and clean rules enter `available`. |
| `G-CONFLICT-001` | `S-D3-DOC-001` | AI/rule conflict enters `review_required`. |
| `G-QUALITY-001` | `S-D4-PDF-002` | Quality admission failure enters `review_required`. |

## Field Mapping Draft

| Source Field | Normalized Field | Notes |
|--------------|------------------|-------|
| `source_system` | `normalized_record.source_system` | Required for crawler batches. |
| `source_url` | `normalized_record.source_uri` | Used for citation and raw trace. |
| `title` | `normalized_document.title` or `normalized_record.title` | Required if available. |
| `body` | `normalized_document.content` or `normalized_record.content` | Redact before external model calls when L3/L4. |
| `org_hint` | governance context org scope hint | Rules may override. |
| `domain_hint` | governance context data domain hint | D1-D4 only for P0. |

## M1 Acceptance Assertions

1. Samples cover D1-D4 at inventory level.
2. At least two static document sample slots and one crawler JSON sample slot are defined.
3. Permission cases include cross-org denial and L4 masking.
4. M1 implementation can demonstrate local identity, data source, ingest batch, raw object ledger, and idempotency.
5. No sample requires enterprise IAM, DingTalk, self-built AI gateway, D5/D6 production ingest, or unmasked L3/L4 external model input.
