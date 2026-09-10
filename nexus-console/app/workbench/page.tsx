import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/shared/ErrorState";
import { loadWorkbenchData } from "@/lib/console-data";
import type { AuditLog, DataSource, IngestBatch, WorkbenchReviewItem } from "@/lib/api";
import { WorkbenchContent } from "./_components/WorkbenchContent";

export const dynamic = "force-dynamic";

export interface WorkbenchData {
  assetCount: number;
  refCount: number;
  governedRefCount: number;
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
  funnelSteps: { label: string; value: number }[];
  /** 最近 batches，按 updated_at desc 排序；UnifiedActivityFeed 内部切片 */
  batches: IngestBatch[];
  /** 最近 audits，按 created_at desc 排序；UnifiedActivityFeed 内部切片 */
  audits: AuditLog[];
  dataSourceById: Record<string, DataSource | undefined>;
  reviewItems: WorkbenchReviewItem[];
  processingBatches: number;
}

export default async function WorkbenchPage() {
  const data = await loadWorkbenchData();
  const summary = data.summary.data;

  const assetCount = summary?.asset_count ?? 0;
  const refCount = summary?.normalized_ref_count ?? 0;
  const succeededJobs = summary?.succeeded_jobs ?? 0;
  const failedJobs = summary?.failed_jobs ?? 0;
  const runningJobs = summary?.running_jobs ?? 0;
  const pipelineHealth = summary?.pipeline_health ?? 100;
  const governanceCoverage = summary?.governance_coverage ?? 0;
  const autoAdopted = summary?.auto_adopted ?? 0;
  const reviewRequired = summary?.review_required ?? 0;
  const qualityPass = summary?.quality_pass ?? 0;
  const qualityWarning = summary?.quality_warning ?? 0;
  const qualityFail = summary?.quality_fail ?? 0;
  const avgQuality = summary?.avg_quality ?? 0;

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
      href: "/tag-review",
      actionLabel: "前往复核",
    });
  if (qualityFail > 0)
    attentionItems.push({
      tone: "warning",
      text: `${qualityFail} 个资产质量未达标`,
      href: "/governance",
      actionLabel: "查看未达标资产",
    });

  const rawCount = summary?.raw_object_count ?? 0;
  const funnelSteps = [
    { label: "原始对象", value: rawCount },
    { label: "数据资产", value: assetCount },
    { label: "标准化引用", value: refCount },
    { label: "已治理", value: summary?.governed_ref_count ?? 0 },
  ];

  const processingBatches = summary?.processing_batches ?? 0;

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
    governedRefCount: summary?.governed_ref_count ?? 0,
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
    batches: sortedBatches,
    audits: sortedAudits,
    dataSourceById,
    reviewItems: summary?.review_items ?? [],
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
