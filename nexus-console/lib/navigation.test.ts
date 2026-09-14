import { describe, expect, it } from "vitest";

import { isConsoleSessionRole } from "@/lib/auth/roles";
import {
  ADMIN_ONLY_PREFIXES,
  EXPERT_ONLY_PREFIXES,
  getActiveGroup,
  getBreadcrumb,
  navigation,
  navItems,
  roleCanAccess,
} from "./navigation";

describe("Console navigation", () => {
  it("uses the frozen first-level group order", () => {
    expect(navigation.map((group) => group.id)).toEqual([
      "overview",
      "asset-center",
      "intelligent-search",
      "data-management",
      "governance-management",
      "access-audit",
    ]);
  });

  it("no longer exposes the retired personal workspace", () => {
    expect(navItems.some((item) => item.href === "/my-workspace")).toBe(false);
    expect(navigation.some((group) => (group.id as string) === "personal")).toBe(false);
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
    const assets = navItems.find((item) => item.href === "/assets");
    expect(assets?.label).toBe("全部资产台账");
    expect(getActiveGroup("/assets/example")).toBe("data-management");
  });

  it("groups user management under access-audit and gates it to platform_data_admin", () => {
    const group = navigation.find((item) => item.id === "access-audit");
    expect(group?.items.map((item) => item.href)).toEqual([
      "/iam-audit",
      "/api-callers",
      "/users",
    ]);
    const users = group?.items.find((item) => item.href === "/users");
    expect(users?.label).toBe("用户管理");
    expect(users?.allowedRoles).toEqual(["platform_data_admin"]);
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

  it("splits admin- and expert-only prefixes disjointly", () => {
    expect(ADMIN_ONLY_PREFIXES).toEqual([
      "/workbench",
      "/data-sources",
      "/raw-ledger",
      "/jobs",
      "/assets",
      "/iam-audit",
      "/api-callers",
      "/users",
    ]);
    expect(EXPERT_ONLY_PREFIXES).toEqual([
      "/asset-center",
      "/query",
      "/tag-review",
      "/governance",
      "/rules",
      "/ai-prompts",
    ]);
    // The two sets never overlap — the role split is intentionally disjoint.
    const intersection = ADMIN_ONLY_PREFIXES.filter((p) => EXPERT_ONLY_PREFIXES.includes(p));
    expect(intersection).toEqual([]);
  });

  it("resolves per-role visibility through allowedRoles", () => {
    expect(roleCanAccess("platform_data_admin", ["platform_data_admin"])).toBe(true);
    expect(roleCanAccess("business_expert", ["platform_data_admin"])).toBe(false);
    expect(roleCanAccess("business_expert", ["business_expert"])).toBe(true);
    expect(roleCanAccess("platform_data_admin", ["business_expert"])).toBe(false);
    // Undefined allowedRoles = public to any authenticated user.
    expect(roleCanAccess("business_expert", undefined)).toBe(true);
    expect(roleCanAccess(undefined, undefined)).toBe(true);

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
