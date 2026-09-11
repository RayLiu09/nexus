import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import AiPromptsContent from "./_components/AiPromptsContent";
import { getApiData } from "@/lib/api";
import type { PromptProfile } from "@/lib/prompt-profiles-api";

export const dynamic = "force-dynamic";

export default async function AiPromptsPage() {
  const result = await getApiData<PromptProfile[]>("/internal/v1/ai/prompt-profiles", [], {
    status: "active",
    pageSize: "100",
  });

  return (
    <>
      <PageHeader
        eyebrow="治理管理"
        title="Prompt 提示词"
        description="维护业务运行时使用的版本化 Prompt 模板。"
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      <AiPromptsContent profiles={result.data} />
    </>
  );
}
