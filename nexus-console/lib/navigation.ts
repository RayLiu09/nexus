import type { SessionRole } from "@/lib/auth/session";
import type { LucideIcon } from "lucide-react";
import {
  BriefcaseBusiness,
  Database,
  FileArchive,
  FileSearch,
  KeyRound,
  LayoutDashboard,
  LibraryBig,
  ListChecks,
  MessageSquareText,
  Search,
  Settings2,
  ShieldCheck,
  TableProperties,
  Workflow,
} from "lucide-react";

import { findAssetCenterDomain, findAssetCenterResource } from "@/lib/asset-center/catalog";

export type NavGroupId =
  | "overview"
  | "asset-center"
  | "intelligent-search"
  | "data-management"
  | "governance-management"
  | "access-audit"
  | "personal";

/**
 * Role hierarchy for UI visibility.
 * Higher numeric value = more privileged.
 */
const ROLE_LEVEL: Record<SessionRole, number> = {
  platform_data_admin: 2,
  business_expert: 1,
};

/** Check if a role meets or exceeds the minimum required level. */
export function roleCanAccess(userRole: SessionRole | undefined, minRole: SessionRole): boolean {
  if (!userRole) return false;
  return (ROLE_LEVEL[userRole] ?? 0) >= (ROLE_LEVEL[minRole] ?? 0);
}

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  badge?: number | string;
  badgeTone?: "default" | "warning" | "danger";
  /** Minimum role required to see this nav item. If omitted, visible to all. */
  minRole?: SessionRole;
};

export type NavGroup = {
  id: NavGroupId;
  label?: string;
  items: NavItem[];
};

export type Navigation = NavGroup[];

export const navigation: Navigation = [
  {
    id: "overview",
    label: "总览",
    items: [{ href: "/workbench", label: "工作台", icon: LayoutDashboard }],
  },
  {
    id: "asset-center",
    items: [{ href: "/asset-center", label: "资产中心", icon: LibraryBig }],
  },
  {
    id: "intelligent-search",
    items: [{ href: "/query", label: "智能检索", icon: Search }],
  },
  {
    id: "data-management",
    label: "数据管理",
    items: [
      { href: "/data-sources", label: "数据源", icon: Database },
      { href: "/raw-ledger", label: "原始数据台账", icon: FileArchive },
      { href: "/jobs", label: "作业中心", icon: Workflow },
      { href: "/assets", label: "全部资产台账", icon: TableProperties },
    ],
  },
  {
    id: "governance-management",
    label: "治理管理",
    items: [
      { href: "/tag-review", label: "治理审核", icon: ListChecks, badgeTone: "warning" },
      { href: "/governance", label: "治理追踪", icon: FileSearch },
      { href: "/rules", label: "规则配置", icon: Settings2, minRole: "business_expert" },
      {
        href: "/ai-prompts",
        label: "Prompt 提示词",
        icon: MessageSquareText,
        minRole: "business_expert",
      },
    ],
  },
  {
    id: "access-audit",
    label: "访问与审计",
    items: [
      { href: "/iam-audit", label: "权限与审计", icon: ShieldCheck },
      { href: "/api-callers", label: "API Caller", icon: KeyRound },
    ],
  },
  {
    id: "personal",
    label: "个人工作",
    items: [{ href: "/my-workspace", label: "我的工作区", icon: BriefcaseBusiness }],
  },
];

export const navItems: NavItem[] = navigation.flatMap((g) => g.items);

export function getActiveGroup(pathname: string): NavGroupId | null {
  for (const group of navigation) {
    if (group.items.some((item) => pathname.startsWith(item.href))) {
      return group.id;
    }
  }
  return null;
}

export function getBreadcrumb(pathname: string): { label: string; href?: string }[] {
  const crumbs: { label: string; href?: string }[] = [{ label: "NEXUS 控制台" }];

  if (pathname === "/asset-center" || pathname.startsWith("/asset-center/")) {
    crumbs.push({ label: "资产中心", href: "/asset-center" });
    const [, , domainSlug, ...resourceParts] = pathname.split("/");
    if (!domainSlug) return crumbs;

    const domain = findAssetCenterDomain(domainSlug);
    if (!domain) return crumbs;
    crumbs.push({ label: domain.name });

    const resource = findAssetCenterResource(domain, resourceParts.join("/"));
    if (resource) crumbs.push({ label: resource.name });
    return crumbs;
  }

  for (const group of navigation) {
    for (const item of group.items) {
      if (pathname === item.href || pathname.startsWith(item.href + "/")) {
        crumbs.push({ label: item.label, href: item.href });
        break;
      }
    }
  }

  return crumbs;
}
