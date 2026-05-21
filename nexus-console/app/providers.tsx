"use client";

import type { ReactNode } from "react";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { ConfigProvider, App as AntdApp, type ThemeConfig } from "antd";
import zhCN from "antd/locale/zh_CN";

const theme: ThemeConfig = {
  cssVar: { key: "nexus" },
  hashed: false,
  token: {
    // 主色 — Tailwind Blue-600 (奠基蓝)，与 globals.css --brand-600 同源
    colorPrimary: "#2563eb",
    colorLink: "#2563eb",
    // info 浅一档（Blue-500），避免与主色冲突
    colorInfo: "#3b82f6",
    colorSuccess: "#16a34a",
    colorWarning: "#d97706",
    colorError: "#dc2626",
    colorTextBase: "#1f2937",
    colorBgBase: "#ffffff",
    colorBorder: "#e5e7eb",
    colorBorderSecondary: "#f3f4f6",
    borderRadius: 8,
    borderRadiusLG: 12,
    borderRadiusSM: 6,
    fontFamily: "inherit",
    fontSize: 14,
    controlHeight: 36,
  },
  components: {
    Layout: {
      headerBg: "#ffffff",
      siderBg: "#0f172a",
      bodyBg: "#f8f9fb",
    },
    Menu: {
      itemSelectedBg: "rgba(37, 99, 235, 0.10)",
      itemSelectedColor: "#2563eb",
      itemHoverBg: "rgba(37, 99, 235, 0.06)",
    },
    Button: {
      primaryShadow: "none",
    },
    Card: {
      headerBg: "transparent",
    },
  },
};

export function Providers({ children }: { children: ReactNode }) {
  return (
    <AntdRegistry>
      <ConfigProvider theme={theme} locale={zhCN}>
        <AntdApp>{children}</AntdApp>
      </ConfigProvider>
    </AntdRegistry>
  );
}
