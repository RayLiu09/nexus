import { PageHeader } from "@/components/PageHeader";
import { AssetsContent } from "./_components/AssetsContent";
import { getApiData } from "@/lib/api";
import { parsePaginationParams, DEFAULT_PAGE_SIZE } from "@/lib/pagination";
import type { AssetWithMeta, AssetSummary } from "./_lib/types";

export const dynamic = "force-dynamic";

interface AssetsPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function AssetsPage({ searchParams }: AssetsPageProps) {
  const params = await searchParams;
  const { page, pageSize } = parsePaginationParams(params);

  const currentPage = page ?? 1;
  const currentPageSize = pageSize ?? DEFAULT_PAGE_SIZE;
  const domain = firstParam(params.domain);
  const level = firstParam(params.level);
  const status = firstParam(params.status) ?? "visible";

  const tableParams: Record<string, string> = {
    page: String(currentPage),
    pageSize: String(currentPageSize),
  };
  if (domain) tableParams.domain = domain;
  if (level) tableParams.level = level;
  if (status && status !== "all") tableParams.status = status;

  // Aggregate + paginated list are independent — fetch in parallel.
  const [summaryResult, tableResult] = await Promise.all([
    getApiData<AssetSummary | null>("/internal/v1/assets/summary", null),
    getApiData<AssetWithMeta[]>("/internal/v1/assets", [], tableParams),
  ]);

  const tableData = tableResult.data;
  const totalCount = summaryResult.data?.total ?? tableData.length;

  return (
    <>
      <PageHeader
        eyebrow="主数据与当前视图"
        title="资产目录"
        description="目录页以「当前可读视图」服务运营和消费方，核心是 current version / current normalized ref / index state 的组合。"
      />
      <AssetsContent
        assets={tableData}
        summary={summaryResult.data}
        totalCount={totalCount}
        currentPage={currentPage}
        pageSize={currentPageSize}
        filters={{ domain, level, status }}
        ok={tableResult.ok}
        error={tableResult.error}
        traceId={tableResult.traceId}
      />
    </>
  );
}

function firstParam(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value;
}
