import { notFound } from "next/navigation";

import { PageHeader } from "@/components/PageHeader";
import { findAssetCenterDomain, findAssetCenterResource } from "@/lib/asset-center/catalog";
import { normalizePolicyLevel } from "../../_components/PolicyLevelNav";
import { ResourceShell } from "../../_components/ResourceShell";

type AssetCenterRouteProps = {
  params: Promise<{ domain: string; resource?: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function AssetCenterRoute({ params, searchParams }: AssetCenterRouteProps) {
  const route = await params;
  const domain = findAssetCenterDomain(route.domain);
  if (!domain) notFound();

  const resourcePath = route.resource?.join("/");
  if (!resourcePath) notFound();

  const resource = findAssetCenterResource(domain, resourcePath);
  if (!resource) notFound();

  const query = await searchParams;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader eyebrow={domain.name} title={resource.name} description={resource.description} />
      <ResourceShell
        domain={domain}
        resource={resource}
        policyLevel={normalizePolicyLevel(query.policyLevel)}
      />
    </div>
  );
}
