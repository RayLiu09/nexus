import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { loadIdentityData } from "@/lib/console-data";
import { IamAuditContent } from "./_components/IamAuditContent";

export const dynamic = "force-dynamic";

export default async function IamAuditPage() {
  const { orgUnits, users, apiCallers, audits } = await loadIdentityData();
  const ok = orgUnits.ok && users.ok && apiCallers.ok && audits.ok;
  const error = orgUnits.error ?? users.error ?? apiCallers.error ?? audits.error ?? null;

  return (
    <>
      <PageHeader
        eyebrow="访问与审计 — 组织、角色、API 调用方"
        title="权限与审计"
        description="本地组织用户、角色、API 调用方、组织范围和安全审计日志。"
      />

      <ApiState ok={ok} error={error} traceId={orgUnits.traceId ?? audits.traceId} />

      <IamAuditContent
        apiCallers={apiCallers.data}
        audits={audits.data}
        orgCount={orgUnits.data.length}
        userCount={users.data.length}
        apiCallerCount={apiCallers.data.length}
        auditCount={audits.data.length}
      />
    </>
  );
}
