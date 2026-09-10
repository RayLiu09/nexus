import { PageHeader } from "@/components/PageHeader";
import { ApiState } from "@/components/ApiState";
import { JobsContent } from "@/components/JobsContent";
import { getApiData, type Job, type JobStage, type RawObject } from "@/lib/api";
import { parsePaginationParams, DEFAULT_PAGE_SIZE } from "@/lib/pagination";

export const dynamic = "force-dynamic";

function extractFilename(obj: RawObject): string {
  const metaName = obj.metadata_summary?.filename;
  if (typeof metaName === "string" && metaName.length > 0) return metaName;
  const uri = obj.source_uri || obj.object_uri;
  if (uri) {
    const last = uri.split("/").pop();
    if (last && last.length > 0) return last;
  }
  return "-";
}

interface JobsPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function JobsPage({ searchParams }: JobsPageProps) {
  const params = await searchParams;
  const { page, pageSize } = parsePaginationParams(params);
  const currentPage = page ?? 1;
  const currentPageSize = pageSize ?? DEFAULT_PAGE_SIZE;

  const apiParams: Record<string, string> = {
    page: String(currentPage),
    pageSize: String(currentPageSize),
  };

  const jobs = await getApiData<Job[]>("/internal/v1/jobs", [], apiParams);
  const totalCount = jobs.total ?? jobs.data.length;

  // Collect unique raw_object_ids and fetch their metadata in parallel
  const rawObjectIds = [
    ...new Set(jobs.data.map((j) => j.raw_object_id).filter(Boolean)),
  ] as string[];
  const rawObjectResults = await Promise.all(
    rawObjectIds.map((id) =>
      getApiData<RawObject>(`/internal/v1/raw-objects/${id}`, null as unknown as RawObject),
    ),
  );
  const rawObjectNames = new Map<string, string>();
  for (const result of rawObjectResults) {
    if (result.ok && result.data) {
      rawObjectNames.set(result.data.id, extractFilename(result.data));
    }
  }

  const firstJob = jobs.data[0];
  const stages = await getApiData<JobStage[]>(
    firstJob ? `/internal/v1/jobs/${firstJob.id}/stages` : "/internal/v1/jobs/-/stages",
    [],
  );

  return (
    <>
      <PageHeader
        eyebrow="流水线 — 作业调度与监控"
        title="作业中心"
        description="展示接入后处理作业、阶段进度、失败原因和关联对象。活跃作业自动轮询状态。作业由数据接入提交后自动创建。"
      />

      <ApiState ok={jobs.ok} error={jobs.error} traceId={jobs.traceId} />

      <JobsContent
        jobs={jobs.data}
        stages={stages.data}
        rawObjectNames={rawObjectNames}
        totalCount={totalCount}
        currentPage={currentPage}
        pageSize={currentPageSize}
      />
    </>
  );
}
