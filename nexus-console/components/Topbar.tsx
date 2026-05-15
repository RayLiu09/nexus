"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type BreadcrumbSegment = {
  label: string;
  href?: string;
};

function deriveBreadcrumbs(pathname: string): BreadcrumbSegment[] {
  const segments: BreadcrumbSegment[] = [{ label: "工作台", href: "/workbench" }];

  if (pathname === "/workbench") return segments;

  const pageTitles: Record<string, string> = {
    "/data-sources": "数据源管理",
    "/ingest": "数据接入",
    "/raw-ledger": "原始数据台账",
    "/jobs": "作业中心",
    "/assets": "资产目录",
    "/governance": "治理中心",
    "/rules": "规则配置",
    "/ai-prompts": "AI Prompt 配置",
    "/iam-audit": "权限与审计",
    "/my-workspace": "我的工作区",
    "/login": "登录"
  };

  // Check for exact page match
  if (pageTitles[pathname]) {
    segments.push({ label: pageTitles[pathname] });
    return segments;
  }

  // Check for detail pages (e.g., /assets/[id], /jobs/[id])
  for (const [base, title] of Object.entries(pageTitles)) {
    if (pathname.startsWith(base + "/")) {
      segments.push({ label: title, href: base });
      const rest = pathname.slice(base.length);
      if (rest.length > 1) {
        segments.push({ label: rest.replace(/^\//, "") });
      }
      return segments;
    }
  }

  // Fallback: just the path
  segments.push({ label: pathname });
  return segments;
}

export function Topbar() {
  const pathname = usePathname();
  const breadcrumbs = deriveBreadcrumbs(pathname);

  return (
    <header className="topbar">
      <div className="topbar-left">
        {/* Breadcrumb */}
        <nav className="topbar-breadcrumb" aria-label="面包屑">
          {breadcrumbs.map((crumb, i) => (
            <span key={i} style={{ display: "contents" }}>
              {i > 0 && <span className="topbar-breadcrumb-sep">/</span>}
              {crumb.href ? (
                <Link href={crumb.href}>{crumb.label}</Link>
              ) : (
                <span className="topbar-breadcrumb-current">{crumb.label}</span>
              )}
            </span>
          ))}
        </nav>
      </div>

      <div className="topbar-right">
        {/* Search trigger */}
        <button
          className="topbar-search"
          title="命令面板 (⌘K)"
          aria-label="打开命令面板"
        >
          <span>⌘</span> 快速搜索
          <kbd>⌘K</kbd>
        </button>

        {/* Notification */}
        <button
          className="topbar-icon-btn has-notifications"
          title="通知"
          aria-label="通知"
        >
          🔔
        </button>

        {/* User avatar */}
        <button className="topbar-avatar" title="用户菜单" aria-label="用户菜单">
          A
        </button>
      </div>
    </header>
  );
}
