"use client";

import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { StatusLabel } from "@/components/StatusLabel";
import { PollingIndicator } from "@/components/PollingIndicator";
import { Button, Drawer, Table, Card, Tooltip } from "antd";
import { EyeOutlined, ReloadOutlined, StopOutlined } from "@ant-design/icons";
import { ConfirmButton } from "@/components/shared/ConfirmButton";
import { EmptyState } from "@/components/shared/EmptyState";
import { useOptimisticMutation } from "@/lib/useOptimisticMutation";
import { useElapsed } from "@/lib/useElapsed";
import { formatTime } from "@/lib/format-time";
import { shortId, postApiData, type Job, type JobStage } from "@/lib/api";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";

const PIPELINE_STAGES = [
  { key: "ingest_validate", label: "接入校验", desc: "校验原始数据的完整性、checksum 和格式，确保数据可被后续阶段处理。" },
  { key: "assetize", label: "资产化", desc: "创建或更新资产与资产版本锚点，锁定数据快照。" },
  { key: "parse", label: "文档解析", desc: "使用 MinerU 引擎解析文档内容，提取结构化文本、表格和图片。" },
  { key: "normalize", label: "标准化", desc: "LLM 语义提取 + 规则引擎回退校验，生成标准化文档或记录。" },
  { key: "ai_governance", label: "AI 治理", desc: "AI 驱动的分类、打标、质量评分与敏感信息脱敏处理。" },
  { key: "rule_guard", label: "规则质检", desc: "业务规则校验：schema 合规、字段白名单、置信度阈值判定。" },
  { key: "index", label: "索引", desc: "将治理通过的标准化资产索引到 RAGFlow 知识库，支持检索与问答。" },
  { key: "complete", label: "完成", desc: "全部阶段执行完毕，资产已就绪可用。" },
];

type StageIcon = "done" | "active" | "pending" | "failed";

function getStageStatus(stageName: string, job: Job, stages: JobStage[]): StageIcon {
  const stageRecord = [...stages]
    .reverse()
    .find((s) => s.stage_name === stageName);
  if (stageRecord) {
    if (stageRecord.status === "succeeded" || stageRecord.status === "skipped" || stageRecord.status === "partial") return "done";
    if (stageRecord.status === "failed") return "failed";
    if (stageRecord.status === "running") return "active";
  }

  if (job.status === "succeeded") return "done";
  if ((job.status === "failed" || job.status === "dead_lettered") && stageName === (job.current_stage ?? "")) return "failed";
  if ((job.status === "running" || job.status === "queued") && stageName === (job.current_stage ?? "")) return "active";
  return "pending";
}

const STAGE_DOT_COLORS: Record<StageIcon, string> = {
  done: "var(--success-600)",
  active: "var(--brand-600)",
  pending: "var(--gray-300)",
  failed: "var(--danger-600)",
};

const STAGE_DOT_TITLES: Record<StageIcon, string> = {
  done: "已完成",
  active: "进行中",
  pending: "待执行",
  failed: "失败",
};

interface JobsContentProps {
  jobs: Job[];
  stages: JobStage[];
  rawObjectNames: Map<string, string>;
  totalCount: number;
  currentPage: number;
  pageSize: number;
}

export function JobsContent({ jobs: initialJobs, stages, rawObjectNames, totalCount, currentPage, pageSize: currentPageSize }: JobsContentProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [jobs, setJobs] = useState<Job[]>(initialJobs);
  const [drawerJob, setDrawerJob] = useState<Job | null>(null);
  const [pollingState, setPollingState] = useState<"active" | "paused" | "error">("active");
  const [lastRefreshAt, setLastRefreshAt] = useState<Date | null>(null);
  const isInitialRender = useRef(true);

  // Sync jobs from server-side prop updates (router.refresh re-fetches server component)
  useEffect(() => {
    setJobs(initialJobs);
    if (isInitialRender.current) {
      isInitialRender.current = false;
    } else {
      setLastRefreshAt(new Date());
    }
  }, [initialJobs]);

  const hasActiveJobs = jobs.some((j) => j.status === "running" || j.status === "queued");

  // Auto-refresh every 15 seconds while polling is active and there are active jobs
  useEffect(() => {
    if (pollingState !== "active" || !hasActiveJobs) return;
    const id = setInterval(() => {
      router.refresh();
    }, 15_000);
    return () => clearInterval(id);
  }, [pollingState, hasActiveJobs, router]);

  const stagesByJob = useMemo(() => {
    const map = new Map<string, JobStage[]>();
    for (const s of stages) {
      const list = map.get(s.job_id) ?? [];
      list.push(s);
      map.set(s.job_id, list);
    }
    return map;
  }, [stages]);

  const retryMutation = useOptimisticMutation({
    mutationFn: (jobId: string) => postApiData(`/api/jobs/${jobId}/retry`, {}),
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

  const cancelMutation = useOptimisticMutation({
    mutationFn: (jobId: string) => postApiData(`/api/jobs/${jobId}/cancel`, {}),
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

  const drawerStages = drawerJob ? (stagesByJob.get(drawerJob.id) ?? []) : [];

  // ── URL-driven pagination (same pattern as RawLedgerContent) ──
  const buildUrl = useCallback(
    (overrides: Record<string, string | undefined>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(overrides)) {
        if (v) params.set(k, v);
        else params.delete(k);
      }
      const qs = params.toString();
      return qs ? `${pathname}?${qs}` : pathname;
    },
    [pathname, searchParams],
  );

  const handleTableChange = useCallback(
    (pagination: { current?: number; pageSize?: number }) => {
      const overrides: Record<string, string | undefined> = {};
      if (pagination.current && pagination.current > 1) {
        overrides.page = String(pagination.current);
      } else {
        overrides.page = undefined;
      }
      if (pagination.pageSize && pagination.pageSize !== DEFAULT_PAGE_SIZE) {
        overrides.pageSize = String(pagination.pageSize);
      } else {
        overrides.pageSize = undefined;
      }
      router.replace(buildUrl(overrides));
    },
    [router, buildUrl],
  );

  const handleManualRefresh = useCallback(() => {
    router.refresh();
  }, [router]);

  // Compute relative "last update" display
  const lastUpdateDisplay = lastRefreshAt ? formatTime(lastRefreshAt.toISOString()).display : null;

  return (
    <>
      {hasActiveJobs && (
        <PollingIndicator
          state={pollingState}
          intervalSeconds={15}
          lastUpdate={lastUpdateDisplay ?? undefined}
          onRefresh={handleManualRefresh}
          onToggle={() => setPollingState((s) => (s === "active" ? "paused" : "active"))}
        />
      )}

      {jobs.length === 0 ? (
        <EmptyState title="暂无作业" hint="作业由数据接入提交后自动创建" size="small" />
      ) : (
        <Card
          title="作业列表"
          extra={
            <span className="text-xs text-muted">
              共 {totalCount} 个作业 · {jobs.filter(j => j.status === "running" || j.status === "queued").length} 活跃
            </span>
          }
        >
          <Table
            rowKey="id"
            dataSource={jobs}
            size="small"
            pagination={{
              current: currentPage,
              pageSize: currentPageSize,
              total: totalCount,
              showSizeChanger: true,
              showTotal: (total) => `共 ${total} 个作业`,
              pageSizeOptions: ["10", "20", "50"],
            }}
            onChange={handleTableChange}
          >
            <Table.Column
              title=""
              width={40}
              render={(_: unknown, r: Job) => (
                <Tooltip title="查看详情">
                  <Button
                    type="text"
                    size="small"
                    icon={<EyeOutlined />}
                    onClick={(e) => { e.stopPropagation(); setDrawerJob(r); }}
                  />
                </Tooltip>
              )}
            />
            <Table.Column
              title="作业ID"
              width={140}
              render={(_: unknown, r: Job) => <span className="mono-cell">{shortId(r.id)}</span>}
            />
            <Table.Column title="类型" dataIndex="job_type" width={100} />
            <Table.Column
              title="关联对象"
              width={180}
              ellipsis
              render={(_: unknown, r: Job) => {
                const name = r.raw_object_id ? (rawObjectNames.get(r.raw_object_id) ?? shortId(r.raw_object_id)) : "-";
                return (
                  <Tooltip title={name}>
                    <span className="text-sm">{name}</span>
                  </Tooltip>
                );
              }}
            />
            <Table.Column
              title="阶段进度"
              width={200}
              render={(_: unknown, r: Job) => {
                const jobStages = stagesByJob.get(r.id) ?? [];
                return (
                  <div className="flex items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
                    {PIPELINE_STAGES.slice(0, -1).map((stage) => {
                      const status = getStageStatus(stage.key, r, jobStages);
                      return (
                        <Tooltip key={stage.key} title={`${stage.label} — ${STAGE_DOT_TITLES[status]}`}>
                          <span
                            className="inline-block rounded-full"
                            style={{
                              width: 10,
                              height: 10,
                              backgroundColor: STAGE_DOT_COLORS[status],
                              margin: "0 1px",
                              transition: "background-color var(--transition-fast)",
                            }}
                          />
                        </Tooltip>
                      );
                    })}
                  </div>
                );
              }}
            />
            <Table.Column
              title="当前阶段"
              width={100}
              render={(_: unknown, r: Job) => {
                const label = PIPELINE_STAGES.find((s) => s.key === r.current_stage)?.label ?? r.current_stage ?? "-";
                return <span className="text-sm">{label}</span>;
              }}
            />
            <Table.Column
              title="状态"
              width={100}
              render={(_: unknown, r: Job) => <StatusLabel value={r.status} />}
            />
            <Table.Column
              title="创建时间"
              width={140}
              render={(_: unknown, r: Job) => {
                const t = formatTime(r.created_at);
                return (
                  <time dateTime={t.iso} title={t.iso} className="text-sm text-muted">
                    {t.display}
                  </time>
                );
              }}
            />
          </Table>
        </Card>
      )}

      {/* ── Detail Drawer ── */}
      <Drawer
        title={drawerJob ? `作业详情 — ${shortId(drawerJob.id)}` : ""}
        open={drawerJob !== null}
        onClose={() => setDrawerJob(null)}
        width={520}
        destroyOnClose
      >
        {drawerJob && (
          <div className="space-y-4">
            {/* Summary Card */}
            <Card size="small" title="基本信息">
              <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
                <div>
                  <div className="text-xs text-text-muted mb-0.5">作业类型</div>
                  <div className="font-medium">{drawerJob.job_type}</div>
                </div>
                <div>
                  <div className="text-xs text-text-muted mb-0.5">状态</div>
                  <StatusLabel value={drawerJob.status} />
                </div>
                <div>
                  <div className="text-xs text-text-muted mb-0.5">关联对象</div>
                  <div className="font-medium truncate">
                    {drawerJob.raw_object_id
                      ? (rawObjectNames.get(drawerJob.raw_object_id) ?? shortId(drawerJob.raw_object_id))
                      : "-"}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-text-muted mb-0.5">重试次数</div>
                  <div className="font-medium tabular-nums">{drawerJob.retry_count}</div>
                </div>
                <div>
                  <div className="text-xs text-text-muted mb-0.5">创建时间</div>
                  <div className="font-medium">{formatTime(drawerJob.created_at).display}</div>
                </div>
                {drawerJob.failure_reason && (
                  <div className="col-span-2 mt-1 rounded-md bg-danger-bg px-3 py-2">
                    <div className="text-xs text-text-muted mb-0.5">失败原因</div>
                    <div className="text-sm text-danger-text font-medium">{drawerJob.failure_reason}</div>
                  </div>
                )}
              </div>
            </Card>

            {/* Stage Timeline Card */}
            <Card
              size="small"
              title="阶段执行时间线"
              extra={
                <span className="text-xs text-text-muted">
                  {drawerStages.filter((s) => s.status === "succeeded").length}/{PIPELINE_STAGES.length - 1} 完成
                </span>
              }
            >
              <StageTimeline drawerJob={drawerJob} drawerStages={drawerStages} />
            </Card>

            {/* Actions */}
            <div className="flex gap-2">
              {(drawerJob.status === "failed" || drawerJob.status === "dead_lettered") && (
                <ConfirmButton
                  title="重试作业"
                  description="重新将作业加入队列。如果失败原因未解决，作业可能再次失败。"
                  severity="warning"
                  buttonProps={{ size: "small", type: "primary", icon: <ReloadOutlined /> }}
                  onConfirm={() => retryMutation.execute(drawerJob.id)}
                >
                  重试
                </ConfirmButton>
              )}
              {(drawerJob.status === "running" || drawerJob.status === "queued") && (
                <ConfirmButton
                  title="取消作业"
                  description="终止当前作业的执行。已完成的阶段不会回溯。"
                  severity="warning"
                  danger
                  buttonProps={{ size: "small", icon: <StopOutlined /> }}
                  onConfirm={() => cancelMutation.execute(drawerJob.id)}
                >
                  取消
                </ConfirmButton>
              )}
            </div>
          </div>
        )}
      </Drawer>
    </>
  );
}

// ── Stage timeline (card content) ──

function stageStatusLabel(status: StageIcon): string {
  if (status === "done") return "succeeded";
  if (status === "active") return "running";
  if (status === "failed") return "failed";
  return "pending";
}

const STAGE_LINE: Record<StageIcon, string> = {
  done: "var(--success-500)",
  active: "var(--brand-500)",
  pending: "var(--gray-200)",
  failed: "var(--danger-500)",
};

function StageTimeline({
  drawerJob,
  drawerStages,
}: {
  drawerJob: Job;
  drawerStages: JobStage[];
}) {
  return (
    <div>
      {PIPELINE_STAGES.map((stage, idx) => {
        const status = getStageStatus(stage.key, drawerJob, drawerStages);
        const record = drawerStages.find((s) => s.stage_name === stage.key);
        const isLast = idx === PIPELINE_STAGES.length - 1;
        const isCurrent = status === "active";
        const isFailed = status === "failed";
        const hasTiming = !!(record && (record.started_at || record.finished_at));

        return (
          <StageTimelineItem
            key={stage.key}
            stage={stage}
            status={status}
            record={record}
            isLast={isLast}
            isHighlighted={isCurrent || isFailed}
            hasTiming={hasTiming}
          />
        );
      })}
    </div>
  );
}

function StageTimelineItem({
  stage,
  status,
  record,
  isLast,
  isHighlighted,
  hasTiming,
}: {
  stage: (typeof PIPELINE_STAGES)[number];
  status: StageIcon;
  record: JobStage | undefined;
  isLast: boolean;
  isHighlighted: boolean;
  hasTiming: boolean;
}) {
  const { elapsed, isRunning } = useElapsed({
    startedAt: record?.started_at ?? null,
    finishedAt: record?.finished_at ?? null,
  });

  return (
    <div className="flex gap-3">
      {/* Left rail: dot + vertical line */}
      <div className="flex flex-col items-center pt-0.5" style={{ width: 12, flexShrink: 0 }}>
        <span
          className="inline-block rounded-full flex-shrink-0"
          style={{
            width: 12,
            height: 12,
            backgroundColor: STAGE_DOT_COLORS[status],
            boxShadow: isHighlighted
              ? `0 0 0 3px ${STAGE_DOT_COLORS[status]}22`
              : undefined,
            transition: "box-shadow var(--transition-fast)",
          }}
        />
        {!isLast && (
          <span
            className="flex-1 w-px min-h-4"
            style={{
              backgroundColor: STAGE_LINE[status],
              opacity: isHighlighted ? 1 : 0.5,
            }}
          />
        )}
      </div>

      {/* Content */}
      <div className={`flex-1 min-w-0 ${isLast ? "" : "pb-4"}`}>
        {/* Header row */}
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-semibold">{stage.label}</span>
          <StatusLabel value={stageStatusLabel(status)} label={STAGE_DOT_TITLES[status]} />
        </div>

        {/* Description */}
        <div className="text-xs text-text-muted mb-2 leading-relaxed">{stage.desc}</div>

        {/* Timing + failure */}
        {hasTiming && record && (
          <div className={`rounded-md px-3 py-2 text-xs ${isHighlighted ? "bg-surface-sunken" : ""}`}>
            {record.started_at && (
              <div className="flex items-baseline gap-2 text-text-muted">
                <span className="flex-shrink-0">开始</span>
                <time dateTime={record.started_at}>{formatTime(record.started_at).display}</time>
                {isRunning && (
                  <span className="text-brand-600 font-medium">已运行 {elapsed}</span>
                )}
              </div>
            )}
            {record.finished_at && (
              <div className="flex items-baseline gap-2 text-text-muted mt-0.5">
                <span className="flex-shrink-0">完成</span>
                <time dateTime={record.finished_at}>{formatTime(record.finished_at).display}</time>
                <span className="text-text-muted">耗时 {elapsed}</span>
              </div>
            )}
            {record.failure_reason && (
              <div className="text-danger-600 mt-1 font-medium">错误：{record.failure_reason}</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
