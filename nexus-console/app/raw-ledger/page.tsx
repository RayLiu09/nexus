import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { Card } from "@/components/shared/Card";
import { getApiData, type RawObject } from "@/lib/api";
import { parsePaginationParams, DEFAULT_PAGE_SIZE } from "@/lib/pagination";
import { RawLedgerContent } from "./_components/RawLedgerContent";

export const dynamic = "force-dynamic";

interface RawObjectSummary {
  total: number;
  validated: number;
  pending: number;
  failed: number;
}

interface RawLedgerPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function RawLedgerPage({ searchParams }: RawLedgerPageProps) {
  const params = await searchParams;
  const { page, pageSize } = parsePaginationParams(params);

  const currentPage = page ?? 1;
  const currentPageSize = pageSize ?? DEFAULT_PAGE_SIZE;

  // Aggregate + paginated list are independent — fetch in parallel.
  const [summaryResult, tableResult] = await Promise.all([
    getApiData<RawObjectSummary | null>("/internal/v1/raw-objects/summary", null),
    getApiData<RawObject[]>("/internal/v1/raw-objects", [], {
      page: String(currentPage),
      pageSize: String(currentPageSize),
    }),
  ]);

  const summary = summaryResult.data;
  const totalCount = summary?.total ?? tableResult.data.length;
  const validatedCount = summary?.validated ?? 0;
  const pendingCount = summary?.pending ?? 0;
  const failedCount = summary?.failed ?? 0;

  return (
    <>
      <PageHeader
        eyebrow="数据接入 — 原始留存与追溯"
        title="原始数据台账"
        description="按批次和对象追溯原始留存位置、checksum、来源和接入状态。每个原始对象对应一次接入校验记录。"
      />

      <ApiState ok={summaryResult.ok} error={summaryResult.error} traceId={summaryResult.traceId} />

      {/* Metrics — from aggregate endpoint */}
      <div className="metric-grid-4">
        <Card variant="metric" weight="secondary">
          <div className="card-label">原始对象总数</div>
          <div className="card-value">{totalCount}</div>
        </Card>
        <Card variant="metric" weight="secondary" tone="success">
          <div className="card-label">已校验</div>
          <div className="card-value">{validatedCount}</div>
        </Card>
        <Card variant="metric" weight="secondary" tone={pendingCount > 0 ? "warning" : "default"}>
          <div className="card-label">待处理</div>
          <div className="card-value">{pendingCount}</div>
        </Card>
        <Card variant="metric" weight="secondary" tone={failedCount > 0 ? "danger" : "default"}>
          <div className="card-label">校验失败</div>
          <div className="card-value">{failedCount}</div>
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
      />
    </>
  );
}
