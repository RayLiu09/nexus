import { PageHeader } from "@/components/PageHeader";
import TagReviewContent, { type GovernanceReviewItem } from "./_components/TagReviewContent";
import { Button } from "antd";
import { getApiData } from "@/lib/api";
import { buildClassificationDictionary, type ClassificationDictionaryEntry } from "@/lib/classificationLabels";
import { buildLevelDictionary, type LevelDictionaryEntry } from "@/lib/levelLabels";

export const dynamic = "force-dynamic";

export default async function TagReviewPage() {
  const [result, rulesResult] = await Promise.all([
    getApiData<GovernanceReviewItem[]>("/internal/v1/governance-reviews/pending", [], { pageSize: "100" }),
    getApiData<{ classifications?: ClassificationDictionaryEntry[]; levels?: LevelDictionaryEntry[] }>("/internal/v1/admin/governance-rules", {}),
  ]);
  return <>
    <PageHeader eyebrow="资产与治理" title="治理审核" description="业务专家在此确认数据分类、分级、结构化标签、质量处置与组织范围。" actions={<Button type="primary" href="/governance">返回治理追踪</Button>} />
    <TagReviewContent
      initialItems={result.data}
      ok={result.ok}
      error={result.error}
      traceId={result.traceId}
      classificationDictionary={buildClassificationDictionary(rulesResult.data.classifications)}
      levelDictionary={buildLevelDictionary(rulesResult.data.levels)}
    />
  </>;
}
