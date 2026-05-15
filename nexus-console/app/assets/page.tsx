import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { AssetsContent } from "@/components/AssetsContent";
import { getApiData, type DocumentAsset } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AssetsPage() {
  const result = await getApiData<DocumentAsset[]>("/v1/assets", []);

  return (
    <>
      <PageHeader
        prototypeId="NX-06"
        title="资产目录"
        description="展示由接入链路生成的资产、派生当前版本和标准化引用。支持卡片和列表双视图。"
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      <AssetsContent assets={result.data} />
    </>
  );
}
