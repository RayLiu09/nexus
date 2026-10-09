import { PageHeader } from "@/components/PageHeader";
import { getApiData } from "@/lib/api";
import type { JobCollectionCategory, SyncPlan, SyncProvider } from "@/lib/data-sync";
import { DataSyncContent } from "./_components/DataSyncContent";

export const dynamic = "force-dynamic";

export default async function DataSyncPage() {
  const [providers, plans, catalog] = await Promise.all([
    getApiData<SyncProvider[]>("/internal/v1/data-sync/providers", []),
    getApiData<SyncPlan[]>("/internal/v1/data-sync/plans", []),
    getApiData<JobCollectionCategory[]>("/internal/v1/data-sync/job-catalog", []),
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
        initialCatalog={catalog.data}
        initialError={providers.error ?? plans.error ?? catalog.error}
      />
    </>
  );
}
