"use client";

import Link from "next/link";
import { Card, Statistic, Alert, Progress, Timeline } from "antd";
import {
  CheckCircleOutlined,
  WarningOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";
import { formatTime } from "@/lib/format-time";
import { BatchList } from "./BatchList";
import { DecisionList } from "./DecisionList";
import type { WorkbenchData } from "../page";

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
    recentAudits,
    batches,
    governanceRuns,
    processingBatches,
  } = data;

  return (
    <>
      {/* Hero Strip */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-5">
        <Card size="small">
          <Statistic title="数据资产总量" value={assetCount} />
          <div className="text-text-muted text-xs mt-1">已标准化 {refCount} 个引用</div>
        </Card>
        <Card
          size="small"
          className={pipelineHealth < 80 ? "border-warning" : "border-success"}
        >
          <Statistic
            title="流水线健康度"
            value={pipelineHealth}
            suffix="%"
            valueStyle={{ color: pipelineHealth < 80 ? "var(--warning-600)" : "var(--success-600)" }}
          />
          <div className="text-text-muted text-xs mt-1">
            {succeededJobs} 成功 · {runningJobs} 运行 · {failedJobs} 失败
          </div>
        </Card>
        <Card size="small">
          <Statistic
            title="AI 治理覆盖率"
            value={governanceCoverage}
            suffix="%"
          />
          <div className="text-text-muted text-xs mt-1">
            {autoAdopted} 自动采纳 · {reviewRequired} 待复核
          </div>
        </Card>
        <Card
          size="small"
          className={
            avgQuality < 60 ? "border-danger" : avgQuality < 80 ? "border-warning" : "border-success"
          }
        >
          <Statistic
            title="数据质量均分"
            value={avgQuality || "-"}
            valueStyle={{
              color: avgQuality < 60
                ? "var(--danger-600)"
                : avgQuality < 80
                  ? "var(--warning-600)"
                  : "var(--success-600)",
            }}
          />
          <div className="text-text-muted text-xs mt-1">
            通过 {qualityPass} · 预警 {qualityWarning} · 未过 {qualityFail}
          </div>
        </Card>
      </div>

      {/* Attention Zone */}
      {attentionItems.length === 0 ? (
        <Alert
          type="success"
          showIcon
          icon={<CheckCircleOutlined />}
          title="系统运行正常，无需关注"
          className="mb-5"
        />
      ) : (
        <div className="grid gap-2 mb-5">
          {attentionItems.map((item, i) => (
            <Alert
              key={i}
              type={item.tone === "danger" ? "error" : "warning"}
              showIcon
              icon={item.tone === "danger" ? <CloseCircleOutlined /> : <WarningOutlined />}
              title={
                <Link href={item.href} className="text-inherit no-underline">
                  {item.text} →
                </Link>
              }
            />
          ))}
        </div>
      )}

      {/* Main Grid */}
      <div className="grid gap-5 lg:grid-cols-[3fr_2fr]">
        {/* Left Column */}
        <div className="grid gap-4">
          {/* Pipeline Funnel */}
          <Card title="主链路漏斗" size="small">
            <div className="grid gap-3">
              {funnelSteps.map((step, i) => {
                const pct = rawCount > 0 ? Math.round((step.value / rawCount) * 100) : 0;
                const convRate =
                  i > 0 && funnelSteps[i - 1].value > 0
                    ? Math.round((step.value / funnelSteps[i - 1].value) * 100)
                    : null;
                return (
                  <div key={step.label}>
                    <div className="flex justify-between text-sm mb-1">
                      <span>{step.label}</span>
                      <span className="font-semibold">
                        {step.value}
                        {convRate !== null && (
                          <span className="text-text-muted text-xs ml-1.5">({convRate}%)</span>
                        )}
                      </span>
                    </div>
                    <Progress
                      percent={pct}
                      showInfo={false}
                      size="small"
                      strokeColor="var(--brand-gradient)"
                    />
                  </div>
                );
              })}
            </div>
          </Card>

          {/* Recent Activity */}
          <Card title="最近活动" size="small">
            {recentAudits.length === 0 ? (
              <div className="text-text-muted text-sm text-center py-5">暂无审计事件</div>
            ) : (
              <Timeline
                items={recentAudits.map((audit) => {
                  const { display, iso } = formatTime(audit.created_at);
                  return {
                    children: (
                      <div>
                        <time dateTime={iso} title={iso} className="text-text-muted text-xs block">
                          {display}
                        </time>
                        <span className="font-medium text-sm">{audit.event_type}</span>
                        {audit.actor_id && (
                          <span className="text-text-secondary text-xs ml-1.5">
                            by {audit.actor_id.slice(0, 8)}
                          </span>
                        )}
                      </div>
                    ),
                  };
                })}
              />
            )}
          </Card>
        </div>

        {/* Right Column */}
        <div className="grid gap-4 content-start">
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

          {/* Running Status */}
          <div className="grid grid-cols-3 gap-3">
            <Card size="small">
              <Statistic title="运行中作业" value={runningJobs} />
            </Card>
            <Card size="small">
              <Statistic title="处理中批次" value={processingBatches} />
            </Card>
            <Card size="small">
              <Statistic title="治理队列" value={grCount} />
            </Card>
          </div>

          {/* Batch Progress */}
          <Card
            title="最近批次"
            size="small"
            extra={
              <Link href="/ingest" className="text-brand text-xs">
                接入仪表盘 →
              </Link>
            }
          >
            <BatchList batches={batches.slice(0, 4)} />
          </Card>
        </div>
      </div>
    </>
  );
}
