import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { DataSourcesContent } from "./_components/DataSourcesContent";
import { getApiData, type DataSource } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DataSourcesPage() {
  const result = await getApiData<DataSource[]>("/internal/v1/data-sources", []);

  return (
    <>
      <PageHeader
        eyebrow="数据接入 — 连接器注册与管理"
        title="数据源管理"
        description="注册不同类型的多源数据接入方式。系统支持本地文件上传、NAS 同步、Crawler 爬虫、数据库对接和 API 推送五种数据源类型。"
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      <DataSourcesContent dataSources={result.data} />
    </>
  );
}
