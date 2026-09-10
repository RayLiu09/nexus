import {
  type ApiCaller,
  type AuditLog,
  type DataSource,
  type Asset,
  type IngestBatch,
  type Job,
  type NormalizedAssetRef,
  type OrgUnit,
  type ParseArtifact,
  type RawObject,
  type RuntimeState,
  type UserAccount,
  type WorkbenchSummary,
  getApiData,
} from "@/lib/api";

export async function loadWorkbenchData() {
  const [summary, runtime, dataSources, batches, audits] = await Promise.all([
    getApiData<WorkbenchSummary | null>("/internal/v1/workbench/summary", null),
    getApiData<RuntimeState | null>("/internal/v1/runtime/state", null),
    getApiData<DataSource[]>("/internal/v1/data-sources", [], { pageSize: "200" }),
    getApiData<IngestBatch[]>("/internal/v1/ingest/batches", [], { pageSize: "20" }),
    getApiData<AuditLog[]>("/internal/v1/audit-logs", [], { pageSize: "20" }),
  ]);

  const results = [summary, runtime, dataSources, batches, audits];
  const failed = results.find((item) => !item.ok);

  return {
    summary,
    runtime,
    dataSources,
    batches,
    audits,
    ok: results.every((item) => item.ok),
    error: failed?.error ?? null,
    traceId: failed?.traceId ?? results.find((item) => item.traceId)?.traceId ?? null,
  };
}

export async function loadIdentityData() {
  const [orgUnits, users, apiCallers, audits] = await Promise.all([
    getApiData<OrgUnit[]>("/internal/v1/org-units", []),
    getApiData<UserAccount[]>("/internal/v1/users", []),
    getApiData<ApiCaller[]>("/internal/v1/api-callers", []),
    getApiData<AuditLog[]>("/internal/v1/audit-logs", [], { pageSize: "100" }),
  ]);
  return { orgUnits, users, apiCallers, audits };
}

export async function loadWeek2Lists() {
  const [dataSources, batches, rawObjects, jobs, parseArtifacts, normalizedRefs, assets] =
    await Promise.all([
      getApiData<DataSource[]>("/internal/v1/data-sources", []),
      getApiData<IngestBatch[]>("/internal/v1/ingest/batches", []),
      getApiData<RawObject[]>("/internal/v1/raw-objects", []),
      getApiData<Job[]>("/internal/v1/jobs", []),
      getApiData<ParseArtifact[]>("/internal/v1/parse-artifacts", []),
      getApiData<NormalizedAssetRef[]>("/internal/v1/normalized-refs", []),
      getApiData<Asset[]>("/internal/v1/assets", []),
    ]);

  return { dataSources, batches, rawObjects, jobs, parseArtifacts, normalizedRefs, assets };
}
