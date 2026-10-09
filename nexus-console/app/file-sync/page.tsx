import { PageHeader } from "@/components/PageHeader";
import { ApiState } from "@/components/ApiState";
import { getApiData, type IngestBatch } from "@/lib/api";
import { FileSyncContent, FileSyncHistory } from "./_components/FileSyncContent";

export const dynamic = "force-dynamic";

export default async function FileSyncPage() {
  const result = await getApiData<IngestBatch[]>("/internal/v1/ingest/batches", []);
  const batches = result.data.filter((batch) => batch.source_type === "file_upload" || batch.source_type === "nas");

  return (
    <>
      <PageHeader title="文件数据同步" eyebrow="数据管理" description="上传本地文件或查看 NAS 同步。" />
      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />
      <FileSyncContent />
      <FileSyncHistory batches={batches} />
    </>
  );
}
