# nexus-api

NEXUS externally consumed business API service.

## Week 1 Scope

- FastAPI app under `/v1`.
- Health and runtime state.
- Local org units, users, API callers, data sources through `nexus-app`.
- Ingest batch and raw object ledger metadata through `nexus-app`.
- Structured request logging with `trace_id`.
- Stable success and error envelopes.

`nexus-api` does not own domain models, migrations, or core processing logic. Those belong to `nexus-app`.

No enterprise IAM, DingTalk runtime dependency, self-developed AI gateway, MinerU, LiteLLM, RAGFlow, or full job orchestration is implemented in Week 1.

## Run

```bash
cd nexus-api
uv run uvicorn nexus_api.main:app --reload
```

Without `uv`, use an environment that already has the dependencies installed:

```bash
cd nexus-api
python -m uvicorn nexus_api.main:app --reload
```

## Test

```bash
cd nexus-api
pytest
```

The test suite uses SQLite in-memory storage. Runtime defaults are loaded by `nexus-app` from the root `.env.dev` style variables and can be overridden with `NEXUS_DATABASE_URL`.
