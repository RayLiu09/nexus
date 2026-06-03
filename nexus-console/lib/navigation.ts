import type { SessionRole } from "@/lib/auth/session";

export type NavGroupId =
  | "overview"
  | "data-engineering"
  | "assets-governance"
  | "access-audit"
  | "personal";

/**
 * Role hierarchy for UI visibility.
 * Higher numeric value = more privileged.
 */
const ROLE_LEVEL: Record<SessionRole, number> = {
  platform_admin: 4,
  data_steward: 3,
  reviewer: 2,
  reader: 1,
};

/** Check if a role meets or exceeds the minimum required level. */
export function roleCanAccess(userRole: SessionRole | undefined, minRole: SessionRole): boolean {
  if (!userRole) return false;
  return (ROLE_LEVEL[userRole] ?? 0) >= (ROLE_LEVEL[minRole] ?? 0);
}

export type NavItem = {
  href: string;
  label: string;
  icon: string;
  badge?: number | string;
  badgeTone?: "default" | "warning" | "danger";
  /** Minimum role required to see this nav item. If omitted, visible to all. */
  minRole?: SessionRole;
};

export type NavGroup = {
  id: NavGroupId;
  label: string;
  items: NavItem[];
};

export type Navigation = NavGroup[];

export const navigation: Navigation = [
  {
    id: "overview",
    label: "总览",
    items: [{ href: "/workbench", label: "工作台", icon: "▦" }],
  },
  {
    id: "data-engineering",
    label: "数据工程",
    items: [
      { href: "/data-sources", label: "数据源管理", icon: "◎" },
      { href: "/ingest", label: "数据接入", icon: "⇪" },
      { href: "/raw-ledger", label: "原始数据台账", icon: "▤" },
      { href: "/jobs", label: "作业中心", icon: "◫" },
    ],
  },
  {
    id: "assets-governance",
    label: "资产与治理",
    items: [
      { href: "/assets", label: "资产目录", icon: "▥" },
      { href: "/governance", label: "治理中心", icon: "◈", badge: 19, badgeTone: "warning" },
      { href: "/tag-review", label: "标签审核", icon: "#", badge: 12, badgeTone: "warning" },
      { href: "/rules", label: "规则配置", icon: "≡", minRole: "data_steward" },
      { href: "/ai-prompts", label: "AI Prompt", icon: "AI", minRole: "data_steward" },
    ],
  },
  {
    id: "access-audit",
    label: "访问与审计",
    items: [
      { href: "/iam-audit", label: "权限与审计", icon: "⌘" },
      { href: "/api-callers", label: "API Caller", icon: "⊡" },
      { href: "/search", label: "检索验证", icon: "?" },
    ],
  },
  {
    id: "personal",
    label: "个人工作",
    items: [{ href: "/my-workspace", label: "我的工作区", icon: "◌" }],
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
