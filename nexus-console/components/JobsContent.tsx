"use client";

import { useState } from "react";
import { StatusLabel } from "@/components/StatusLabel";
import { PollingIndicator } from "@/components/PollingIndicator";
import { EmptyState } from "@/components/EmptyState";
import { formatDateTime, shortId, type Job, type JobStage } from "@/lib/api";

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

export function JobsContent({ jobs, stages }: { jobs: Job[]; stages: JobStage[] }) {
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [pollingState, setPollingState] = useState<"active" | "paused" | "error">("active");

  const hasActiveJobs = jobs.some((j) => j.status === "running" || j.status === "queued");
  const expandedJob = jobs.find((j) => j.id === expandedJobId);

  function toggleExpand(jobId: string) {
    setExpandedJobId((prev) => (prev === jobId ? null : jobId));
  }

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
        <EmptyState icon="⚙" title="暂无作业" description="提交数据接入后将自动创建作业" />
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
                          const stageRecord = jobStages.find((s) => s.stage_name === stage.key);
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

                      {/* Current stage info */}
                      {(() => {
                        const currentStage = PIPELINE_STAGES.find((s) => s.key === job.current_stage);
                        const currentStageRecord = jobStages.find((s) => s.stage_name === job.current_stage);
                        if (!currentStage) return null;
                        return (
                          <div className="pipeline-stage-info">
                            <strong>当前阶段：{currentStage.label}</strong>
                            {currentStageRecord?.started_at && (
                              <span className="text-xs text-muted">
                                开始于 {formatDateTime(currentStageRecord.started_at)}
                              </span>
                            )}
                            {currentStageRecord?.finished_at && (
                              <span className="text-xs text-muted">
                                完成于 {formatDateTime(currentStageRecord.finished_at)}
                              </span>
                            )}
                            {currentStageRecord?.failure_reason && (
                              <span className="text-xs" style={{ color: "var(--danger-600)" }}>
                                错误：{currentStageRecord.failure_reason}
                              </span>
                            )}
                            <span className="text-xs text-muted">
                              状态：<StatusLabel value={currentStageRecord?.status ?? job.status} />
                            </span>
                          </div>
                        );
                      })()}
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
