"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { Input, Avatar, Breadcrumb, Tag, Tooltip } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { getBreadcrumb } from "@/lib/navigation";

export function Topbar() {
  const pathname = usePathname();
  const crumbs = getBreadcrumb(pathname);

  const breadcrumbItems = crumbs.map((crumb, i) => ({
    key: i,
    title: crumb.href ? <Link href={crumb.href}>{crumb.label}</Link> : crumb.label,
  }));

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
        <Tag bordered={false} color="default">
          环境: Demo
        </Tag>
        <Tag bordered={false} color="default">
          角色: 平台管理员
        </Tag>
        <Tag bordered={false} color="default">
          组织: 产教融合中心
        </Tag>

        <Tooltip title="张敏 — 平台管理员">
          <Avatar
            size={32}
            style={{
              backgroundColor: "var(--brand-200)",
              color: "var(--brand-700)",
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            张
          </Avatar>
        </Tooltip>
      </div>
    </header>
  );
}
