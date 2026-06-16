import { Card, Statistic } from "antd";
import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { getApiData, type DataSource, type RawObject } from "@/lib/api";
import { parsePaginationParams, DEFAULT_PAGE_SIZE } from "@/lib/pagination";
import { RawLedgerContent } from "./_components/RawLedgerContent";

export const dynamic = "force-dynamic";

interface RawLedgerPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function RawLedgerPage({ searchParams }: RawLedgerPageProps) {
  const params = await searchParams;
  const { page, pageSize } = parsePaginationParams(params);

  const currentPage = page ?? 1;
  const currentPageSize = pageSize ?? DEFAULT_PAGE_SIZE;
  const filterBatchId = typeof params.batch_id === "string" ? params.batch_id : undefined;
  const filterDataSourceId = typeof params.data_source_id === "string" ? params.data_source_id : undefined;

  const apiParams: Record<string, string> = {
    page: String(currentPage),
    pageSize: String(currentPageSize),
  };
  if (filterBatchId) apiParams.batch_id = filterBatchId;
  if (filterDataSourceId) apiParams.data_source_id = filterDataSourceId;

  const [tableResult, sourcesResult] = await Promise.all([
    getApiData<RawObject[]>("/internal/v1/raw-objects", [], apiParams),
    getApiData<DataSource[]>("/internal/v1/data-sources", [], {
      includeDeleted: "true",
    }),
  ]);

  const dataSourceNames = new Map<string, string>();
  for (const ds of sourcesResult.data) {
    dataSourceNames.set(ds.id, ds.name);
  }

  const totalCount = tableResult.total ?? tableResult.data.length;
  const validatedCount = tableResult.data.filter((o) => o.status === "raw_persisted").length;
  const failedCount = tableResult.data.filter(
    (o) => o.status === "checksum_failed" || o.status === "failed",
  ).length;
  const duplicateCount = tableResult.data.filter(
    (o) => o.status === "duplicate_skipped",
  ).length;

  return (
    <>
      <PageHeader
        eyebrow="数据接入 — 原始留存与追溯"
        title="原始数据台账"
        description="按批次和对象追溯原始留存位置、checksum、来源和接入状态。每个原始对象对应一次接入校验记录。"
      />

      <ApiState ok={tableResult.ok} error={tableResult.error} traceId={tableResult.traceId} />

      {/* Metrics */}
      <div className="metric-grid-4">
        <Card size="small" className="metric-secondary">
          <Statistic title="原始对象总数" value={totalCount} />
        </Card>
        <Card size="small" className="metric-secondary">
          <Statistic
            title="已校验"
            value={validatedCount}
            styles={{ content: { color: "var(--success-600)" } }}
          />
        </Card>
        <Card size="small" className="metric-secondary">
          <Statistic
            title="校验失败"
            value={failedCount}
            styles={{ content: failedCount > 0 ? { color: "var(--danger-600)" } : undefined }}
          />
        </Card>
        <Card size="small" className="metric-secondary">
          <Statistic title="重复跳过" value={duplicateCount} />
        </Card>
      </div>

      {/* Paginated table */}
      <RawLedgerContent
        objects={tableResult.data}
        totalCount={totalCount}
        currentPage={currentPage}
        pageSize={currentPageSize}
        ok={tableResult.ok}
        error={tableResult.error}
        traceId={tableResult.traceId}
        dataSourceNames={dataSourceNames}
        filterBatchId={filterBatchId}
        filterDataSourceId={filterDataSourceId}
      />
    </>
  );
}
