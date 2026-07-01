# Task Package: Evidence-grounded KG Console View

## Source Context

- `docs/evidence_grounded_kg_implementation_plan.md`: Task Package F requires the asset detail knowledge tab to expose `RAG知识块` and `Evidence Graph`, with graph canvas, details drawer, evidence source-location, empty/build states, fullscreen, and full graph image download.
- `nexus-api/nexus_api/api/internal/evidence_graph.py`: previous slice exposes internal build/query APIs.
- `nexus-console/app/assets/[assetId]/_components/CapabilityGraphView.tsx`: existing ECharts, fullscreen, and full graph download interaction pattern.
- `nexus-console/components/chunk/ChunkPreviewDrawer.tsx`: existing locator-based source preview drawer.

## Goal

Add a Console Evidence Graph view for document assets so operators can switch from RAG chunks to an evidence-grounded graph, inspect nodes/edges/facts, and open cited chunks with locator-based source preview.

## Scope

- `nexus-console/lib/api.ts`: Evidence Graph DTO types.
- `nexus-console/app/api/evidence-graphs/**`: internal API proxy routes.
- `nexus-console/app/assets/[assetId]/_components/DocumentKnowledgeView.tsx`: document knowledge two-view dispatcher.
- `nexus-console/app/assets/[assetId]/_components/EvidenceGraphView.tsx`: Evidence Graph canvas, details drawer, evidence list, build state, fullscreen, and image download.
- `nexus-console/components/AssetDetailTabs.tsx`: route document assets to the new two-view knowledge component.
- `docs/evidence_grounded_kg_implementation_plan.md`: mark Task Package F as started.

## Out Of Scope

- Public/open Evidence Graph API.
- Running LLM extraction from the browser or route handler.
- Background worker orchestration for full graph builds.
- Changes to Pipeline B capability graph staging.

## Forbidden Changes

- Do not call `/internal/v1/*` directly from client components.
- Do not expose backend base URLs or JWTs to the browser.
- Do not use raw files, raw JSON, or MinerU raw output as graph inputs.
- Do not couple Evidence Graph rendering to Pipeline B graph staging DTOs.

## Deliverables

- Asset detail document knowledge tab defaults to `RAG知识块`.
- `Evidence Graph` view can load latest succeeded build and graph rows.
- Empty state shows build/rebuild action that submits a build envelope.
- Clicking node, edge, or fact opens a details drawer with related evidence.
- Clicking evidence opens the existing chunk preview drawer for source locator.
- Graph supports fullscreen display and complete graph image download.

## Acceptance

- TypeScript typecheck passes for touched console files.
- Lint passes for touched console files.
- Evidence Graph API calls go through `/api/evidence-graphs/*` proxy routes.
- Missing build, empty graph rows, and failed API states render explicit states.
