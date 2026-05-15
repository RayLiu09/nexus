"use client";

import { useState } from "react";
import { StatusLabel } from "@/components/StatusLabel";
import { PollingIndicator } from "@/components/PollingIndicator";
import { DefaultDocPipeline } from "@/components/JobPipeline";
import { EmptyState } from "@/components/EmptyState";
import { formatDateTime, shortId, type Job, type JobStage } from "@/lib/api";

export function JobsContent({ jobs, stages }: { jobs: Job[]; stages: JobStage[] }) {
  const [pollingState, setPollingState] = useState<"active" | "paused" | "error">("active");

  const hasActiveJobs = jobs.some((j) => j.status === "running" || j.status === "queued");

  return (
    <>
      {/* Polling indicator */}
      {hasActiveJobs && (
        <PollingIndicator
          state={pollingState}
          intervalSeconds={3}
          lastUpdate="2s前"
          responseMs={45}
          onRefresh={() => window.location.reload()}
          onToggle={() => setPollingState((s) => (s === "active" ? "paused" : "active"))}
        />
      )}

      {/* Pipeline visualization */}
      {jobs.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">流水线概览</span>
            <span className="text-xs text-muted">
              {jobs.filter((j) => j.status === "running").length} 个活跃作业
            </span>
          </div>
          <div className="card-body">
            <DefaultDocPipeline currentStage={jobs.find((j) => j.status === "running")?.current_stage ?? undefined} />
          </div>
        </div>
      )}

      {/* Job list */}
      {jobs.length === 0 ? (
        <EmptyState icon="⚙" title="暂无作业" description="提交数据接入后将在此显示作业进度" />
      ) : (
        <div className="table-frame">
          <div className="table-head">
            <div className="table-row" style={{ gridTemplateColumns: "140px 100px 120px 100px 100px 140px" }}>
              <span>作业ID</span>
              <span>类型</span>
              <span>关联对象</span>
              <span>当前阶段</span>
              <span>状态</span>
              <span>创建时间</span>
            </div>
          </div>
          {jobs.map((job) => (
            <div
              className={`table-row${hasActiveJobs ? " clickable" : ""}`}
              key={job.id}
              style={{ gridTemplateColumns: "140px 100px 120px 100px 100px 140px" }}
            >
              <span className="mono-cell">{shortId(job.id)}</span>
              <span>{job.job_type}</span>
              <span className="mono-cell">{shortId(job.raw_object_id)}</span>
              <span>{job.current_stage ?? "-"}</span>
              <StatusLabel value={job.status} />
              <span className="text-sm text-muted">{formatDateTime(job.created_at)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Stages */}
      {stages.length > 0 && (
        <div className="table-frame">
          <div className="table-head">
            <div className="table-row" style={{ gridTemplateColumns: "140px 120px 1fr 100px 140px" }}>
              <span>阶段ID</span>
              <span>阶段名</span>
              <span>详情</span>
              <span>状态</span>
              <span>时间</span>
            </div>
          </div>
          {stages.map((stage) => (
            <div
              className="table-row"
              key={stage.id}
              style={{ gridTemplateColumns: "140px 120px 1fr 100px 140px" }}
            >
              <span className="mono-cell">{shortId(stage.id)}</span>
              <span>{stage.stage_name}</span>
              <span className="text-sm text-muted truncate">
                {stage.failure_reason ?? JSON.stringify(stage.detail)}
              </span>
              <StatusLabel value={stage.status} />
              <span className="text-sm text-muted">
                {stage.started_at ? formatDateTime(stage.started_at) : "-"}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
