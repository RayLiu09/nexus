import { http, HttpResponse } from "msw";
import { apiBaseUrl, type ApiEnvelope } from "@/lib/api";
import {
  makeDataSource,
  makeJob,
  makeJobStage,
  makeIngestBatch,
  makeRawObject,
  makeAsset,
  makeAuditLog,
} from "./factories";
import type {
  JobStageInput,
  IngestBatchInput,
  RawObjectInput,
  AssetInput,
  AuditLogInput,
} from "./factories";

const BASE = apiBaseUrl();

function envelope<T>(data: T, meta?: { trace_id?: string; total?: number }): ApiEnvelope<T> {
  return { data, meta: { trace_id: "msw-00000000", ...meta } };
}

// ── Data Sources ───────────────────────────────────────────────────────────

export function getDataSources(overrides?: Parameters<typeof makeDataSource>[0][]) {
  const items = overrides?.map((o) => makeDataSource(o)) ?? [makeDataSource(), makeDataSource({ code: "ds_002", name: "Secondary" })];
  return http.get(`${BASE}/v1/data-sources`, () => HttpResponse.json(envelope(items, { total: items.length })));
}

// ── Jobs ───────────────────────────────────────────────────────────────────

export function getJobs(overrides?: Parameters<typeof makeJob>[0][]) {
  const items = overrides?.map((o) => makeJob(o)) ?? [
    makeJob({ status: "running" }),
    makeJob({ status: "succeeded", current_stage: "complete" }),
    makeJob({ status: "queued", current_stage: null }),
  ];
  return http.get(`${BASE}/v1/jobs`, () => HttpResponse.json(envelope(items, { total: items.length })));
}

// ── Job Stages ─────────────────────────────────────────────────────────────

export function getJobStages(jobId: string, overrides?: Partial<JobStageInput>[]) {
  const stages = overrides?.map((o) => makeJobStage({ ...o, job_id: jobId, stage_name: o.stage_name ?? "ingest_validate" })) ?? [
    makeJobStage({ job_id: jobId, stage_name: "ingest_validate", status: "succeeded", finished_at: new Date().toISOString() }),
    makeJobStage({ job_id: jobId, stage_name: "parse", status: "running" }),
  ];
  return http.get(`${BASE}/v1/jobs/${jobId}/stages`, () => HttpResponse.json(envelope(stages)));
}

// ── Ingest Batches ─────────────────────────────────────────────────────────

export function getIngestBatches(overrides?: Partial<IngestBatchInput>[]) {
  const items = overrides?.map((o) => makeIngestBatch({ ...o, data_source_id: o.data_source_id ?? "ds-00000000" })) ?? [
    makeIngestBatch({ data_source_id: "ds-00000000" }),
  ];
  return http.get(`${BASE}/v1/ingest-batches`, () => HttpResponse.json(envelope(items, { total: items.length })));
}

// ── Raw Objects ────────────────────────────────────────────────────────────

export function getRawObjects(overrides?: Partial<RawObjectInput>[]) {
  const items = overrides?.map((o) => makeRawObject({ ...o, batch_id: o.batch_id ?? "batch-00000000", data_source_id: o.data_source_id ?? "ds-00000000" })) ?? [
    makeRawObject({ batch_id: "batch-00000000", data_source_id: "ds-00000000" }),
  ];
  return http.get(`${BASE}/v1/raw-objects`, () => HttpResponse.json(envelope(items, { total: items.length })));
}

// ── Assets ─────────────────────────────────────────────────────────────────

export function getAssets(overrides?: Partial<AssetInput>[]) {
  const items = overrides?.map((o) => makeAsset({ ...o, data_source_id: o.data_source_id ?? "ds-00000000" })) ?? [
    makeAsset({ data_source_id: "ds-00000000" }),
    makeAsset({ data_source_id: "ds-00000000", title: "Second Doc", asset_kind: "record" }),
  ];
  return http.get(`${BASE}/v1/assets`, () => HttpResponse.json(envelope(items, { total: items.length })));
}

// ── Audit Logs ─────────────────────────────────────────────────────────────

export function getAuditLogs(overrides?: Partial<AuditLogInput>[]) {
  const items = overrides?.map((o) => makeAuditLog({ ...o, target_id: o.target_id ?? "target-00000000" })) ?? [
    makeAuditLog({ target_id: "target-00000000" }),
    makeAuditLog({ target_id: "target-00000001", event_type: "STAGE_COMPLETED" }),
  ];
  return http.get(`${BASE}/v1/audit-logs`, () => HttpResponse.json(envelope(items, { total: items.length })));
}

// ── POST handlers ──────────────────────────────────────────────────────────

export function postRetryJob(jobId: string) {
  return http.post(`${BASE}/v1/jobs/${jobId}/retry`, () => HttpResponse.json(envelope({ ok: true })));
}

export function postCancelJob(jobId: string) {
  return http.post(`${BASE}/v1/jobs/${jobId}/cancel`, () => HttpResponse.json(envelope({ ok: true })));
}

// ── Error simulation ───────────────────────────────────────────────────────

export function serverError(path: string, status = 500, message = "Internal Server Error") {
  return http.all(`${BASE}${path}`, () =>
    HttpResponse.json({ error: { message } }, { status }),
  );
}
