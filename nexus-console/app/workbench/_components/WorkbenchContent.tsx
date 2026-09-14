"use client";

import Link from "next/link";
import { Alert, Button, Card, Progress, Statistic, Tag } from "antd";
import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
} from "@ant-design/icons";

import { UnifiedActivityFeed } from "./UnifiedActivityFeed";
import type { WorkbenchData } from "../page";

const EM_DASH = "—";

function qualityTone(score: number): "danger" | "warning" | "success" {
  if (score < 60) return "danger";
  if (score < 80) return "warning";
  return "success";
}

function qualityColorVar(score: number): string {
  const tone = qualityTone(score);
  return tone === "danger"
    ? "var(--danger-600)"
    : tone === "warning"
      ? "var(--warning-600)"
      : "var(--success-600)";
}

export function WorkbenchContent({ data }: { data: WorkbenchData }) {
  const {
    assetCount,
    refCount,
    succeededJobs,
    failedJobs,
    runningJobs,
    queuedJobs,
    pipelineHealth,
    governanceCoverage,
    autoAdopted,
    qualityPass,
    avgQuality,
    attentionItems,
    executionDurationTop,
    queueTrend,
    batches,
    audits,
    dataSourceById,
  } = data;

  const hasQuality = avgQuality > 0;
  const maxDuration = Math.max(...executionDurationTop.map((item) => item.duration_seconds), 1);
  const maxQueued = Math.max(...queueTrend.map((item) => item.queued_count), 1);
  const maxWait = Math.max(...queueTrend.map((item) => item.average_wait_seconds), 1);

  function formatDuration(seconds: number): string {
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  }

  return (
    <>
      {/* ── Hero Strip ─── Hero (2 cols) + 3 Secondary ─────────────────── */}
      <div className="workbench-hero-bg mb-5 grid gap-4 md:grid-cols-2 lg:grid-cols-5">
        {/* Hero —— 流水线健康度（运营注意力锚点）*/}
        <div className="metric-hero lg:col-span-2">
          <div className="metric-label">流水线健康度</div>
          <div className="flex items-baseline gap-3">
            <span
              className="metric-value text-num"
              style={{ color: qualityColorVar(pipelineHealth) }}
            >
              {pipelineHealth}
              <span className="ml-0.5 text-xl font-medium">%</span>
            </span>
            <Tag
              color={pipelineHealth >= 80 ? "success" : pipelineHealth >= 60 ? "warning" : "error"}
              className="text-[11px]"
            >
              {pipelineHealth >= 80 ? "健康" : pipelineHealth >= 60 ? "需关注" : "异常"}
            </Tag>
          </div>
          <div className="metric-sub text-num">
            {succeededJobs} 成功 · {runningJobs} 运行 ·{" "}
            <span className={failedJobs > 0 ? "text-danger font-medium" : ""}>
              {failedJobs} 失败
            </span>
          </div>
        </div>

        {/* Secondary 1 —— 数据资产 */}
        <Card size="small" className="metric-secondary">
          <Statistic title="数据资产总量" value={assetCount} />
          <div className="text-text-muted text-num mt-1 text-xs">已标准化 {refCount} 个引用</div>
        </Card>

        {/* Secondary 2 —— AI 治理覆盖率（管理员视角：AI 自动化占比） */}
        <Card size="small" className="metric-secondary">
          <Statistic title="AI 治理覆盖率" value={governanceCoverage} suffix="%" />
          <div className="text-text-muted text-num mt-1 text-xs">{autoAdopted} 项已自动采纳</div>
        </Card>

        {/* Secondary 3 —— 数据质量均分（空态用 em-dash）*/}
        <Card size="small" className="metric-secondary">
          {hasQuality ? (
            <Statistic
              title="数据质量均分"
              value={avgQuality}
              styles={{ content: { color: qualityColorVar(avgQuality) } }}
            />
          ) : (
            <>
              <div className="text-text-secondary mb-2 text-xs font-medium tracking-wide uppercase">
                数据质量均分
              </div>
              <div className="text-text-muted text-2xl font-semibold">{EM_DASH}</div>
            </>
          )}
          <div className="text-text-muted text-num mt-1 text-xs">
            {hasQuality ? `已评估 ${qualityPass} 项通过` : "暂无评分数据"}
          </div>
        </Card>
      </div>

      {/* ── Attention Zone —— 告警 + 直达操作按钮（闭环） ─────────────── */}
      {attentionItems.length === 0 ? (
        <Alert
          type="success"
          showIcon
          icon={<CheckCircleOutlined />}
          title="系统运行正常，无需关注"
          className="mb-5"
        />
      ) : (
        <div className="mb-5 grid gap-2">
          {attentionItems.map((item, i) => (
            <Alert
              key={i}
              type={item.tone === "danger" ? "error" : "warning"}
              showIcon
              icon={item.tone === "danger" ? <CloseCircleOutlined /> : <WarningOutlined />}
              title={<span className="font-medium">{item.text}</span>}
              action={
                <Link href={item.href}>
                  <Button
                    size="small"
                    type={item.tone === "danger" ? "primary" : "default"}
                    danger={item.tone === "danger"}
                    icon={<ArrowRightOutlined />}
                    iconPlacement="end"
                  >
                    {item.actionLabel}
                  </Button>
                </Link>
              }
            />
          ))}
        </div>
      )}

      {/* ── Resource Insights —— 执行时长与队列趋势 ───────────────────── */}
      <div className="mb-5 grid gap-4 lg:grid-cols-2">
        <Card
          title="任务执行时长 TOP 10"
          size="small"
          extra={<span className="text-text-muted text-xs">近 6 个月</span>}
        >
          {executionDurationTop.length === 0 ? (
            <div className="text-text-muted py-8 text-center text-sm">暂无可用执行时长数据</div>
          ) : (
            <div className="grid gap-3">
              {executionDurationTop.map((item) => (
                <div
                  key={item.job_id}
                  className="grid grid-cols-[104px_1fr_auto] items-center gap-2"
                >
                  <div className="min-w-0">
                    <div className="truncate text-xs font-medium" title={item.job_id}>
                      {item.job_type}
                    </div>
                    <div className="text-text-muted truncate font-mono text-[10px]">
                      {item.job_id.slice(0, 8)}
                    </div>
                  </div>
                  <Progress
                    percent={Math.round((item.duration_seconds / maxDuration) * 100)}
                    showInfo={false}
                    size="small"
                    strokeColor="var(--brand-600)"
                  />
                  <div className="text-num text-text-secondary text-xs">
                    {formatDuration(item.duration_seconds)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card
          title="任务排队趋势"
          size="small"
          extra={
            <span className="text-text-muted text-xs">
              当前排队 {queuedJobs} · 近 6 个月入队量 / 平均等待
            </span>
          }
        >
          <div className="mb-3 flex items-center gap-4 text-xs">
            <span className="flex items-center gap-1.5">
              <i className="bg-brand-600 h-2 w-2 rounded-full" />
              入队量
            </span>
            <span className="flex items-center gap-1.5">
              <i className="bg-warning-600 h-2 w-2 rounded-full" />
              平均等待
            </span>
          </div>
          <div className="grid grid-cols-6 items-end gap-2">
            {queueTrend.map((item) => (
              <div key={item.month} className="grid min-w-0 gap-1 text-center">
                <div className="border-line-light relative flex h-28 items-end justify-center gap-1 border-b">
                  <div
                    className="bg-brand-600/80 w-3 rounded-t"
                    style={{ height: `${Math.max(4, (item.queued_count / maxQueued) * 100)}%` }}
                    title={`${item.month} 入队 ${item.queued_count}`}
                  />
                  <div
                    className="bg-warning-600/80 w-3 rounded-t"
                    style={{
                      height: `${Math.max(4, (item.average_wait_seconds / maxWait) * 100)}%`,
                    }}
                    title={`${item.month} 平均等待 ${formatDuration(item.average_wait_seconds)}`}
                  />
                </div>
                <div className="text-text-muted text-[10px]">{item.month.slice(5)}月</div>
                <div className="text-num text-text-secondary text-[10px]">
                  {item.queued_count} · {formatDuration(item.average_wait_seconds)}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* ── Unified Activity Feed —— 接入 / 审计 / 全部 一站式视图 ───── */}
      <Card
        size="small"
        title="活动流"
        extra={
          <Link href="/iam-audit" className="text-brand text-xs">
            完整审计 →
          </Link>
        }
      >
        <UnifiedActivityFeed
          batches={batches}
          audits={audits}
          dataSourceById={dataSourceById}
          pageSize={10}
        />
      </Card>
    </>
  );
}
