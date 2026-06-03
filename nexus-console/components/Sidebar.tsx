"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { navigation } from "@/lib/navigation";

type SidebarProps = {
  collapsed: boolean;
  onToggle: () => void;
};

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();

  return (
    <aside className="sidebar">
      {/* Brand */}
      <Link className="sidebar-brand" href="/workbench">
        <div className="sidebar-brand-icon">N</div>
        <div className="sidebar-brand-text">
          <strong>NEXUS</strong>
          <span>数据与知识资产平台</span>
        </div>
      </Link>

      {/* Navigation groups */}
      <nav className="sidebar-nav" aria-label="主导航">
        {navigation.map((group) => (
          <div className="sidebar-group" key={group.id}>
            <div className="sidebar-group-label">{group.label}</div>
            {group.items.map((item) => {
              const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
              return (
                <Link
                  className={`nav-item${isActive ? " active" : ""}`}
                  href={item.href}
                  key={item.href}
                  title={collapsed ? item.label : undefined}
                >
                  <span className="nav-item-icon">{item.icon}</span>
                  <span className="nav-item-label">{item.label}</span>
                  {item.badge != null && !collapsed && (
                    <span className={`nav-item-badge ${item.badgeTone ?? ""}`}>
                      {item.badge}
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Collapse toggle */}
      <div className="sidebar-collapse">
        <button onClick={onToggle} aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}>
          <span className={`sidebar-collapse-icon${collapsed ? " collapsed" : ""}`}>
            {collapsed ? "▸" : "◂"}
          </span>
          <span className="sidebar-collapse-text">收起侧边栏</span>
        </button>
      </div>
    </aside>
  );
}
