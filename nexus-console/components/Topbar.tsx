"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { Avatar, Breadcrumb, Dropdown, Input, Tag, Tooltip } from "antd";
import {
  SearchOutlined,
  LogoutOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { getBreadcrumb } from "@/lib/navigation";
import { useSession } from "@/lib/auth/useSession";
import { logout } from "@/lib/auth/session";

const ENV_LABELS: Record<string, { label: string; color: string }> = {
  demo: { label: "环境: Demo", color: "default" },
  staging: { label: "环境: Staging", color: "warning" },
  prod: { label: "环境: 生产", color: "error" },
};

const ROLE_LABELS: Record<string, string> = {
  platform_admin: "平台管理员",
  data_steward: "数据管家",
  reviewer: "审核员",
  reader: "只读用户",
};

export function Topbar() {
  const pathname = usePathname();
  const crumbs = getBreadcrumb(pathname);
  const { session } = useSession();

  const breadcrumbItems = crumbs.map((crumb, i) => ({
    key: i,
    title: crumb.href ? <Link href={crumb.href}>{crumb.label}</Link> : crumb.label,
  }));

  const displayName = session?.displayName ?? "用户";
  const initial = displayName.charAt(0);
  const roleLabel = session?.role ? ROLE_LABELS[session.role] ?? session.role : "";
  const orgName = session?.orgUnit?.name ?? "";
  const envInfo = session?.env ? ENV_LABELS[session.env] ?? ENV_LABELS.demo : ENV_LABELS.demo;

  const userMenuItems = [
    {
      key: "role",
      label: `角色：${roleLabel}`,
      icon: <UserOutlined />,
      disabled: true,
    },
    { type: "divider" as const },
    {
      key: "logout",
      label: "退出登录",
      icon: <LogoutOutlined />,
      onClick: () => logout(),
    },
  ];

  return (
    <header className="topbar">
      <div className="topbar-left">
        <Breadcrumb items={breadcrumbItems} />

        <Input
          className="topbar-search-input"
          placeholder="搜索 batch / asset / rule / trace_id"
          prefix={<SearchOutlined />}
          suffix={<kbd className="topbar-kbd">⌘K</kbd>}
          variant="filled"
          readOnly
          onFocus={(e) => e.target.blur()}
        />
      </div>

      <div className="topbar-right">
        <Tag color={envInfo.color}>{envInfo.label}</Tag>
        {session && <Tag color="default">角色: {roleLabel}</Tag>}
        {session?.orgUnit?.name && <Tag color="default">组织: {orgName}</Tag>}

        <Dropdown menu={{ items: userMenuItems }} placement="bottomRight" trigger={["click"]}>
          <Tooltip title={`${displayName} — ${roleLabel}`}>
            <Avatar
              size={32}
              style={{
                backgroundColor: "var(--brand-200)",
                color: "var(--brand-700)",
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              {initial}
            </Avatar>
          </Tooltip>
        </Dropdown>
      </div>
    </header>
  );
}
