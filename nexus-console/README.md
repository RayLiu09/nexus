# nexus-console

NEXUS admin console built with Next.js App Router and TypeScript.

## Week 1/2 Scope

- Global shell with sidebar navigation.
- P0 route placeholders from Prototype v2.2.
- Shared status label component aligned with `docs/contracts/p0_api_state_contract.md`.
- Live `/v1` API integration for workbench, data sources, ingest, raw ledger, jobs, assets, asset detail, and audit pages.
- v2.4 Prompt and rule placeholders use save-to-activate states instead of draft/publish/rollback lifecycle states.
- No P1 retrieval test page, no knowledge asset page, and no NEXUS AI gateway management page.

## Run

```bash
cd nexus-console
npm install
NEXUS_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

`NEXUS_API_BASE_URL` defaults to `http://127.0.0.1:8000`.

## P0 Routes

- `/login`
- `/workbench`
- `/data-sources`
- `/ingest`
- `/raw-ledger`
- `/jobs`
- `/assets`
- `/assets/[assetId]`
- `/governance`
- `/rules`
- `/iam-audit`
- `/ai-prompts`
