import { PageHeader } from "@/components/PageHeader";
import { ApiState } from "@/components/ApiState";
import { getApiData, type DataSource } from "@/lib/api";

import { BatchUploadPage } from "./_components/BatchUploadPage";

export const dynamic = "force-dynamic";

export default async function MultiFileBatchPage() {
  const sources = await getApiData<DataSource[]>("/internal/v1/data-sources", []);

  return (
    <>
      <PageHeader
        eyebrow="数据接入 — 批量上传"
        title="批量文件上传"
        description="为同一个数据源一次性上传多个文件，系统会创建一个批次并对每个文件独立资产化、解析与标准化，自动聚合批次状态。"
      />

      <ApiState ok={sources.ok} error={sources.error} traceId={sources.traceId} />

      <BatchUploadPage sources={sources.data} />
    </>
  );
}
