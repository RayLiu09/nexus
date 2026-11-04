import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { getApiData, type AuditLog } from "@/lib/api";
import { DEFAULT_PAGE_SIZE, parsePaginationParams } from "@/lib/pagination";
import { IamAuditContent } from "./_components/IamAuditContent";

export const dynamic = "force-dynamic";

interface IamAuditPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function IamAuditPage({ searchParams }: IamAuditPageProps) {
  const params = await searchParams;
  const { page = 1, pageSize = DEFAULT_PAGE_SIZE } = parsePaginationParams(params);
  // Keep existing workbench activity links compatible with the new filter.
  const rawEvent = params.event_type ?? params.event;
  const eventType = Array.isArray(rawEvent) ? rawEvent[0] : rawEvent;
  const query: Record<string, string> = {
    page: String(page),
    pageSize: String(pageSize),
    exclude_token_refresh: "true",
  };
  if (eventType) query.event_type = eventType;
  const [audits, eventTypes] = await Promise.all([
    getApiData<AuditLog[]>("/internal/v1/audit-logs", [], query),
    getApiData<string[]>("/internal/v1/audit-logs/event-types", [], {
      exclude_token_refresh: "true",
    }),
  ]);

  return (
    <>
      <PageHeader
        eyebrow="访问与审计"
        title="审计日志"
        description="查看操作目标、操作者、摘要和操作时间，可按事件类型筛选。"
      />

      <ApiState
        ok={audits.ok && eventTypes.ok}
        error={audits.error ?? eventTypes.error}
        traceId={audits.traceId ?? eventTypes.traceId}
      />

      <IamAuditContent
        audits={audits.data}
        eventTypes={eventTypes.data}
        eventType={eventType}
        totalCount={audits.total ?? audits.data.length}
        currentPage={page}
        pageSize={pageSize}
      />
    </>
  );
}
