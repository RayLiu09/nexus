"use client";

import { useState, useCallback } from "react";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import { RouteBoundary } from "@/components/shared/RouteBoundary";

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const [collapsed, setCollapsed] = useState(false);
  const toggle = useCallback(() => setCollapsed((c) => !c), []);

  return (
    <div className={`app-shell${collapsed ? " collapsed" : ""}`}>
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <main className="main-area">
        <Topbar />
        <div className="content">
          <RouteBoundary>{children}</RouteBoundary>
        </div>
      </main>
    </div>
  );
}
