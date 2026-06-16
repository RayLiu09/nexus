import { PageHeader } from "@/components/PageHeader";
import TagReviewContent from "./_components/TagReviewContent";
import { toTagReviewData } from "./_lib/tagReviewData";
import { Button } from "antd";
import { getApiData, type AIGovernanceRun } from "@/lib/api";
import { buildTagDictionary, type TagDictionaryEntry } from "@/lib/tagLabels";

export const dynamic = "force-dynamic";

export default async function TagReviewPage() {
  const [result, rulesResult] = await Promise.all([
    getApiData<AIGovernanceRun[]>("/internal/v1/ai/governance-runs", []),
    getApiData<{ tags?: TagDictionaryEntry[] }>("/internal/v1/admin/governance-rules", {}),
  ]);
  const tagDictionary = buildTagDictionary(rulesResult.data.tags);
  const data = toTagReviewData(result.data);

  return (
    <>
      <PageHeader
        eyebrow="资产与治理 — normalized asset 标签运营"
        title="标签审核"
        description="标签生成在 metadata_enrich 阶段针对 normalized asset 执行。页面读取真实 AI 治理运行记录，高置信自动提交，低置信进入人工审核。"
        actions={
          <Button type="primary" href="/governance">
            返回治理中心
          </Button>
        }
      />
      <TagReviewContent
        initialDrafts={data.drafts}
        initialCommitted={data.committed}
        ok={result.ok}
        error={result.error}
        traceId={result.traceId}
        tagDictionary={tagDictionary}
      />
    </>
  );
}
