# Architecture Task Package: v2.4 Async Jobs And Default Data Level

## Source Context

- `AGENTS.md`: architecture changes must update `ARCHTECT.md`, `SPEC.md`, `readme.md`, and affected contracts.
- `ARCHTECT.md`: v2.3 already changed P0 async jobs from RabbitMQ + Celery to PostgreSQL job table + Worker poller, but lacks implementation-level details and explicit single-node capacity.
- `docs/企业数据与知识资产平台技术选型和架构nexus_v2.3.md`: source architecture document to upgrade.
- `WORKFLOWS.md`: non-trivial work requires a bounded task package and Review Gate awareness.

## Goal

Produce v2.4 architecture documentation that clarifies:

- P0 async jobs use PostgreSQL job table + background Worker polling, including claim locking, retry, lease timeout, indexes, event handling, and operational limits.
- Single-node deployment has an explicit recommended concurrency envelope and scale-up triggers.
- Unless explicitly configured otherwise, all imported data sources default to L1/L2 classification levels. L3/L4 are exception levels that require explicit source configuration, rule evidence, or manual/security approval.

## Scope

- Create `docs/企业数据与知识资产平台技术选型和架构nexus_v2.4.md`.
- Archive v2.3 source architecture document.
- Update root contracts and collaboration docs affected by the new architecture baseline:
  - `ARCHTECT.md`
  - `AGENTS.md`
  - `CLAUDE.md`
  - `readme.md`
  - `SPEC.md`
  - `WORKFLOWS.md`
  - `docs/contracts/p0_api_state_contract.md`
- Update placeholder/status code constants only when they represent contract drift and do not require data migrations.

## Out Of Scope

- No runtime Worker implementation in this task.
- No database migration for job polling fields in this task unless existing schema already requires a contract-only enum adjustment.
- No RabbitMQ, Celery, or Redis implementation.
- No changes to local sample files under `docs/samples`.

## Forbidden Changes

- Do not reintroduce enterprise IAM.
- Do not develop a NEXUS `llm-gateway`.
- Do not create standalone `quality_report` or `governance_decision_log` entities.
- Do not add `document_asset.current_version_id`, `document_version.normalized_ref_id`, or governance reverse pointers.
- Do not make RabbitMQ, Celery, or Redis required P0 dependencies.
- Do not make L3/L4 the default level for imported data sources.

## Deliverables

- v2.4 architecture source document with version record and detailed async job design.
- Updated concise architecture and product contracts.
- Updated agent and workflow instructions.
- Updated status/API contract for save-to-activate Prompt and rule lifecycle.
- Verification evidence from text scans and relevant lightweight tests.

## Acceptance

- Repository contains active v2.4 architecture document and archived v2.3 document.
- `ARCHTECT.md`, `AGENTS.md`, `CLAUDE.md`, and `readme.md` refer to v2.4.
- Async job design states claim SQL semantics, lock/lease model, retry, timeout, cleanup, indexes, idempotency, and Worker concurrency.
- Single-node capacity is explicit, with both recommended baseline and upgrade triggers.
- Default data-source level is explicitly L1/L2 unless an exception is documented.
- Text scan shows no P0-required RabbitMQ/Celery/Redis wording remains in root contracts.
