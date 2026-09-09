import { describe, expect, it } from "vitest";

import {
  ASSET_CENTER_DOMAINS,
  assetCenterHref,
  findAssetCenterDomain,
  findAssetCenterResource,
} from "./catalog";

describe("Asset Center catalogue", () => {
  it("freezes exactly five business domains without synthetic entries", () => {
    expect(ASSET_CENTER_DOMAINS.map((domain) => domain.name)).toEqual([
      "产业政策数据",
      "专业数据",
      "市场数据",
      "教材资源数据",
      "用户行为数据",
    ]);
    const resourceNames = ASSET_CENTER_DOMAINS.reduce<string[]>(
      (names, domain) => names.concat(domain.resources.map((resource) => resource.name)),
      [],
    );
    expect(resourceNames).not.toContain("产业画像");
  });

  it("keeps every fixed resource route unique and resolvable", () => {
    const hrefs = ASSET_CENTER_DOMAINS.flatMap((domain) =>
      domain.resources.map((resource) => assetCenterHref(domain, resource)),
    );

    expect(new Set(hrefs).size).toBe(hrefs.length);
    for (const domain of ASSET_CENTER_DOMAINS) {
      expect(findAssetCenterDomain(domain.slug)).toBe(domain);
      for (const resource of domain.resources) {
        expect(findAssetCenterResource(domain, resource.path)).toBe(resource);
      }
    }
  });

  it("does not create governance classifications for parks or enterprises", () => {
    const market = findAssetCenterDomain("market");
    expect(market).toBeDefined();
    expect(
      findAssetCenterResource(market!, "industrial-parks")?.classificationCode,
    ).toBeUndefined();
    expect(findAssetCenterResource(market!, "enterprises")?.classificationCode).toBeUndefined();
  });

  it("keeps occupational analysis under professional data", () => {
    const major = findAssetCenterDomain("major");
    const market = findAssetCenterDomain("market");

    expect(findAssetCenterResource(major!, "occupation-analyses")?.classificationCode).toBe(
      "competency_analysis",
    );
    expect(
      market!.resources.some((resource) => resource.classificationCode === "competency_analysis"),
    ).toBe(false);
  });

  it("keeps the standard course library as a projection-backed business entry", () => {
    const major = findAssetCenterDomain("major");
    expect(findAssetCenterResource(major!, "teaching-standards")?.classificationCode).toBe(
      "teaching_standard",
    );
    expect(findAssetCenterResource(major!, "standard-course-library")?.name).toBe("标准课程库");
    expect(findAssetCenterResource(major!, "standard-course-library")?.classificationCode).toBe(
      "teaching_standard",
    );
  });

  it("merges theory and training textbooks into the course-textbook entry", () => {
    const teachingResources = findAssetCenterDomain("teaching-resources");
    expect(findAssetCenterResource(teachingResources!, "course-textbooks")?.name).toBe("课程教材");
    expect(teachingResources!.resources.map((resource) => resource.name)).not.toContain("理论教材");
    expect(teachingResources!.resources.map((resource) => resource.name)).not.toContain("实训教材");
  });
});
