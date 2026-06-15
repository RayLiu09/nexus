"use client";

import Link from "next/link";
import { Alert, Button, Card, Progress, Statistic, Tag, Tooltip } from "antd";
import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  RiseOutlined,
  WarningOutlined,
} from "@ant-design/icons";

import { DecisionList } from "./DecisionList";
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
    grCount,
    succeededJobs,
    failedJobs,
    runningJobs,
    pipelineHealth,
    governanceCoverage,
    autoAdopted,
    reviewRequired,
    qualityPass,
    qualityWarning,
    qualityFail,
    avgQuality,
    attentionItems,
    rawCount,
    funnelSteps,
    batches,
    audits,
    dataSourceById,
    governanceRuns,
    processingBatches,
  } = data;

  const hasQuality = avgQuality > 0;

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

        {/* Secondary 2 —— AI 治理覆盖率 */}
        <Card size="small" className="metric-secondary">
          <Statistic title="AI 治理覆盖率" value={governanceCoverage} suffix="%" />
          <div className="text-text-muted text-num mt-1 text-xs">
            {autoAdopted} 自动 · {reviewRequired} 待复核
          </div>
        </Card>

        {/* Secondary 3 —— 数据质量均分（空态用 em-dash）*/}
        <Card size="small" className="metric-secondary">
          {hasQuality ? (
            <Statistic
              title="数据质量均分"
              value={avgQuality}
              valueStyle={{ color: qualityColorVar(avgQuality) }}
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
            {hasQuality
              ? `通过 ${qualityPass} · 预警 ${qualityWarning} · 未过 ${qualityFail}`
              : "暂无评分数据"}
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
                    iconPosition="end"
                  >
                    {item.actionLabel}
                  </Button>
                </Link>
              }
            />
          ))}
        </div>
      )}

      {/* ── Focus Modules ── 漏斗 + 决策待办 ─────────────────────────── */}
      <div className="mb-5 grid gap-5 lg:grid-cols-[3fr_2fr]">
        {/* Pipeline Funnel —— 进度条锁 100%，超额数值用 chip 旁挂 */}
        <Card title="主链路漏斗" size="small">
          <div className="grid gap-3">
            {funnelSteps.map((step, i) => {
              const rawPct = rawCount > 0 ? (step.value / rawCount) * 100 : 0;
              const cappedPct = Math.min(100, Math.round(rawPct));
              const overage = rawPct > 100 ? Math.round(rawPct - 100) : 0;
              const convRate =
                i > 0 && funnelSteps[i - 1].value > 0
                  ? Math.round((step.value / funnelSteps[i - 1].value) * 100)
                  : null;
              const isEmpty = step.value === 0;
              return (
                <div key={step.label}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className={isEmpty ? "text-text-muted" : ""}>{step.label}</span>
                    <span className={`text-num ${isEmpty ? "text-text-muted" : "font-semibold"}`}>
                      {step.value}
                      {convRate !== null && (
                        <span className="text-text-muted ml-1.5 text-xs">({convRate}%)</span>
                      )}
                      {overage > 0 && (
                        <Tooltip
                          title={`引用数 ${step.value} 超出原始对象 ${rawCount}，包含多版本或回溯生成`}
                        >
                          <Tag color="processing" className="ml-2 text-[11px]">
                            <RiseOutlined className="mr-0.5" />+{overage}%
                          </Tag>
                        </Tooltip>
                      )}
                    </span>
                  </div>
                  <Progress
                    percent={cappedPct}
                    showInfo={false}
                    size="small"
                    strokeColor={isEmpty ? "var(--line-strong)" : "var(--brand-gradient)"}
                  />
                </div>
              );
            })}
          </div>
        </Card>

        {/* Decision Queue */}
        <Card
          title="决策待办"
          size="small"
          extra={
            <Link href="/governance" className="text-brand text-xs">
              查看全部 →
            </Link>
          }
        >
          <DecisionList
            items={governanceRuns
              .filter(
                (gr) =>
                  gr.adoption_status === "review_required" ||
                  gr.adoption_status === "pending_rule_guardrail",
              )
              .slice(0, 5)}
          />
        </Card>
      </div>

      {/* ── Running Status —— 满宽 3 列 ──────────────────────────────── */}
      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Card size="small" className="metric-secondary">
          <Statistic
            title="运行中作业"
            value={runningJobs}
            valueStyle={runningJobs === 0 ? { color: "var(--text-muted)" } : undefined}
          />
        </Card>
        <Card size="small" className="metric-secondary">
          <Statistic
            title="处理中批次"
            value={processingBatches}
            valueStyle={processingBatches === 0 ? { color: "var(--text-muted)" } : undefined}
          />
        </Card>
        <Card size="small" className="metric-secondary">
          <Statistic
            title="治理队列"
            value={grCount}
            valueStyle={grCount === 0 ? { color: "var(--text-muted)" } : undefined}
          />
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
