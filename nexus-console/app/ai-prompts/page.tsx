import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import AiPromptsContent from "./_components/AiPromptsContent";
import { getApiData } from "@/lib/api";

export const dynamic = "force-dynamic";

type PromptProfile = {
  id: string;
  profile_name: string;
  profile_version: number;
  task_type: string;
  status: string;
  litellm_model_alias: string;
  prompt_version: string;
  output_schema_version: string;
  scoring_weight_version: string;
  temperature: number;
  max_input_tokens: number;
  redaction_policy: string;
  created_at: string;
  updated_at: string;
};

export default async function AiPromptsPage() {
  const result = await getApiData<PromptProfile[]>("/v1/ai/prompt-profiles", []);

  return (
    <>
      <PageHeader
        eyebrow="资产与治理 — AI Prompt 资产管理"
        title="AI Prompt 配置"
        description="维护 AI 治理和质量评分使用的 Prompt 配置。保存即激活新版本，仅影响未来接入资产。AI 治理环节自动选用对应模板+规则集组合。"
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      <div
        style={{
          padding: "12px 16px",
          borderRadius: "var(--radius-lg)",
          background: "var(--brand-50)",
          border: "1px solid var(--brand-200)",
          fontSize: 13,
          marginBottom: 16,
        }}
      >
        <strong>自动选用机制：</strong>AI 治理触发时根据治理目标自动匹配 Prompt 模板 +
        规则集组合。如果某类模板未配置，对应治理环节跳过（不阻塞流水线）。选用记录写入审计日志。
      </div>

      <AiPromptsContent profiles={result.data} />
    </>
  );
}
