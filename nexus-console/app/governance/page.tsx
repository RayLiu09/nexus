import { PageHeader } from "@/components/PageHeader";
import { GovernanceContent } from "./_components/GovernanceContent";
import { getApiData } from "@/lib/api";
import type { GovernanceRun } from "./_lib/types";
import { buildTagDictionary, type TagDictionaryEntry } from "@/lib/tagLabels";

export const dynamic = "force-dynamic";

export default async function GovernancePage() {
  const [result, rulesResult] = await Promise.all([
    getApiData<GovernanceRun[]>("/internal/v1/ai/governance-runs", []),
    getApiData<{ tags?: TagDictionaryEntry[] }>("/internal/v1/admin/governance-rules", {}),
  ]);
  const tagDictionary = buildTagDictionary(rulesResult.data.tags);

  return (
    <>
      <PageHeader
        eyebrow="资产与治理 — AI + 规则 + 人工协同"
        title="治理运营中心"
        description="以任务和裁定为中心组织。待复核队列以卡片呈现，优先级排序，支持完整的裁定交互闭环。标签审核已独立至「标签审核」页面。"
      />
      <GovernanceContent runs={result.data} tagDictionary={tagDictionary} />
    </>
  );
}
