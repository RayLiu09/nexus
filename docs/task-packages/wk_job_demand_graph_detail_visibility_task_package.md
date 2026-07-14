# Task Package: Job Demand Graph and Record Detail Visibility

## Task name

Correct Pipeline B job-demand graph projection and record-asset detail tabs.

## Source context

- `nexus_app.capability_graph.builders.build_job_demand`: the authoritative
  graph is deterministically materialized from `job_demand_record` and its
  `job_demand_requirement_item` children. It makes no LiteLLM call.
- `nexus_app.worker.runner._run_capability_graph_staging`: graph staging is a
  non-blocking derived view; an unavailable requirement extractor must not
  prevent the parent-record graph from being built.
- `AGENTS.md`: Pipeline B is a normalized-record workflow; raw/document
  preview behavior must not be presented as a document experience.

## Goal

Open the Evidence Graph entry for graph-admitted document assets, retain the
B8 `job_demand` CapabilityGraphStaging projection, render one selected role's
staging subgraph at a time, and remove the document-only "原文预览" tab from
Pipeline B asset details.

## Scope

- `nexus-console/app/assets/[assetId]/_components/DocumentKnowledgeView.tsx`
- `nexus-console/app/assets/[assetId]/_components/JobDemandKnowledgeView.tsx`
- `nexus-console/app/assets/[assetId]/_components/JobDemandGraphView.tsx`
- `nexus-console/components/AssetDetailTabs.tsx`
- `nexus-app/nexus_app/worker/runner.py`
- `nexus-api/nexus_api/api/open.py` and Console route proxy
- focused tests and this task package.

## Out of scope

- Replacing or changing the B5 requirement-item extractor.
- Calling LLM from capability graph construction.
- Changing `job_demand_record` / `job_demand_requirement_item` schema.
- Replacing the B5 requirement-item extractor or treating raw job-description
  text as an equivalent structured capability source.

## Frozen behavior

- `CapabilityGraphStaging` automatic construction runs for both
  `job_demand.v1` (`build_type=job_demand`) and
  `ability_analysis.pgsd.v1` (`build_type=ability_analysis`).
- The job-demand Console graph reads the latest generated `job_demand`
  CapabilityGraphStaging build. It does not reconstruct graph relations from
  raw record fields at read time.
- `GET /internal/v1/record-assets/job-demand-datasets/{dataset_id}/role-graph`
  returns the stable role list and one selected role's graph. Omitted
  `job_title` selects the first title in deterministic order; Console presents
  a role dropdown and never loads the full dataset graph by default.
- Evidence Graph is visible for graph-admitted document assets; task-outline
  assets that declare `evidence_graph_admission=not_recommended` remain
  excluded.
- A `normalized_type=record` asset has no `原文预览` tab. Document assets keep
  their existing preview and block-jump behavior.

## Acceptance

- The Worker creates a `job_demand` CapabilityGraphStaging build after B5.2;
  extraction unavailability must still permit a record-only build.
- Job-demand asset details render the selected role's staging subgraph with a
  dropdown; the default contains only the first role, its records, and related
  requirement nodes/edges.
- Evidence Graph can be selected for graph-admitted document assets.
- `npm run typecheck` and focused backend graph tests pass.
