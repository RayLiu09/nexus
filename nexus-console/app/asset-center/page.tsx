import { PageHeader } from "@/components/PageHeader";
import { getApiData, type AssetCenterCounts } from "@/lib/api";
import { AssetCenterOverview } from "./_components/AssetCenterOverview";

export const dynamic = "force-dynamic";

export default async function AssetCenterPage() {
  const result = await getApiData<AssetCenterCounts>("/internal/v1/asset-center/counts", {
    counts: {},
  });

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        eyebrow="业务任务视图"
        title="资产中心"
        description="产业政策、专业、市场、教材资源与用户行为数据"
      />
      <AssetCenterOverview counts={result.ok ? result.data.counts : null} />
    </div>
  );
}
