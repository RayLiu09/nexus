import {
  type ApiCaller,
  type AIGovernanceRun,
  type AuditLog,
  type DataSource,
  type DocumentAsset,
  type IngestBatch,
  type Job,
  type NormalizedAssetRef,
  type OrgUnit,
  type ParseArtifact,
  type RawObject,
  type RuntimeState,
  type UserAccount,
  getApiData
} from "@/lib/api";

export async function loadWorkbenchData() {
  const [
    runtime,
    dataSources,
    batches,
    rawObjects,
    jobs,
    assets,
    normalizedRefs,
    audits,
    governanceRuns
  ] = await Promise.all([
    getApiData<RuntimeState | null>("/v1/runtime/state", null),
    getApiData<DataSource[]>("/v1/data-sources", []),
    getApiData<IngestBatch[]>("/v1/ingest/batches", []),
    getApiData<RawObject[]>("/v1/raw-objects", []),
    getApiData<Job[]>("/v1/jobs", []),
    getApiData<DocumentAsset[]>("/v1/assets", []),
    getApiData<NormalizedAssetRef[]>("/v1/normalized-refs", []),
    getApiData<AuditLog[]>("/v1/audit-logs", []),
    getApiData<AIGovernanceRun[]>("/v1/ai/governance-runs", [])
  ]);

  return {
    runtime,
    dataSources,
    batches,
    rawObjects,
    jobs,
    assets,
    normalizedRefs,
    audits,
    governanceRuns,
    ok: [
      runtime,
      dataSources,
      batches,
      rawObjects,
      jobs,
      assets,
      normalizedRefs,
      audits,
      governanceRuns
    ].every((item) => item.ok),
    error:
      [
        runtime,
        dataSources,
        batches,
        rawObjects,
        jobs,
        assets,
        normalizedRefs,
        audits,
        governanceRuns
      ].find((item) => item.error)?.error ?? null,
    traceId: runtime.traceId ?? dataSources.traceId ?? batches.traceId ?? null
  };
}

export async function loadIdentityData() {
  const [orgUnits, users, apiCallers, audits] = await Promise.all([
    getApiData<OrgUnit[]>("/v1/org-units", []),
    getApiData<UserAccount[]>("/v1/users", []),
    getApiData<ApiCaller[]>("/v1/api-callers", []),
    getApiData<AuditLog[]>("/v1/audit-logs", [])
  ]);
  return { orgUnits, users, apiCallers, audits };
}

export async function loadWeek2Lists() {
  const [dataSources, batches, rawObjects, jobs, parseArtifacts, normalizedRefs, assets] =
    await Promise.all([
      getApiData<DataSource[]>("/v1/data-sources", []),
      getApiData<IngestBatch[]>("/v1/ingest/batches", []),
      getApiData<RawObject[]>("/v1/raw-objects", []),
      getApiData<Job[]>("/v1/jobs", []),
      getApiData<ParseArtifact[]>("/v1/parse-artifacts", []),
      getApiData<NormalizedAssetRef[]>("/v1/normalized-refs", []),
      getApiData<DocumentAsset[]>("/v1/assets", [])
    ]);

  return { dataSources, batches, rawObjects, jobs, parseArtifacts, normalizedRefs, assets };
}
