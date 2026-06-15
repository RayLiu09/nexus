import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { DataSourcesContent, type SyncInfo } from "./_components/DataSourcesContent";
import { getApiData, type DataSource, type IngestBatch } from "@/lib/api";
import { nextCronRun } from "@/lib/cron/nextRun";

export const dynamic = "force-dynamic";

function readScheduleCron(ds: DataSource): string | null {
  const cfg = (ds.connection_config ?? {}) as Record<string, unknown>;
  const value = cfg.schedule_cron ?? cfg.cfg_schedule_cron;
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

export default async function DataSourcesPage() {
  const [sourcesResult, batchesResult] = await Promise.all([
    getApiData<DataSource[]>("/internal/v1/data-sources", []),
    getApiData<IngestBatch[]>("/internal/v1/ingest/batches", []),
  ]);

  // 取每个数据源最近一次批次的 updated_at —— 这是用户视角的"上次同步"
  const lastSyncByDsId = new Map<string, string>();
  for (const batch of batchesResult.data) {
    const prev = lastSyncByDsId.get(batch.data_source_id);
    if (!prev || prev < batch.updated_at) {
      lastSyncByDsId.set(batch.data_source_id, batch.updated_at);
    }
  }

  // 解析 schedule_cron 算下次触发；不支持的表达式返回 null，UI 降级
  const now = new Date();
  const syncInfoByDsId: Record<string, SyncInfo> = {};
  for (const ds of sourcesResult.data) {
    const cron = readScheduleCron(ds);
    const next = cron ? nextCronRun(cron, now) : null;
    syncInfoByDsId[ds.id] = {
      lastSync: lastSyncByDsId.get(ds.id) ?? null,
      nextSync: next ? next.toISOString() : null,
      cron,
    };
  }

  return (
    <>
      <PageHeader
        eyebrow="数据工程 — 连接器注册与管理"
        title="数据源"
        description="注册不同类型的多源数据接入方式。系统支持本地文件上传、NAS 同步、Crawler 爬虫、数据库对接和 API 推送五种数据源类型。"
      />

      <ApiState
        ok={sourcesResult.ok && batchesResult.ok}
        error={sourcesResult.error ?? batchesResult.error}
        traceId={sourcesResult.traceId ?? batchesResult.traceId}
      />

      <DataSourcesContent dataSources={sourcesResult.data} syncInfoByDsId={syncInfoByDsId} />
    </>
  );
}
