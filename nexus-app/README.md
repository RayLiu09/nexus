# nexus-app

NEXUS core application package. This module owns domain configuration, database models, migrations, and reusable application services.

## Week 1 Ownership

`nexus-app` owns:

- environment configuration loading from root `.env.dev` style variables;
- SQLAlchemy database engine/session setup;
- Week 1 master data models and Alembic migration;
- domain enums and Pydantic DTOs;
- CRUD/application services for local identity, API callers, data sources, ingest batches, and raw objects;
- middleware environment configuration inspection utilities.

`nexus-api` owns only the externally consumed FastAPI service layer and calls into `nexus-app`.

## Test

```bash
cd nexus-app
pytest
```

## Environment Check

```bash
cd nexus-app
python -m nexus_app.scripts.check_env --env-file ../.env.dev
```

The environment checker redacts secret values and performs only non-destructive socket/HTTP checks.
