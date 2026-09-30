import { PageHeader } from "@/components/PageHeader";
import { getApiData } from "@/lib/api";
import type { SyncPlan, SyncProvider, SyncRun } from "@/lib/data-sync";
import { DataSyncContent } from "./_components/DataSyncContent";

export const dynamic = "force-dynamic";

export default async function DataSyncPage() {
  const [providers, plans, runs] = await Promise.all([
    getApiData<SyncProvider[]>("/internal/v1/data-sync/providers", []),
    getApiData<SyncPlan[]>("/internal/v1/data-sync/plans", []),
    getApiData<SyncRun[]>("/internal/v1/data-sync/runs", [], { pageSize: "100" }),
  ]);
  return (
    <>
      <PageHeader
        eyebrow="数据管理"
        title="API 数据同步"
        description="查看系统接入的 Provider，并管理同步计划和运行。"
      />
      <DataSyncContent
        initialProviders={providers.data}
        initialPlans={plans.data}
        initialRuns={runs.data}
        initialError={providers.error ?? plans.error ?? runs.error}
      />
    </>
  );
}
