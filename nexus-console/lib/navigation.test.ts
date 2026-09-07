import { describe, expect, it } from "vitest";

import { getActiveGroup, getBreadcrumb, navigation } from "./navigation";

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

  it("builds Asset Center domain and nested resource breadcrumbs", () => {
    expect(getBreadcrumb("/asset-center/major/standard-course-library")).toEqual([
      { label: "NEXUS 控制台" },
      { label: "资产中心", href: "/asset-center" },
      { label: "专业数据" },
      { label: "标准课程库" },
    ]);
  });
});
