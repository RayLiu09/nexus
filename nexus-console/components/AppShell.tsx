"use client";

import { useState, useCallback } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import { QuickUploadProvider } from "@/components/QuickUploadProvider";
import { RouteBoundary } from "@/components/shared/RouteBoundary";

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const toggle = useCallback(() => setCollapsed((c) => !c), []);

  if (pathname === "/login" || pathname.startsWith("/login/")) {
    return <>{children}</>;
  }

  return (
    <QuickUploadProvider>
      <div className={collapsed ? "app-shell collapsed" : "app-shell"}>
        <Sidebar collapsed={collapsed} onToggle={toggle} />
        <main className="main-area">
          <Topbar />
          <div className="content">
            <RouteBoundary>{children}</RouteBoundary>
          </div>
        </main>
      </div>
    </QuickUploadProvider>
  );
}
