import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { AiPromptsContent } from "@/components/AiPromptsContent";
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
        prototypeId="NX-13"
        title="AI Prompt 配置"
        description="维护 AI 治理和质量评分使用的 Prompt 配置。保存即激活新版本，仅影响未来接入资产。AI 治理环节自动选用对应模板+规则集组合。"
        actions={
          <div className="flex gap-2">
            <a href="/ai-prompts/playground" className="btn btn-primary btn-sm">试验场 →</a>
          </div>
        }
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      {/* Auto-selection info */}
      <div className="notice notice-info">
        ⓘ <strong>自动选用机制：</strong>AI 治理触发时根据治理目标自动匹配 Prompt 模板 + 规则集组合。如果某类模板未配置，对应治理环节跳过（不阻塞流水线）。选用记录写入审计日志。
      </div>

      <AiPromptsContent profiles={result.data} />
    </>
  );
}
