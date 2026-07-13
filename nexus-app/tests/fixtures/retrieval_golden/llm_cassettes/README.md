# LLM Cassettes — M-C.2

One JSON file per golden case that walks the intent + planner LLM
path. The M-C.2 harness loads `<case_id>.json`, wraps the recorded
strings in a `CassetteLiteLLMClient`, and injects that client into
both `IntentRecognitionService` and `RetrievalPlannerService`. The
orchestrator's `run()` loop then executes intent → (planner) →
executors → DAG → audit end-to-end, with zero live LLM traffic.

## File schema

Two shapes are supported. Both may coexist in one file; the loader
(`tests/fixtures/retrieval_golden/__init__.py::cassette_client_kwargs`)
prefers `by_model_alias` when present.

### Sequential (M-C.2 — intent + planner only)

```jsonc
{
  "case_id": "cs_...",                 // must match GoldenQuery.llm_cassette_id
  "description": "one-sentence intent of this case",
  "intent_content": "{...json-encoded RetrievalIntent shape...}",
  "planner_content": "{...json-encoded RetrievalPlan shape...}" | null
}
```

- `intent_content` — verbatim value of `choices[0].message.content` the
  real LiteLLM call would return. Must be a JSON string (i.e. a `str`
  containing serialised JSON), NOT the parsed object.
- `planner_content` — same convention for the planner call. Set to
  `null` when the case is expected to take the direct-retrieval path
  (single unstructured domain + question_type not requiring planning),
  in which case `RetrievalOrchestrator._can_direct_retrieve()` returns
  true and the planner is skipped.

### Keyed (M-D — multi-stage Pipeline B / ingest flows)

```jsonc
{
  "case_id": "cs_pipeline_b_jd",
  "description": "xlsx job_demand ingest without _run_pipeline_without_live_llm stub",
  "by_model_alias": {
    "body-markdown": ["{...markdown body JSON...}"],
    "governance-multi": [
      "{...classification+level+tags JSON...}",
      "{...second call if re-run needed...}",
    ],
    "knowledge-type-inference": ["{...knowledge_type_code JSON...}"],
    "task-structuring": ["{...task tree JSON...}"],
    "_default": ["{...fallback for unrecorded aliases...}"],
  },
}
```

- Keys are matched against the caller's `model_alias` in this order:
  exact → longest substring match → `_default` bucket.
- The substring rule lets a cassette author key on the family name
  (`body-markdown`) even though production ships an alias with a
  version suffix (`body-markdown-v2`).
- Missing aliases with no `_default` bucket raise a `RuntimeError` at
  call time — silent under-recording surfaces as a hard failure.
- Use keyed mode when the caller order isn't stable (parallel Pipeline
  B stages, retries, or B0-B4 stages that reshuffle across schema
  versions). Use sequential mode for the retrieval intent → planner
  pair where the order is fixed.

## Editorial rules

1. **Deterministic** — real LiteLLM calls use `temperature=0.0` so the
   same prompt always yields the same output; hand-crafted responses
   must respect that too. Never introduce nonces or timestamps.
2. **Schema-valid** — the string must survive
   `RetrievalIntent.model_validate` / `RetrievalPlan.model_validate`
   without a fallback path. Test both when adding a cassette.
3. **Realistic** — write the response as the LLM would. Include
   `candidate_intents`, `confidence`, `resource_hints` where the prompt
   asks for them; skip the fields the prompt allows to omit.
4. **Small** — the file is committed to the repo. Don't paste the raw
   LLM debug dump — just the fields the caller consumes.

## Adding a new cassette

1. Craft the intent + planner JSON responses that match the target
   question. Cross-check against the prompt templates in
   `nexus_app/retrieval/prompts.py`.
2. Save to `tests/fixtures/retrieval_golden/llm_cassettes/<case_id>.json`.
3. Add a `GoldenQuery` line to `queries.jsonl` with matching
   `llm_cassette_id` and expected assertions (no `prebuilt_plan`).
4. Run `pytest tests/retrieval/test_golden_baseline.py -v -k <case_id>`.

## When to record real responses (M-C.4 pathway)

M-C.4 will add a `scripts/record_retrieval_cassettes.py` runner that
takes a `--case-id`, calls the real LiteLLM endpoint once with the
production prompts, and writes the cassette JSON. Until then, all
cassettes are hand-crafted. See runbook
`docs/runbooks/retrieval_golden_query_v1.md` for the growth roadmap.
