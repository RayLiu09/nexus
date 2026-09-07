import Link from "next/link";
import { ArrowLeft, Database } from "lucide-react";

import type { AssetCenterDomain, AssetCenterResource } from "@/lib/asset-center/catalog";
import { assetCenterHref, isPolicyResource } from "@/lib/asset-center/catalog";
import { PolicyLevelNav } from "./PolicyLevelNav";

export function ResourceShell({
  domain,
  resource,
  policyLevel,
}: {
  domain: AssetCenterDomain;
  resource: AssetCenterResource;
  policyLevel: string;
}) {
  const href = assetCenterHref(domain, resource);

  return (
    <div className="flex flex-col gap-6">
      {isPolicyResource(resource) && <PolicyLevelNav href={href} current={policyLevel} />}

      <section className="border-line bg-surface flex min-h-[360px] flex-col items-center justify-center border-y px-6 py-14 text-center">
        <span
          className="flex size-12 items-center justify-center rounded-md"
          style={{ color: domain.accent, backgroundColor: domain.accentBackground }}
        >
          <Database size={22} aria-hidden />
        </span>
        <h2 className="text-text mt-4 text-base font-semibold">暂无可用业务视图</h2>
        <p className="text-text-muted mt-2 max-w-md text-sm">
          业务字段与数据接口将在后续领域任务中接入。
        </p>
      </section>

      <Link
        className="text-text-secondary inline-flex w-fit items-center gap-2 text-sm"
        href="/asset-center"
      >
        <ArrowLeft size={15} aria-hidden />
        返回资产中心
      </Link>
    </div>
  );
}
