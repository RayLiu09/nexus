import type { SessionRole } from "@/lib/auth/session";
import type { LucideIcon } from "lucide-react";
import {
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
  Users2,
  Workflow,
} from "lucide-react";

import { findAssetCenterDomain, findAssetCenterResource } from "@/lib/asset-center/catalog";

export type NavGroupId =
  | "overview"
  | "asset-center"
  | "intelligent-search"
  | "data-management"
  | "governance-management"
  | "access-audit";

const ADMIN_ONLY: readonly SessionRole[] = ["platform_data_admin"] as const;
const EXPERT_ONLY: readonly SessionRole[] = ["business_expert"] as const;

/**
 * Return true when `userRole` is included in `allowedRoles`. If `allowedRoles`
 * is omitted the item is public to every authenticated console user.
 * The platform intentionally supports only two disjoint role families
 * (admin vs. business expert); there is no hierarchy or inheritance.
 */
export function roleCanAccess(
  userRole: SessionRole | undefined,
  allowedRoles?: readonly SessionRole[],
): boolean {
  if (!allowedRoles || allowedRoles.length === 0) return true;
  if (!userRole) return false;
  return allowedRoles.includes(userRole);
}

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  badge?: number | string;
  badgeTone?: "default" | "warning" | "danger";
  /**
   * Roles allowed to see this item. Undefined = every authenticated user.
   * Role membership is disjoint — admins do NOT inherit expert-only pages
   * and vice versa.
   */
  allowedRoles?: readonly SessionRole[];
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
    items: [
      {
        href: "/workbench",
        label: "工作台",
        icon: LayoutDashboard,
        allowedRoles: ADMIN_ONLY,
      },
    ],
  },
  {
    id: "asset-center",
    items: [
      {
        href: "/asset-center",
        label: "资产中心",
        icon: LibraryBig,
        allowedRoles: EXPERT_ONLY,
      },
    ],
  },
  {
    id: "intelligent-search",
    items: [
      {
        href: "/query",
        label: "智能检索",
        icon: Search,
        allowedRoles: EXPERT_ONLY,
      },
    ],
  },
  {
    id: "data-management",
    label: "数据管理",
    items: [
      { href: "/data-sources", label: "数据源", icon: Database, allowedRoles: ADMIN_ONLY },
      {
        href: "/raw-ledger",
        label: "原始数据台账",
        icon: FileArchive,
        allowedRoles: ADMIN_ONLY,
      },
      { href: "/jobs", label: "作业中心", icon: Workflow, allowedRoles: ADMIN_ONLY },
      {
        href: "/assets",
        label: "全部资产台账",
        icon: TableProperties,
        allowedRoles: ADMIN_ONLY,
      },
    ],
  },
  {
    id: "governance-management",
    label: "治理管理",
    items: [
      {
        href: "/tag-review",
        label: "治理审核",
        icon: ListChecks,
        badgeTone: "warning",
        allowedRoles: EXPERT_ONLY,
      },
      { href: "/governance", label: "治理追踪", icon: FileSearch, allowedRoles: EXPERT_ONLY },
      { href: "/rules", label: "规则配置", icon: Settings2, allowedRoles: EXPERT_ONLY },
      {
        href: "/ai-prompts",
        label: "Prompt 提示词",
        icon: MessageSquareText,
        allowedRoles: EXPERT_ONLY,
      },
    ],
  },
  {
    id: "access-audit",
    label: "访问与审计",
    items: [
      { href: "/iam-audit", label: "权限与审计", icon: ShieldCheck, allowedRoles: ADMIN_ONLY },
      { href: "/api-callers", label: "API Caller", icon: KeyRound, allowedRoles: ADMIN_ONLY },
      { href: "/users", label: "用户管理", icon: Users2, allowedRoles: ADMIN_ONLY },
    ],
  },
];

export const navItems: NavItem[] = navigation.flatMap((g) => g.items);

/**
 * Prefix set of admin-only routes — kept in sync with `navigation` above so
 * `middleware.ts` can enforce the same policy server-side.
 */
export const ADMIN_ONLY_PREFIXES: readonly string[] = navItems
  .filter((item) => item.allowedRoles === ADMIN_ONLY)
  .map((item) => item.href);

/** Prefix set of expert-only routes (asset center, intelligent search, governance). */
export const EXPERT_ONLY_PREFIXES: readonly string[] = navItems
  .filter((item) => item.allowedRoles === EXPERT_ONLY)
  .map((item) => item.href);

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
