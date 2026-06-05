import { PageHeader } from "@/components/PageHeader";
import { getApiData, type ApiCaller } from "@/lib/api";
import { parsePaginationParams, DEFAULT_PAGE_SIZE } from "@/lib/pagination";
import { ApiCallersContent } from "./_components/ApiCallersContent";

export const dynamic = "force-dynamic";

interface ApiCallersPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function ApiCallersPage({ searchParams }: ApiCallersPageProps) {
  const params = await searchParams;
  const { page, pageSize } = parsePaginationParams(params);

  const currentPage = page ?? 1;
  const currentPageSize = pageSize ?? DEFAULT_PAGE_SIZE;

  const result = await getApiData<ApiCaller[]>(
    "/internal/v1/api-callers",
    [],
    { page: String(currentPage), pageSize: String(currentPageSize) },
  );

  const totalCount = result.data.length;

  return (
    <>
      <PageHeader
        eyebrow="访问与审计 — API 调用方"
        title="API Caller 管理"
        description="创建、管理和吊销 API 调用方凭证，用于外部系统访问 NEXUS API。"
      />

      <ApiCallersContent
        callers={result.data}
        totalCount={totalCount}
        currentPage={currentPage}
        pageSize={currentPageSize}
        ok={result.ok}
        error={result.error}
        traceId={result.traceId}
      />
    </>
  );
}
