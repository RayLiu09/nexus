import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { JobsContent } from "@/components/JobsContent";
import { getApiData, type Job, type JobStage } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function JobsPage() {
  const jobs = await getApiData<Job[]>("/v1/jobs", []);
  const firstJob = jobs.data[0];
  const stages = await getApiData<JobStage[]>(
    firstJob ? `/v1/jobs/${firstJob.id}/stages` : "/v1/jobs/-/stages",
    []
  );

  return (
    <>
      <PageHeader
        prototypeId="NX-05"
        title="作业中心"
        description="展示接入后处理作业、阶段进度、失败原因和关联对象。活跃作业自动轮询状态。作业由数据接入提交后自动创建。"
      />

      <ApiState ok={jobs.ok} error={jobs.error} traceId={jobs.traceId} />

      <JobsContent jobs={jobs.data} stages={stages.data} />
    </>
  );
}
