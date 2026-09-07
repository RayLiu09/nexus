import Link from "next/link";

import {
  ASSET_CENTER_DOMAINS,
  assetCenterCountKey,
  assetCenterHref,
} from "@/lib/asset-center/catalog";

export function AssetCenterOverview({ counts }: { counts: Record<string, number> | null }) {
  return (
    <div
      className="grid grid-cols-1 items-start gap-3 md:grid-cols-2 xl:grid-cols-3"
      aria-label="资产中心领域"
    >
      {ASSET_CENTER_DOMAINS.map((domain) => {
        const Icon = domain.icon;
        const isMajor = domain.slug === "major";
        const isUserBehavior = domain.slug === "user-behavior";

        const cardSpan = isMajor
          ? "xl:col-span-2"
          : isUserBehavior
            ? "md:col-span-2 xl:col-span-1"
            : "";
        const resourceGrid = isMajor
          ? "grid md:grid-cols-2"
          : isUserBehavior
            ? "grid md:grid-cols-2 xl:grid-cols-1"
            : "";

        return (
          <article
            className={`border-line bg-surface shadow-card overflow-hidden rounded-md border border-t-2 ${cardSpan}`}
            key={domain.slug}
            style={{ borderTopColor: domain.accent }}
          >
            <header className="flex min-h-[68px] items-center gap-3 px-4 py-3">
              <span
                className="flex size-9 shrink-0 items-center justify-center rounded-md"
                style={{ color: domain.accent, backgroundColor: domain.accentBackground }}
              >
                <Icon size={18} strokeWidth={1.8} aria-hidden />
              </span>
              <div className="min-w-0">
                <h2 className="text-text text-base font-semibold">{domain.name}</h2>
                <p className="text-text-muted mt-0.5 text-xs leading-5">{domain.description}</p>
              </div>
            </header>

            <ul className={resourceGrid}>
              {domain.resources.map((resource, resourceIndex) => {
                const count = counts?.[assetCenterCountKey(domain, resource)];
                const countAvailable = count !== undefined;
                const countLabel = countAvailable
                  ? `${count.toLocaleString("zh-CN")} 条`
                  : "数量暂不可用";
                const hasColumnDivider =
                  (isMajor && resourceIndex % 2 === 0) ||
                  (isUserBehavior && resourceIndex % 2 === 0);

                return (
                  <li
                    className={`border-line-light border-t ${
                      hasColumnDivider
                        ? isUserBehavior
                          ? "md:border-r xl:border-r-0"
                          : "md:border-r"
                        : ""
                    }`}
                    key={resource.path}
                  >
                    <Link
                      className="group hover:bg-surface-alt focus-visible:ring-brand flex min-h-12 items-center gap-2 px-4 py-2 transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset"
                      href={assetCenterHref(domain, resource)}
                      aria-label={`${resource.name}，${countLabel}`}
                    >
                      <span className="text-text group-hover:text-brand min-w-0 flex-1 text-sm leading-5 font-medium transition-colors">
                        {resource.name}
                      </span>
                      <span
                        className="min-w-[58px] shrink-0 text-right text-xs font-semibold tabular-nums"
                        style={{ color: domain.accent }}
                        title={countLabel}
                      >
                        {countAvailable ? `${count.toLocaleString("zh-CN")} 条` : "--"}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </article>
        );
      })}
    </div>
  );
}
