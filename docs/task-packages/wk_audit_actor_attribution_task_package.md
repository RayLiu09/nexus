# Audit actor attribution task package

Display-only revision: the latest user instruction replaces uniform `system`
presentation with actual recorded executor IDs; see
`wk_audit_actor_display_task_package.md`. Write attribution remains as below.

## Source and goal

User request: analyze and correct missing actors on automated audit events.
Follow `ARCHITECT.md` Audit Event Contract, `SPEC.md` audit traceability and
`WORKFLOWS.md` Permission/Audit Review Gate. Record the actual executor without
mistaking an unknown human operation for a system operation.

## Scope and frozen contract

- Add a scoped audit identity at automated execution boundaries: pipeline
  execution, worker bootstrap/recovery, crawler scheduler and data-sync runtime.
- `actor_type=system`; `actor_id` identifies the worker/component. Nested writes
  inherit this identity only when no explicit identity was supplied. Explicit
  user/API identities take precedence; incompatible partial identities are not
  merged. Context must reset after errors and remain isolated across workers.
- Preserve manual crawler identities through both connector branches and their
  nested ingest writes. Display actual `system_repair` executor IDs in the
  audit read model under the latest display contract.
- Preserve API schemas, audit event names, trace IDs, redaction, transactions,
  job states, retries, permission rules and pipeline contracts.
- Historical rows remain unchanged; missing historical attribution is not
  fabricated. No automatic execution of jobs against the development database.

## Exclusions and forbidden changes

No schema/migration, bulk history rewrite, unrelated permission repair, IAM,
gateway, queue system, arbitrary execution, governance bypass, reverse pointers
or P1/P2 product features. Preserve all unrelated worktree changes.

## Deliverables and acceptance

Code, scoped identity isolation/precedence tests, real pipeline/scheduler/runtime
regression evidence and updated architecture/requirements/readme. Verify
successful and failed worker paths, lease recovery, scheduler nested writes,
manual crawler identity, unknown unauthenticated events and redaction.
Permission/Audit contract self-review and test evidence are recorded below;
human Review Gate remains required before merge under `WORKFLOWS.md`.

## Verification

- App regressions (isolated SQLite): **107 passed, 1 skipped**. Command from
  `nexus-app`:

  ```sh
  .venv/bin/python -m pytest tests/test_audit_actor.py tests/test_job_payload_schema_version.py tests/test_worker_lease_lifecycle.py tests/test_crawler_scheduler.py tests/test_crawler_websearch_custom_client.py tests/test_crawler_deepseek_search.py tests/data_sync/test_runtime.py tests/data_sync/test_runs.py tests/governance/test_audit_sanitizer.py tests/test_structured_parse_worker.py tests/test_ingest_validate_stage.py -q -o addopts=
  ```

- API regressions (isolated SQLite, outside the sandbox because TestClient's
  AnyIO portal stalls inside it): **59 passed**. Command from `nexus-api`:

  ```sh
  .venv/bin/python -m pytest tests/test_crawler_plan_api.py tests/test_data_sync_run_controls_api.py tests/test_audit_log_list.py -q -o addopts=
  ```

- Coverage: nested/exception/thread/task isolation; explicit user/API identity
  precedence; unknown login/refresh failures; redaction; a real successful XLSX
  pipeline; unsupported payload rejection; bootstrap failure/dead letter versus
  retry behavior; expired worker leases; crawler schedule start/skip; actual
  Firecrawl and WebSearch nested ingest; sync schedule/claim/completion/recovery;
  manual sync control attribution; `system_repair` read presentation.
- Broader `tests/test_profile_detect_worker.py` found **4 failures, 7 passes,
  1 skip**. Re-executing that suite with the original `HEAD` runner loaded in
  memory reproduced the same four failures: job-demand fixtures fall back to
  generic tables, and the corresponding review assertions do not match.
  No profile-detection code/config or unrelated tests were changed.
- `git diff --check` passes for this task's tracked changes.
- Local preview API restarted with Worker, crawler scheduler and data-sync
  runtime disabled as before. `/v1/health` returns HTTP 200/status `ok`;
  `http://127.0.0.1:3000/iam-audit` redirects an unauthenticated visitor to login
  (HTTP 307), preserving its authentication boundary. No development jobs or
  historical audit updates were executed for verification.

## Permission/Audit contract self-review

- Identity comes from a trusted executor or authenticated dependency, never
  from payload fields or an event-name heuristic. Manual crawler operations
  retain existing authentication and pass the current user's ID.
- Automatic stage writes record the system executor; the user's initiating
  operation remains a separate event. Explicit actors win over inherited ones.
- Capturing worker identity precedes lease release. Recovery identifies the
  recovery component rather than attributing it to the expired worker.
- API schemas, event names, stored timestamps/targets, redaction, transaction
  boundaries, retry/state behavior and audit read authorization are preserved.
- No migration or historical audit mutation. Unknown historical or
  unauthenticated identities remain unknown. New standalone automatic entry
  points must bind their own scope; ContextVar does not copy to new threads.
- Implementation/test evidence is ready for human Permission/Audit review;
  this task does not merge or publish changes.
