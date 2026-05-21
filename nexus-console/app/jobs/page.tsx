import { PageHeader } from "@/components/PageHeader";
import { ApiState } from "@/components/ApiState";
import { Card } from "@/components/shared/Card";
import { JobsContent } from "@/components/JobsContent";
import { getApiData, type Job, type JobStage } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function JobsPage() {
  const jobs = await getApiData<Job[]>("/v1/jobs", []);
  const firstJob = jobs.data[0];
  const stages = await getApiData<JobStage[]>(
    firstJob ? `/v1/jobs/${firstJob.id}/stages` : "/v1/jobs/-/stages",
    [],
  );

  const total = jobs.data.length;
  const running = jobs.data.filter((j) => j.status === "running" || j.status === "queued").length;
  const succeeded = jobs.data.filter((j) => j.status === "succeeded").length;
  const failed = jobs.data.filter(
    (j) => j.status === "failed" || j.status === "dead_lettered",
  ).length;

  return (
    <>
      <PageHeader
        eyebrow="流水线 — 作业调度与监控"
        title="作业中心"
        description="展示接入后处理作业、阶段进度、失败原因和关联对象。活跃作业自动轮询状态。作业由数据接入提交后自动创建。"
      />

      <ApiState ok={jobs.ok} error={jobs.error} traceId={jobs.traceId} />

      {/* ── Metrics ── */}
      <div className="metric-grid-4">
        <Card variant="metric" weight="secondary">
          <div className="card-label">作业总数</div>
          <div className="card-value">{total}</div>
        </Card>
        <Card variant="metric" weight="secondary" tone={running > 0 ? "warning" : "default"}>
          <div className="card-label">运行中</div>
          <div className="card-value">{running}</div>
        </Card>
        <Card variant="metric" weight="secondary" tone="success">
          <div className="card-label">已完成</div>
          <div className="card-value">{succeeded}</div>
        </Card>
        <Card variant="metric" weight="secondary" tone={failed > 0 ? "danger" : "default"}>
          <div className="card-label">失败</div>
          <div className="card-value">{failed}</div>
          <div className="card-sub">{failed > 0 ? "需排查" : "无异常"}</div>
        </Card>
      </div>

      <JobsContent jobs={jobs.data} stages={stages.data} />
    </>
  );
}
