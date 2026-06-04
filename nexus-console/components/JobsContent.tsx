"use client";

import { useState } from "react";
import { StatusLabel } from "@/components/StatusLabel";
import { PollingIndicator } from "@/components/PollingIndicator";
import { Empty } from "antd";
import { ConfirmButton } from "@/components/shared/ConfirmButton";
import { useOptimisticMutation } from "@/lib/useOptimisticMutation";
import { useElapsed } from "@/lib/useElapsed";
import { formatDateTime, shortId, postApiData, type Job, type JobStage } from "@/lib/api";

const PIPELINE_STAGES = [
  { key: "ingest_validate", label: "接入校验" },
  { key: "document_parse", label: "文档解析" },
  { key: "assetize", label: "资产化" },
  { key: "normalize", label: "标准化" },
  { key: "ai_governance", label: "AI 治理" },
  { key: "rule_guard", label: "规则质检" },
  { key: "index", label: "索引" },
  { key: "complete", label: "完成" }
];

function getStageStatus(stageName: string, job: Job, stages: JobStage[]): "done" | "active" | "pending" | "failed" {
  const currentIdx = PIPELINE_STAGES.findIndex((s) => s.key === job.current_stage);
  const thisIdx = PIPELINE_STAGES.findIndex((s) => s.key === stageName);

  if (job.status === "failed" && stageName === (job.current_stage ?? "")) return "failed";

  const stageRecord = stages.find((s) => s.stage_name === stageName);
  if (stageRecord) {
    if (stageRecord.status === "succeeded") return "done";
    if (stageRecord.status === "failed") return "failed";
    if (stageRecord.status === "running") return "active";
  }

  if (job.status === "succeeded" && thisIdx <= PIPELINE_STAGES.length - 1) return "done";
  if (currentIdx >= 0 && thisIdx < currentIdx) return "done";
  if (thisIdx === currentIdx) return "active";
  return "pending";
}

export function JobsContent({ jobs: initialJobs, stages }: { jobs: Job[]; stages: JobStage[] }) {
  const [jobs, setJobs] = useState<Job[]>(initialJobs);
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [pollingState, setPollingState] = useState<"active" | "paused" | "error">("active");

  const hasActiveJobs = jobs.some((j) => j.status === "running" || j.status === "queued");

  function toggleExpand(jobId: string) {
    setExpandedJobId((prev) => (prev === jobId ? null : jobId));
  }

  // Optimistic retry: optimistically set to "queued", rollback on failure
  const retryMutation = useOptimisticMutation({
    mutationFn: (jobId: string) => postApiData(`/v1/jobs/${jobId}/retry`, {}),
    onMutate: (jobId: string) => {
      setJobs((prev) =>
        prev.map((j) => (j.id === jobId ? { ...j, status: "queued", failure_reason: null } : j)),
      );
    },
    rollback: (snapshot: unknown) => {
      setJobs(snapshot as Job[]);
    },
    getSnapshot: () => jobs,
    successMessage: "作业已重新入队",
  });

  // Optimistic cancel: optimistically set to "cancelled", rollback on failure
  const cancelMutation = useOptimisticMutation({
    mutationFn: (jobId: string) => postApiData(`/v1/jobs/${jobId}/cancel`, {}),
    onMutate: (jobId: string) => {
      setJobs((prev) =>
        prev.map((j) => (j.id === jobId ? { ...j, status: "cancelled" } : j)),
      );
    },
    rollback: (snapshot: unknown) => {
      setJobs(snapshot as Job[]);
    },
    getSnapshot: () => jobs,
    successMessage: "作业已取消",
  });

  return (
    <>
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

      {jobs.length === 0 ? (
        <Empty description="暂无作业" />
      ) : (
        <div className="card">
          <div className="card-header">
            <span className="card-title">作业列表</span>
            <span className="text-xs text-muted">{jobs.length} 个作业 · {jobs.filter(j => j.status === "running" || j.status === "queued").length} 活跃</span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            <div className="table-row table-head" style={{ gridTemplateColumns: "30px 140px 100px 1fr 100px 100px 140px" }}>
              <span />
              <span>作业ID</span>
              <span>类型</span>
              <span>关联对象</span>
              <span>当前阶段</span>
              <span>状态</span>
              <span>创建时间</span>
            </div>

            {jobs.map((job) => {
              const isExpanded = expandedJobId === job.id;
              const jobStages = stages.filter((s) => s.job_id === job.id);
              const currentStageLabel = PIPELINE_STAGES.find((s) => s.key === job.current_stage)?.label ?? job.current_stage ?? "-";

              return (
                <div key={job.id}>
                  {/* Job row */}
                  <div
                    className={`table-row job-row-expandable${isExpanded ? " expanded" : ""}`}
                    style={{ gridTemplateColumns: "30px 140px 100px 1fr 100px 100px 140px" }}
                    onClick={() => toggleExpand(job.id)}
                  >
                    <span style={{ fontSize: 12, transition: "transform var(--transition-fast)", transform: isExpanded ? "rotate(90deg)" : "" }}>
                      ▶
                    </span>
                    <span className="mono-cell">{shortId(job.id)}</span>
                    <span>{job.job_type}</span>
                    <span className="mono-cell">{shortId(job.raw_object_id)}</span>
                    <span className="text-sm">{currentStageLabel}</span>
                    <StatusLabel value={job.status} />
                    <span className="text-sm text-muted">{formatDateTime(job.created_at)}</span>
                  </div>

                  {/* Expanded pipeline panel */}
                  {isExpanded && (
                    <div className="job-expand-panel">
                      <div className="pipeline-flow">
                        {PIPELINE_STAGES.map((stage, idx) => {
                          const status = getStageStatus(stage.key, job, jobStages);
                          const stepNumber = idx + 1;

                          return (
                            <div key={stage.key} style={{ display: "flex", alignItems: "flex-start", gap: 0 }}>
                              <div className="pipeline-node">
                                <div className={`pipeline-node-dot ${status}`}>
                                  {status === "done" ? "✓" : status === "failed" ? "✗" : status === "active" ? "●" : stepNumber}
                                </div>
                                <span className="pipeline-node-label">{stage.label}</span>
                              </div>
                              {idx < PIPELINE_STAGES.length - 1 && (
                                <div className={`pipeline-connector ${status === "done" ? "done" : status === "active" ? "active" : ""}`} />
                              )}
                            </div>
                          );
                        })}
                      </div>

                      <CurrentStageInfo job={job} stages={jobStages} />

                      {/* Danger actions */}
                      {(job.status === "failed" || job.status === "dead_lettered") && (
                        <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                          <ConfirmButton
                            title="重试作业"
                            description="重新将作业加入队列。如果失败原因未解决，作业可能再次失败。"
                            severity="warning"
                            buttonProps={{ size: "small" }}
                            onConfirm={() => retryMutation.execute(job.id)}
                          >
                            重试
                          </ConfirmButton>
                        </div>
                      )}
                      {(job.status === "running" || job.status === "queued") && (
                        <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                          <ConfirmButton
                            title="取消作业"
                            description="终止当前作业的执行。已完成的阶段不会回溯。"
                            severity="warning"
                            danger
                            buttonProps={{ size: "small" }}
                            onConfirm={() => cancelMutation.execute(job.id)}
                          >
                            取消
                          </ConfirmButton>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}

// ── Current stage timing with live elapsed counter ──────────────────────

function CurrentStageInfo({ job, stages }: { job: Job; stages: JobStage[] }) {
  const currentStage = PIPELINE_STAGES.find((s) => s.key === job.current_stage);
  const record = stages.find((s) => s.stage_name === job.current_stage);
  const { elapsed, isRunning } = useElapsed({
    startedAt: record?.started_at ?? null,
    finishedAt: record?.finished_at ?? null,
  });

  if (!currentStage) return null;

  return (
    <div className="pipeline-stage-info">
      <strong>当前阶段：{currentStage.label}</strong>
      {record?.started_at && (
        <span className="text-xs text-muted">
          开始于 {formatDateTime(record.started_at)}
          {isRunning && (
            <span style={{ color: "var(--brand)", marginLeft: 6 }}>已运行 {elapsed}</span>
          )}
        </span>
      )}
      {record?.finished_at && (
        <span className="text-xs text-muted">
          完成于 {formatDateTime(record.finished_at)}（耗时 {elapsed}）
        </span>
      )}
      {record?.failure_reason && (
        <span className="text-xs" style={{ color: "var(--danger-600)" }}>
          错误：{record.failure_reason}
        </span>
      )}
      <span className="text-xs text-muted">
        状态：<StatusLabel value={record?.status ?? job.status} />
      </span>
    </div>
  );
}
