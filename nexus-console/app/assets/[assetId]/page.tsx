import { PageScaffold } from "@/components/PageScaffold";

export default function AssetDetailPage({ params }: { params: { assetId: string } }) {
  return (
    <PageScaffold
      title={`资产详情 ${params.assetId}`}
      prototypeId="NX-07"
      summary="概览、版本、标准化引用、AI 治理、质量评分、治理结果、决策追踪、切片、索引清单、血缘和审计。"
      columns={["区域", "对象ID", "状态", "更新时间", "追溯入口"]}
      statuses={["available", "review_required", "indexed", "stale", "failed"]}
    />
  );
}
