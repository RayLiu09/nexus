import { PageHeader } from "@/components/PageHeader";
import { ApiState } from "@/components/ApiState";
import { getApiData, type ApiCaller } from "@/lib/api";
import { ApiCallersContent } from "./_components/ApiCallersContent";

export const dynamic = "force-dynamic";

export default async function ApiCallersPage() {
  const result = await getApiData<ApiCaller[]>("/v1/api-callers", []);

  return (
    <>
      <PageHeader
        eyebrow="访问与审计 — API 调用方"
        title="API Caller 管理"
        description="创建、管理和吊销 API 调用方凭证，用于外部系统访问 NEXUS API。"
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      <ApiCallersContent callers={result.data} />
    </>
  );
}
