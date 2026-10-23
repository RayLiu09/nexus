import { render } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { getApiData } from "@/lib/api";
import AssetCenterRoute from "./page";

vi.mock("@/lib/api", () => ({ getApiData: vi.fn() }));
vi.mock("@/lib/auth/serverSession", () => ({ getServerSession: vi.fn().mockResolvedValue(null) }));
vi.mock("../../_components/IndustryPoliciesTable", () => ({ IndustryPoliciesTable: () => null }));
vi.mock("../../_components/MajorProfilesTable", () => ({ MajorProfilesTable: () => null }));
vi.mock("../../_components/TalentDemandReportsTable", () => ({
  TalentDemandReportsTable: () => null,
}));
vi.mock("../../_components/TeachingCasesTable", () => ({ TeachingCasesTable: () => null }));

const filters = { region: "重庆市", industry: "电子商务", content_tag: "融合" };
const identity = { major_name: "电子商务", major_code: "530701", institution_name: "重庆职业学院" };

beforeEach(() => {
  vi.mocked(getApiData).mockReset();
  vi.mocked(getApiData).mockResolvedValue({
    ok: true,
    data: [],
    total: 0,
    error: null,
    traceId: null,
  });
});

it.each(["industry-policies", "industry-reports", "sector-reports"])(
  "%s sends the same tag scope to every topic count and paged request",
  async (resource) => {
    render(
      await AssetCenterRoute({
        params: Promise.resolve({ domain: "policy", resource: [resource] }),
        searchParams: Promise.resolve({
          ...filters,
          region: " 重庆市 ",
          page: "3",
          topic: "low_altitude",
        }),
      }),
    );
    expect(getApiData).toHaveBeenCalledTimes(4);
    expect(vi.mocked(getApiData).mock.calls.map((call) => call[2])).toEqual([
      { ...filters, page: "3", pageSize: "20", topic: "low_altitude" },
      { ...filters, page: "1", pageSize: "1" },
      { ...filters, page: "1", pageSize: "1", topic: "finance_commerce" },
      { ...filters, page: "1", pageSize: "1", topic: "low_altitude" },
    ]);
  },
);

it.each([
  ["major", "profiles", "major-profile-documents"],
  ["major", "talent-demand-reports", "talent-demand-reports"],
  ["teaching-resources", "cases", "teaching-cases"],
])("%s/%s passes filters to its server list", async (domain, resource, endpoint) => {
  render(
    await AssetCenterRoute({
      params: Promise.resolve({ domain, resource: [resource] }),
      searchParams: Promise.resolve({
        ...filters,
        ...identity,
        q: "商务",
        page: "2",
        pageSize: "50",
      }),
    }),
  );
  expect(getApiData).toHaveBeenCalledExactlyOnceWith(`/internal/v1/${endpoint}`, [], {
    ...(resource === "profiles"
      ? identity
      : resource === "talent-demand-reports"
        ? { ...identity, content_tag: filters.content_tag }
        : filters),
    page: "2",
    pageSize: "50",
  });
});
