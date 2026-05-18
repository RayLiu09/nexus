import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { GovernanceContent } from "@/components/GovernanceContent";
import { getApiData } from "@/lib/api";

export const dynamic = "force-dynamic";

type AIGovernanceRun = {
  id: string;
  normalized_ref_id: string;
  profile_id: string;
  model_alias: string;
  prompt_version: string;
  ai_output: Record<string, unknown> | null;
  quality_summary: Record<string, unknown> | null;
  validation_status: string;
  adoption_status: string;
  validation_error: string | null;
  created_at: string;
  updated_at: string;
};

export default async function GovernancePage() {
  const result = await getApiData<AIGovernanceRun[]>("/v1/ai/governance-runs", []);

  return (
    <>
      <PageHeader
        prototypeId="NX-08"
        title="治理中心"
        description="AI 治理建议、质量评分、治理待办、规则执行追踪和决策记录。按队列分类管理，支持批量采纳和逐条裁定。"
        actions={
          <button className="btn btn-secondary">
            📋 导出决策报告
          </button>
        }
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      <GovernanceContent runs={result.data} />
    </>
  );
}
