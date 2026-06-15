import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/shared/ErrorState";
import { loadWorkbenchData } from "@/lib/console-data";
import type { AIGovernanceRun, AuditLog, DataSource, IngestBatch } from "@/lib/api";
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
  attentionItems: {
    tone: "danger" | "warning";
    text: string;
    href: string;
    actionLabel: string;
  }[];
  rawCount: number;
  batchCount: number;
  funnelSteps: { label: string; value: number }[];
  /** 全部 batches，按 updated_at desc 排序；UnifiedActivityFeed 内部切片 */
  batches: IngestBatch[];
  /** 全部 audits，按 created_at desc 排序；UnifiedActivityFeed 内部切片 */
  audits: AuditLog[];
  dataSourceById: Record<string, DataSource | undefined>;
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

  const attentionItems: WorkbenchData["attentionItems"] = [];
  if (failedJobs > 0)
    attentionItems.push({
      tone: "danger",
      text: `${failedJobs} 个作业失败，需排查`,
      href: "/jobs?status=failed",
      actionLabel: "查看失败作业",
    });
  if (reviewRequired > 0)
    attentionItems.push({
      tone: "warning",
      text: `${reviewRequired} 项治理待复核`,
      href: "/governance",
      actionLabel: "前往复核",
    });
  if (qualityFail > 0)
    attentionItems.push({
      tone: "warning",
      text: `${qualityFail} 个资产质量未达标`,
      href: "/governance",
      actionLabel: "查看未达标资产",
    });

  const rawCount = data.rawObjects.data.length;
  const batchCount = data.batches.data.length;
  const funnelSteps = [
    { label: "原始对象", value: rawCount },
    { label: "数据资产", value: assetCount },
    { label: "标准化引用", value: refCount },
    { label: "已治理", value: governedRefIds.size },
  ];

  const processingBatches = data.batches.data.filter((b) => b.status === "processing").length;

  // 服务端预排序：UnifiedActivityFeed 切片即可
  const sortedBatches = [...data.batches.data].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  );
  const sortedAudits = [...data.audits.data].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  );
  const dataSourceById: Record<string, DataSource | undefined> = {};
  for (const ds of data.dataSources.data) dataSourceById[ds.id] = ds;

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
    batches: sortedBatches,
    audits: sortedAudits,
    dataSourceById,
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

      {data.ok ? (
        <WorkbenchContent data={workbenchData} />
      ) : (
        <ErrorState
          title="工作台数据加载失败"
          description={data.error || "无法连接到后端服务，请检查网络后重试。"}
          traceId={data.traceId ?? undefined}
        />
      )}
    </>
  );
}
