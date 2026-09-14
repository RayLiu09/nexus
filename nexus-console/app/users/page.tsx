import { PageHeader } from "@/components/PageHeader";
import { getApiData, type UserAccount } from "@/lib/api";
import { parsePaginationParams, DEFAULT_PAGE_SIZE } from "@/lib/pagination";
import { UsersContent } from "./_components/UsersContent";

export const dynamic = "force-dynamic";

interface UsersPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function UsersPage({ searchParams }: UsersPageProps) {
  const params = await searchParams;
  const { page, pageSize } = parsePaginationParams(params);
  const currentPage = page ?? 1;
  const currentPageSize = pageSize ?? DEFAULT_PAGE_SIZE;

  const result = await getApiData<UserAccount[]>("/internal/v1/users", [], {
    page: String(currentPage),
    pageSize: String(currentPageSize),
  });

  return (
    <>
      <PageHeader
        eyebrow="访问与审计 — 用户管理"
        title="用户管理"
        description="管理 NEXUS Console 用户账号：创建、编辑、激活/禁用、重置密码。平台仅支持数据管理员与业务专家两种角色。"
      />

      <UsersContent
        users={result.data}
        totalCount={result.total ?? result.data.length}
        currentPage={currentPage}
        pageSize={currentPageSize}
        ok={result.ok}
        error={result.error}
        traceId={result.traceId}
      />
    </>
  );
}
