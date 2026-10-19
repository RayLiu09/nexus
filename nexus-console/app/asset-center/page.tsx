import { Suspense } from "react";
import { PageHeader } from "@/components/PageHeader";
import { getApiData, type AssetCenterCounts } from "@/lib/api";
import { AssetCenterOverview } from "./_components/AssetCenterOverview";

export const dynamic = "force-dynamic";

async function AssetCenterCounts() {
  const result = await getApiData<AssetCenterCounts>("/internal/v1/asset-center/counts", {
    counts: {},
  });

  return <AssetCenterOverview counts={result.ok ? result.data.counts : null} />;
}

export default function AssetCenterPage() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        eyebrow="业务任务视图"
        title="资产中心"
        description="产业、专业、市场与教材数据"
      />
      <Suspense fallback={<AssetCenterOverview counts={null} loading />}>
        <AssetCenterCounts />
      </Suspense>
    </div>
  );
}
