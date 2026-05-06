import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { formatDateTime, getApiData, shortId, type Job, type JobStage } from "@/lib/api";

export const dynamic = "force-dynamic";

async function loadStages(jobs: Job[]) {
  const firstJob = jobs[0];
  if (!firstJob) {
    return getApiData<JobStage[]>("/v1/jobs/-/stages", []);
  }
  return getApiData<JobStage[]>(`/v1/jobs/${firstJob.id}/stages`, []);
}

export default async function JobsPage() {
  const jobs = await getApiData<Job[]>("/v1/jobs", []);
  const stages = jobs.ok ? await loadStages(jobs.data) : await loadStages([]);

  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-05</p>
          <h1>作业中心</h1>
          <p>展示接入后处理作业、阶段进度、失败原因和关联对象。</p>
        </div>
      </div>

      <ApiState ok={jobs.ok} error={jobs.error} traceId={jobs.traceId} />

      <div className="table-frame">
        <div className="table-row table-head">
          <span>作业ID</span>
          <span>类型</span>
          <span>关联对象</span>
          <span>当前阶段</span>
          <span>状态</span>
          <span>创建时间</span>
        </div>
        {jobs.data.length ? (
          jobs.data.map((job) => (
            <div className="table-row" key={job.id}>
              <span>{shortId(job.id)}</span>
              <span>{job.job_type}</span>
              <span>{shortId(job.raw_object_id)}</span>
              <span>{job.current_stage ?? "-"}</span>
              <StatusLabel value={job.status} />
              <span>{formatDateTime(job.created_at)}</span>
            </div>
          ))
        ) : (
          <div className="empty-state">
            <strong>暂无真实作业</strong>
          </div>
        )}
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>阶段</span>
          <span>阶段名</span>
          <span>输入对象</span>
          <span>输出对象</span>
          <span>状态</span>
        </div>
        {stages.data.length ? (
          stages.data.map((stage) => (
            <div className="table-row" key={stage.id}>
              <span>{shortId(stage.id)}</span>
              <span>{stage.stage_name}</span>
              <span>{shortId(stage.job_id)}</span>
              <span className="mono-cell">{JSON.stringify(stage.detail)}</span>
              <StatusLabel value={stage.status} />
            </div>
          ))
        ) : (
          <div className="empty-state">
            <strong>暂无阶段记录</strong>
          </div>
        )}
      </div>
    </section>
  );
}
