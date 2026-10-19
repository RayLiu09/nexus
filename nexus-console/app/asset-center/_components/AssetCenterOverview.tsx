import Link from "next/link";
import styles from "./AssetCenterOverview.module.css";

import {
  ASSET_CENTER_DOMAINS,
  assetCenterCountKey,
  assetCenterHref,
} from "@/lib/asset-center/catalog";

export function AssetCenterOverview({
  counts,
  loading = false,
}: {
  counts: Record<string, number> | null;
  loading?: boolean;
}) {
  return (
    <div className={styles.grid} aria-label="资产中心领域">
      {ASSET_CENTER_DOMAINS.filter((domain) => domain.slug !== "user-behavior").map((domain) => {
        const Icon = domain.icon;
        const isMajor = domain.slug === "major";
        const resourceGrid = isMajor ? styles.majorResources : "";

        return (
          <article
            className={styles.card}
            key={domain.slug}
            style={{ borderTopColor: domain.accent }}
          >
            <header className={styles.header}>
              <span
                className={styles.icon}
                style={{ color: domain.accent, backgroundColor: domain.accentBackground }}
              >
                <Icon size={21} strokeWidth={1.8} aria-hidden />
              </span>
              <div className={styles.heading}>
                <h2 className={styles.title}>{domain.name}</h2>
                <p className={styles.description}>{domain.description}</p>
              </div>
            </header>

            <ul className={`${styles.resources} ${resourceGrid}`}>
              {domain.resources
                .filter(
                  (resource) =>
                    resource.path !== "certificates" &&
                    resource.path !== "education-policies" &&
                    resource.path !== "course-standards",
                )
                .map((resource, resourceIndex) => {
                  const count = counts?.[assetCenterCountKey(domain, resource)];
                  const countAvailable = count !== undefined;
                  const countLabel = countAvailable
                    ? `${count.toLocaleString("zh-CN")} 条`
                    : loading
                      ? "数量加载中"
                      : "数量暂不可用";
                  const hasColumnDivider = isMajor && resourceIndex % 2 === 0;

                  return (
                    <li
                      className={`${styles.resource} ${hasColumnDivider ? styles.columnDivider : ""}`}
                      key={resource.path}
                    >
                      <Link
                        className={styles.link}
                        href={assetCenterHref(domain, resource)}
                        aria-label={`${resource.name}，${countLabel}`}
                      >
                        <span className={styles.resourceName}>{resource.name}</span>
                        <span
                          className={styles.count}
                          style={{ color: domain.accent }}
                          title={countLabel}
                        >
                          {countAvailable
                            ? `${count.toLocaleString("zh-CN")} 条`
                            : loading
                              ? "加载中"
                              : "--"}
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
