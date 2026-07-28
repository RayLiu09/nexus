import { PageHeader } from "@/components/PageHeader";
import TagReviewContent, { type GovernanceReviewItem } from "./_components/TagReviewContent";
import { Button } from "antd";
import { getApiData } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function TagReviewPage() {
  const result = await getApiData<GovernanceReviewItem[]>("/internal/v1/governance-reviews/pending", [], { pageSize: "100" });
  return <>
    <PageHeader eyebrow="资产与治理" title="治理审核" description="业务专家在此确认数据分类、分级、结构化标签、质量处置与组织范围。" actions={<Button type="primary" href="/governance">返回治理中心</Button>} />
    <TagReviewContent initialItems={result.data} ok={result.ok} error={result.error} traceId={result.traceId} />
  </>;
}
