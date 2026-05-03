export type NavItem = {
  href: string;
  label: string;
  prototypeId: string;
};

export const navItems: NavItem[] = [
  { href: "/workbench", label: "工作台", prototypeId: "NX-01" },
  { href: "/data-sources", label: "数据源管理", prototypeId: "NX-02" },
  { href: "/ingest", label: "数据接入", prototypeId: "NX-03" },
  { href: "/raw-ledger", label: "原始数据台账", prototypeId: "NX-04" },
  { href: "/jobs", label: "作业中心", prototypeId: "NX-05" },
  { href: "/assets", label: "资产目录", prototypeId: "NX-06" },
  { href: "/governance", label: "治理中心", prototypeId: "NX-08" },
  { href: "/rules", label: "规则配置", prototypeId: "NX-09" },
  { href: "/iam-audit", label: "权限与审计", prototypeId: "NX-10" },
  { href: "/ai-prompts", label: "AI Prompt 配置", prototypeId: "NX-13" }
];
