import { describe, expect, it } from "vitest";

import { isConsoleSessionRole } from "@/lib/auth/roles";
import { getActiveGroup, getBreadcrumb, navigation, roleCanAccess } from "./navigation";

describe("Console navigation", () => {
  it("uses the frozen first-level group order", () => {
    expect(navigation.map((group) => group.id)).toEqual([
      "overview",
      "asset-center",
      "intelligent-search",
      "data-management",
      "governance-management",
      "access-audit",
      "personal",
    ]);
  });

  it("keeps intelligent search as a single direct navigation item", () => {
    const group = navigation.find((item) => item.id === "intelligent-search");
    expect(group?.label).toBeUndefined();
    expect(group?.items.map((item) => [item.label, item.href])).toEqual([["智能检索", "/query"]]);
    expect(
      navigation.flatMap((item) => item.items).some((item) => item.href === "/retrieval-test"),
    ).toBe(false);
  });

  it("labels the generic asset route as the complete ledger", () => {
    const assets = navigation
      .flatMap((group) => group.items)
      .find((item) => item.href === "/assets");
    expect(assets?.label).toBe("全部资产台账");
    expect(getActiveGroup("/assets/example")).toBe("data-management");
  });

  it("keeps one canonical Prompt entry under Governance Management", () => {
    const group = navigation.find((item) => item.id === "governance-management");
    expect(group?.items.map((item) => [item.label, item.href])).toEqual([
      ["治理审核", "/tag-review"],
      ["治理追踪", "/governance"],
      ["规则配置", "/rules"],
      ["Prompt 提示词", "/ai-prompts"],
    ]);
    expect(
      navigation.flatMap((item) => item.items).some((item) => item.href === "/governance-prompts"),
    ).toBe(false);
  });

  it("maps backend-issued roles to Prompt navigation permissions", () => {
    expect(roleCanAccess("platform_data_admin", "business_expert")).toBe(true);
    expect(roleCanAccess("business_expert", "business_expert")).toBe(true);
    expect(isConsoleSessionRole("ops")).toBe(false);
    expect(isConsoleSessionRole("api_caller")).toBe(false);
  });

  it("builds Asset Center domain and nested resource breadcrumbs", () => {
    expect(getBreadcrumb("/asset-center/major/standard-course-library")).toEqual([
      { label: "NEXUS 控制台" },
      { label: "资产中心", href: "/asset-center" },
      { label: "专业数据" },
      { label: "标准课程库" },
    ]);
  });
});
