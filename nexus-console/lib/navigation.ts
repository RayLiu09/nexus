// ================================================================
// NEXUS v3.2 Navigation — 4 functional groups with collapse support
// ================================================================

export type NavGroupId = "data-engineering" | "assets" | "governance" | "tools-system";

export type NavItem = {
  href: string;
  label: string;
  icon: string; // emoji or icon identifier
  badge?: number | string;
  badgeTone?: "default" | "warning" | "danger";
};

export type NavGroup = {
  id: NavGroupId;
  label: string;
  items: NavItem[];
};

export type Navigation = NavGroup[];

export const navigation: Navigation = [
  {
    id: "data-engineering",
    label: "数据工程",
    items: [
      { href: "/workbench", label: "工作台", icon: "⊞" },
      { href: "/data-sources", label: "数据源管理", icon: "◎" },
      { href: "/ingest", label: "数据接入", icon: "↥" },
      { href: "/raw-ledger", label: "原始数据台账", icon: "☰" },
      { href: "/jobs", label: "作业中心", icon: "⚙" }
    ]
  },
  {
    id: "assets",
    label: "资产",
    items: [
      { href: "/assets", label: "资产目录", icon: "◈" },
      { href: "/my-workspace", label: "我的工作区", icon: "♨" }
    ]
  },
  {
    id: "governance",
    label: "治理",
    items: [
      { href: "/governance", label: "治理中心", icon: "⛬" },
      { href: "/rules", label: "规则配置", icon: "⚖" },
      { href: "/ai-prompts", label: "AI Prompt 配置", icon: "✦" }
    ]
  },
  {
    id: "tools-system",
    label: "工具 / 系统",
    items: [
      { href: "/iam-audit", label: "权限与审计", icon: "⊡" }
    ]
  }
];

// -- Legacy flat list for backward compat (deprecated, use navigation) --
export const navItems: NavItem[] = navigation.flatMap((g) => g.items);

// -- Derive active group from pathname --
export function getActiveGroup(pathname: string): NavGroupId | null {
  for (const group of navigation) {
    if (group.items.some((item) => pathname.startsWith(item.href))) {
      return group.id;
    }
  }
  return null;
}
