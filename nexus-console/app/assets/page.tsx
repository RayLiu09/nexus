import { PageHeader } from "@/components/PageHeader";
import { AssetsContent } from "./_components/AssetsContent";
import { getApiData } from "@/lib/api";
import type { AssetWithMeta } from "./_lib/types";

export const dynamic = "force-dynamic";

export default async function AssetsPage() {
  const result = await getApiData<AssetWithMeta[]>("/v1/assets", []);

  return (
    <>
      <PageHeader
        eyebrow="主数据与当前视图"
        title="资产目录"
        description="目录页以「当前可读视图」服务运营和消费方，核心是 current version / current normalized ref / index state 的组合。"
      />
      <AssetsContent assets={result.data} />
    </>
  );
}
