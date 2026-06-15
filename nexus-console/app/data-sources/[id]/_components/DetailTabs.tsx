"use client";

import { Tabs } from "antd";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

export type TabKey = "config" | "sync" | "history";

interface DetailTabsProps {
  config: React.ReactNode;
  sync: React.ReactNode;
  history: React.ReactNode;
  defaultActive?: TabKey;
}

const VALID_TABS: TabKey[] = ["config", "sync", "history"];

export function DetailTabs({ config, sync, history, defaultActive = "config" }: DetailTabsProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlTab = searchParams.get("tab");
  const active: TabKey = useMemo(
    () => (urlTab && VALID_TABS.includes(urlTab as TabKey) ? (urlTab as TabKey) : defaultActive),
    [urlTab, defaultActive],
  );

  const handleChange = useCallback(
    (key: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (key === defaultActive) params.delete("tab");
      else params.set("tab", key);
      const q = params.toString();
      router.replace(q ? `?${q}` : "?", { scroll: false });
    },
    [router, searchParams, defaultActive],
  );

  return (
    <Tabs
      activeKey={active}
      onChange={handleChange}
      destroyOnHidden
      items={[
        { key: "config", label: "配置", children: config },
        { key: "sync", label: "同步控制", children: sync },
        { key: "history", label: "同步历史", children: history },
      ]}
    />
  );
}
