"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { navigation, roleCanAccess, type NavItem } from "@/lib/navigation";
import { useSession } from "@/lib/auth/useSession";
import { useNavBadges } from "@/hooks/useNavBadges";

function resolveBadge(item: NavItem, badgeOverrides: Record<string, number>): NavItem["badge"] {
  if (badgeOverrides[item.href] != null) {
    return badgeOverrides[item.href] > 0 ? badgeOverrides[item.href] : undefined;
  }
  return item.badge;
}

type SidebarProps = {
  collapsed: boolean;
  onToggle: () => void;
};

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();
  const { session } = useSession();
  const navBadges = useNavBadges();

  const badgeOverrides: Record<string, number> = {
    "/governance": navBadges.governancePendingCount,
    "/tag-review": navBadges.tagReviewPendingCount,
  };

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
        {navigation.map((group) => {
          const visibleItems = group.items.filter(
            (item) => !item.minRole || roleCanAccess(session?.role, item.minRole),
          );
          if (visibleItems.length === 0) return null;
          return (
            <div className="sidebar-group" key={group.id}>
              <div className="sidebar-group-label">{group.label}</div>
              {visibleItems.map((item) => {
                const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
                const badge = resolveBadge(item, badgeOverrides);
                return (
                  <Link
                    className={`nav-item${isActive ? " active" : ""}`}
                    href={item.href}
                    key={item.href}
                    title={collapsed ? item.label : undefined}
                  >
                    <span className="nav-item-icon">{item.icon}</span>
                    <span className="nav-item-label">{item.label}</span>
                    {badge != null && !collapsed && (
                      <span className={`nav-item-badge ${item.badgeTone ?? ""}`}>
                        {badge}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          );
        })}
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
