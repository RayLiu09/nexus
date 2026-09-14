import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/shared/ErrorState";
import { loadWorkbenchData } from "@/lib/console-data";
import type {
  AuditLog,
  DataSource,
  IngestBatch,
  WorkbenchJobDuration,
  WorkbenchQueueTrend,
} from "@/lib/api";
import { WorkbenchContent } from "./_components/WorkbenchContent";

export const dynamic = "force-dynamic";

export interface WorkbenchData {
  assetCount: number;
  refCount: number;
  governedRefCount: number;
  succeededJobs: number;
  failedJobs: number;
  runningJobs: number;
  queuedJobs: number;
  pipelineHealth: number;
  governanceCoverage: number;
  autoAdopted: number;
  avgQuality: number;
  qualityPass: number;
  attentionItems: {
    tone: "danger" | "warning";
    text: string;
    href: string;
    actionLabel: string;
  }[];
  executionDurationTop: WorkbenchJobDuration[];
  queueTrend: WorkbenchQueueTrend[];
  /** 最近 batches，按 updated_at desc 排序；UnifiedActivityFeed 内部切片 */
  batches: IngestBatch[];
  /** 最近 audits，按 created_at desc 排序；UnifiedActivityFeed 内部切片 */
  audits: AuditLog[];
  dataSourceById: Record<string, DataSource | undefined>;
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
  const queuedJobs = summary?.queued_jobs ?? 0;
  const pipelineHealth = summary?.pipeline_health ?? 100;
  const governanceCoverage = summary?.governance_coverage ?? 0;
  const autoAdopted = summary?.auto_adopted ?? 0;
  const qualityPass = summary?.quality_pass ?? 0;
  const avgQuality = summary?.avg_quality ?? 0;

  // Admin workbench focuses on pipeline / data-plane operations. Governance
  // review counts and quality-fail alerts belong to the business_expert
  // workflow (/tag-review, /governance) and are intentionally omitted here —
  // those routes are also gated to business_expert by middleware, so linking
  // to them from the admin workbench would produce broken navigation.
  const attentionItems: WorkbenchData["attentionItems"] = [];
  if (failedJobs > 0)
    attentionItems.push({
      tone: "danger",
      text: `${failedJobs} 个作业失败，需排查`,
      href: "/jobs?status=failed",
      actionLabel: "查看失败作业",
    });

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
    queuedJobs,
    pipelineHealth,
    governanceCoverage,
    autoAdopted,
    avgQuality,
    qualityPass,
    attentionItems,
    executionDurationTop: summary?.execution_duration_top ?? [],
    queueTrend: summary?.queue_trend ?? [],
    batches: sortedBatches,
    audits: sortedAudits,
    dataSourceById,
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
