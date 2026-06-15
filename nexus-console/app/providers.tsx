"use client";

import type { ReactNode } from "react";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { ConfigProvider, App as AntdApp, type ThemeConfig } from "antd";
import zhCN from "antd/locale/zh_CN";

/**
 * 视觉系统 v2 token —— 与 globals.css :root 保持同步。
 *
 * 重要：Antd cssinjs 需要从语义 token 推导出整套色盘（如 *-bg / *-border / *-hover），
 * 必须传具体 hex，不能传 var(--brand)。任何 token 改动都需同时改 globals.css。
 */
const theme: ThemeConfig = {
  cssVar: { key: "nexus" },
  hashed: false,
  token: {
    // 主色 —— Refined Blue（冷紫向，降饱和）
    colorPrimary: "#3851d3",
    colorLink: "#3851d3",
    // info 比主色再冷一档
    colorInfo: "#4a7ec9",
    // 语义色 —— 苔绿 / 暖琥珀 / 砖红，降饱和后大面积场景更舒适
    colorSuccess: "#2c8a5a",
    colorWarning: "#c2701f",
    colorError: "#c03946",
    // 文本 / 表面 / 边框
    colorTextBase: "#0f1424",
    colorBgBase: "#ffffff",
    colorBorder: "#e5e7eb",
    colorBorderSecondary: "#f1f2f5",
    // 圆角
    borderRadius: 8,
    borderRadiusLG: 12,
    borderRadiusSM: 6,
    // 字体（继承 html 上 next/font 注入的 Inter Tight）
    fontFamily: "inherit",
    fontSize: 14,
    controlHeight: 36,
  },
  components: {
    Layout: {
      headerBg: "#ffffff",
      siderBg: "#0f172a",
      bodyBg: "#f3f5f8",
    },
    Menu: {
      itemSelectedBg: "rgba(56, 81, 211, 0.10)",
      itemSelectedColor: "#3851d3",
      itemHoverBg: "rgba(56, 81, 211, 0.06)",
    },
    Button: {
      primaryShadow: "none",
      defaultShadow: "none",
    },
    Card: {
      headerBg: "transparent",
    },
    Statistic: {
      titleFontSize: 12,
      contentFontSize: 24,
    },
    Tag: {
      defaultBg: "#f1f2f5",
      defaultColor: "#475063",
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
