import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { DataSourcesContent } from "@/components/DataSourcesContent";
import { getApiData, type DataSource } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DataSourcesPage() {
  const result = await getApiData<DataSource[]>("/v1/data-sources", []);

  return (
    <>
      <PageHeader
        prototypeId="NX-02"
        title="数据源管理"
        description="注册不同类型的多源数据接入方式。系统支持本地文件上传、NAS 同步、Crawler 爬虫、数据库对接和 API 推送五种数据源类型。"
        actions={
          <a href="/data-sources/new" className="btn btn-primary">+ 新建数据源</a>
        }
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      <DataSourcesContent dataSources={result.data} />
    </>
  );
}
