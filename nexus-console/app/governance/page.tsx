import { PageHeader } from "@/components/PageHeader";
import { Button } from "antd";
import { GovernanceTrackingContent, type GovernanceTrace } from "./_components/GovernanceTrackingContent";
import { getApiData } from "@/lib/api";
import { buildTagDictionary, type TagDictionaryEntry } from "@/lib/tagLabels";
import { buildClassificationDictionary, type ClassificationDictionaryEntry } from "@/lib/classificationLabels";
import { buildLevelDictionary, type LevelDictionaryEntry } from "@/lib/levelLabels";

export const dynamic = "force-dynamic";

export default async function GovernancePage() {
  const [result, rulesResult] = await Promise.all([
    getApiData<GovernanceTrace[]>("/internal/v1/governance-traces", [], { pageSize: "20" }),
    getApiData<{ classifications?: ClassificationDictionaryEntry[]; levels?: LevelDictionaryEntry[]; tags?: TagDictionaryEntry[] }>("/internal/v1/admin/governance-rules", {}),
  ]);
  const tagDictionary = buildTagDictionary(rulesResult.data.tags);
  const classificationDictionary = buildClassificationDictionary(rulesResult.data.classifications);
  const levelDictionary = buildLevelDictionary(rulesResult.data.levels);

  return (
    <>
      <PageHeader
        eyebrow="资产与治理"
        title="治理追踪"
        description="查看正式治理结果、人工审核结论及字段级决策证据。"
        actions={<Button type="primary" href="/tag-review">进入治理审核</Button>}
      />
      <GovernanceTrackingContent
        initialRows={result.data}
        initialTotal={result.total ?? result.data.length}
        error={result.ok ? null : result.error}
        tagDictionary={tagDictionary}
        classificationDictionary={classificationDictionary}
        levelDictionary={levelDictionary}
      />
    </>
  );
}
