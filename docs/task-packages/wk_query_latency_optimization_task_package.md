# Task Package: Public-tool query latency optimization

Date: 2026-11-05. Status: implemented and verified; human Review Gates pending before merge. Single agent.

## Goal And Allowed Scope

Measure the 150.83-second web-enabled Chongqing question, reduce avoidable scheduling/model/context overhead, and preserve source quality and explicit web behavior. Allowed: public query runtime/executor and focused tests; query factory only if client lifetime requires it; architecture/spec/readme and latency review evidence. Preserve unrelated working changes.

## Frozen Boundaries

- Existing internal query/SSE and public tools; web switch default off and DeepSeek count=10 when enabled. Preserve explicit scope/sensitivity gates, deployment ingestion policy, credential isolation, citation identity, available/current-ref gates and initiating-user audit.
- Measure actual stage duration, time to first answer text, HTTP/model counts and bounded context size. Persist safe numeric timings in existing final query audit; no raw prompts, source content or secrets in logs.
- Optimize independent HTTP calls only with bounded per-turn concurrency; workers never receive a SQLAlchemy Session or mutate registry/event state. Owner thread serializes result registration, citations and ordered SSE events. Validate prerequisites; dependent evidence reads stay sequential. Disconnect/budget cancellation stops future scheduling and does not wait for an unbounded worker join.
- Avoid redundant evidence planning when observed document anchors can directly supply relevant content; preserve specialist graph/outline requests and fallback for other resources. Keep the full business tool catalog reachable and avoid silent active Prompt overwrite or weaker validation.
- No migration, new API surface, new infrastructure, change to model/provider routing, commit or push. Respect finite HTTP/time budgets. Do not shorten answers or reduce requested web result count solely to improve measurements.

## Verification

Capture a real pre-change instrumented query, deterministic tests for evidence-stage selection, failures, dependency ordering, scope gates, cancellation, source registration, context deduplication and timing audit (overlap tests only if concurrency is introduced), appropriate query/SSE/executor regression, then repeat the original question with web enabled and ingestion disabled. Separate actual measured improvement from model/provider variability. API/Permission-Audit/Semantic Retrieval Review Gate evidence before merge.


## Measured Implementation Choice

A fresh unchanged baseline completed in 56.54s (first answer 44.931s): planning
29.509s, composition 24.494s, web HTTP 3.480s; most other HTTP calls below 0.5s.
The historical 150.83s is an observed outlier without retained step timestamps,
not a stable baseline. This slice targets redundant evidence planning and duplicate
model input; HTTP execution remains sequential because measured HTTP overhead is
small. No concurrency, Session lifetime, connection pooling or public API changes
are needed for this slice.

## Delivery Evidence

See [review and measured results](../review/query_latency_optimization_review.md).
Backend regression: 139 passed. Ordinary document queries use two planner calls;
specialist/fallback paths remain covered. Optimized live runs took 44.83s and
58.61s versus a fresh 56.54s baseline, so no stable percentage gain is claimed.
