import { PageHeader } from "@/components/PageHeader";
import { ApiState } from "@/components/ApiState";
import { getApiData, type AIGovernanceRun } from "@/lib/api";
import { selectCurrentReviewRuns } from "@/lib/governance-runs";
import { WorkspaceContent } from "./_components/WorkspaceContent";

export const dynamic = "force-dynamic";

export default async function MyWorkspacePage() {
  const grResult = await getApiData<AIGovernanceRun[]>("/internal/v1/ai/governance-runs", []);

  const pendingReview = selectCurrentReviewRuns(grResult.data);

  return (
    <>
      <PageHeader
        eyebrow="个人中心 — SLA 驱动的待办管理"
        title="我的工作区"
        description="按 SLA 优先级管理个人待办任务。超时任务优先处理，今日任务及时完成，正常任务按序推进。"
      />

      <ApiState
        ok={grResult.ok}
        error={grResult.error}
        traceId={grResult.traceId}
      />

      <WorkspaceContent pendingReview={pendingReview} />
    </>
  );
}
