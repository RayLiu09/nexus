import { PageHeader } from "@/components/PageHeader";
import { ApiState } from "@/components/ApiState";
import { getApiData, type AIGovernanceRun, type AuditLog } from "@/lib/api";
import { WorkspaceContent } from "./_components/WorkspaceContent";

export const dynamic = "force-dynamic";

export default async function MyWorkspacePage() {
  const [grResult, auditResult] = await Promise.all([
    getApiData<AIGovernanceRun[]>("/internal/v1/ai/governance-runs", []),
    getApiData<AuditLog[]>("/internal/v1/audit-logs", []),
  ]);

  const pendingReview = grResult.data.filter(
    (r) =>
      r.adoption_status === "review_required" || r.adoption_status === "pending_rule_guardrail",
  );
  const recentAudits = auditResult.data.slice(0, 10);

  return (
    <>
      <PageHeader
        eyebrow="个人中心 — SLA 驱动的待办管理"
        title="我的工作区"
        description="按 SLA 优先级管理个人待办任务。超时任务优先处理，今日任务及时完成，正常任务按序推进。"
      />

      <ApiState
        ok={grResult.ok && auditResult.ok}
        error={grResult.error ?? auditResult.error}
        traceId={grResult.traceId ?? auditResult.traceId}
      />

      <WorkspaceContent pendingReview={pendingReview} recentAudits={recentAudits} />
    </>
  );
}
