import { PageHeader } from "@/components/PageHeader";
import { ApiState } from "@/components/ApiState";
import { loadWorkbenchData } from "@/lib/console-data";
import type { AIGovernanceRun, AuditLog, IngestBatch } from "@/lib/api";
import { WorkbenchContent } from "./_components/WorkbenchContent";

export const dynamic = "force-dynamic";

export interface WorkbenchData {
  assetCount: number;
  refCount: number;
  jobCount: number;
  grCount: number;
  succeededJobs: number;
  failedJobs: number;
  runningJobs: number;
  pipelineHealth: number;
  governanceCoverage: number;
  autoAdopted: number;
  reviewRequired: number;
  qualityPass: number;
  qualityWarning: number;
  qualityFail: number;
  avgQuality: number;
  attentionItems: { tone: "danger" | "warning"; text: string; href: string }[];
  rawCount: number;
  batchCount: number;
  funnelSteps: { label: string; value: number }[];
  recentAudits: AuditLog[];
  batches: IngestBatch[];
  governanceRuns: AIGovernanceRun[];
  processingBatches: number;
}

export default async function WorkbenchPage() {
  const data = await loadWorkbenchData();

  const assetCount = data.assets.data.length;
  const refCount = data.normalizedRefs.data.length;
  const jobCount = data.jobs.data.length;
  const grCount = data.governanceRuns.data.length;

  const succeededJobs = data.jobs.data.filter((j) => j.status === "succeeded").length;
  const failedJobs = data.jobs.data.filter(
    (j) => j.status === "failed" || j.status === "dead_lettered",
  ).length;
  const runningJobs = data.jobs.data.filter(
    (j) => j.status === "running" || j.status === "queued",
  ).length;
  const pipelineHealth = jobCount > 0 ? Math.round((succeededJobs / jobCount) * 100) : 100;

  const governedRefIds = new Set(data.governanceRuns.data.map((gr) => gr.normalized_ref_id));
  const governanceCoverage = refCount > 0 ? Math.round((governedRefIds.size / refCount) * 100) : 0;
  const autoAdopted = data.governanceRuns.data.filter(
    (gr) => gr.adoption_status === "auto_adopted",
  ).length;
  const reviewRequired = data.governanceRuns.data.filter(
    (gr) =>
      gr.adoption_status === "review_required" || gr.adoption_status === "pending_rule_guardrail",
  ).length;

  let qualityPass = 0;
  let qualityWarning = 0;
  let qualityFail = 0;
  let qualitySumTotal = 0;
  let qualityCountTotal = 0;

  data.governanceRuns.data.forEach((gr) => {
    const qs = gr.quality_summary as Record<string, unknown> | null;
    const score =
      (qs?.overall_score as number) ??
      (qs?.quality_score as number) ??
      ((gr.ai_output as Record<string, unknown> | null)?.overall_score as number);
    if (typeof score === "number") {
      qualitySumTotal += score;
      qualityCountTotal += 1;
      if (score >= 80) qualityPass += 1;
      else if (score >= 60) qualityWarning += 1;
      else qualityFail += 1;
    }
  });
  const avgQuality = qualityCountTotal > 0 ? Math.round(qualitySumTotal / qualityCountTotal) : 0;

  const attentionItems: { tone: "danger" | "warning"; text: string; href: string }[] = [];
  if (failedJobs > 0)
    attentionItems.push({ tone: "danger", text: `${failedJobs} 个作业失败，需排查`, href: "/jobs" });
  if (reviewRequired > 0)
    attentionItems.push({ tone: "warning", text: `${reviewRequired} 项治理待复核`, href: "/governance" });
  if (qualityFail > 0)
    attentionItems.push({ tone: "warning", text: `${qualityFail} 个资产质量未达标`, href: "/governance" });

  const rawCount = data.rawObjects.data.length;
  const batchCount = data.batches.data.length;
  const funnelSteps = [
    { label: "原始对象", value: rawCount },
    { label: "数据资产", value: assetCount },
    { label: "标准化引用", value: refCount },
    { label: "已治理", value: governedRefIds.size },
  ];

  const recentAudits = data.audits.data.slice(0, 5);
  const processingBatches = data.batches.data.filter((b) => b.status === "processing").length;

  const workbenchData: WorkbenchData = {
    assetCount,
    refCount,
    jobCount,
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
    batchCount,
    funnelSteps,
    recentAudits,
    batches: data.batches.data,
    governanceRuns: data.governanceRuns.data,
    processingBatches,
  };

  return (
    <>
      <PageHeader
        eyebrow="工作台 — 全局概览"
        title="工作台"
        description="问题驱动的运营首页。关注异常项、流水线健康度和待办决策。"
      />
      <ApiState ok={data.ok} error={data.error} traceId={data.traceId} />
      <WorkbenchContent data={workbenchData} />
    </>
  );
}
