import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MajorProfile } from "@/lib/api";

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const { getApiDataMock, replaceMock } = vi.hoisted(() => ({
  getApiDataMock: vi.fn(),
  replaceMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/asset-center/major/profiles",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, getApiData: getApiDataMock };
});

import { MajorProfilesTable } from "./MajorProfilesTable";

const summary: MajorProfile = {
  id: "profile-1",
  normalized_ref_id: "ref-1",
  asset_version_id: "version-1",
  domain_profile: "major_profile.v1",
  major_code: "530702",
  major_name: "跨境电子商务",
  profile_source: "institution_profile",
  institution_name: "浙江商业职业技术学院",
  region_tags: ["浙江省"],
  education_level: "高职专科",
  basic_study_duration: "三年",
  training_goal: "培养跨境电子商务运营和数据分析技术技能人才。",
  source_title: "跨境电子商务专业简介",
  extractor_version: "major_profile_extractor.v1",
  confidence: 0.92,
  quality_flags: {},
  status: "generated",
  created_at: "2026-09-09T00:00:00Z",
  updated_at: "2026-09-09T00:00:00Z",
};

const item = (id: string, text: string, itemIndex = 1) => ({
  id,
  profile_id: summary.id,
  normalized_ref_id: summary.normalized_ref_id,
  item_index: itemIndex,
  text,
  source_text: text,
  evidence_block_ids: [`block-${id}`],
  locator: {},
  confidence: 0.9,
});

const detail: MajorProfile = {
  ...summary,
  occupations: [
    {
      ...item("occupation", "跨境电商运营专员"),
      normalized_name: "跨境电商运营专员",
      occupation_type: "position",
    },
  ],
  abilities: [item("ability", "具备跨境平台运营与数据分析能力")],
  courses: [
    { ...item("course-1", "跨境电子商务实务"), course_group: "core", course_type: "course" },
    {
      ...item("course-2", "跨境电商综合实训"),
      course_group: "practice_training",
      course_type: "training",
    },
  ],
  certificates: [
    {
      ...item("certificate", "跨境电商运营职业技能等级证书"),
      certificate_type: "vocational_skill_level",
    },
  ],
};

function renderTable() {
  return render(
    <MajorProfilesTable
      rows={[summary]}
      total={1}
      page={1}
      pageSize={20}
      filters={{}}
      ok
      error={null}
      traceId={null}
    />,
  );
}

describe("MajorProfilesTable", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    getApiDataMock.mockReset();
    getApiDataMock.mockResolvedValue({ ok: true, data: detail, error: null });
  });

  it("renders the five business identity columns", () => {
    renderTable();

    for (const heading of ["专业名称", "专业代码", "修业年限", "培养层次", "院校名称"]) {
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByText("跨境电子商务")).toBeInTheDocument();
    expect(screen.getByText("530702")).toBeInTheDocument();
    expect(screen.getByText("三年")).toBeInTheDocument();
    expect(screen.getByText("高职专科")).toBeInTheDocument();
    expect(screen.getByText("浙江商业职业技术学院")).toBeInTheDocument();
  });

  it("lazily loads, renders, and caches the five detail sections", async () => {
    const user = userEvent.setup();
    renderTable();
    const expand = screen.getByRole("button", { name: /Expand row|展开行/ });

    expect(getApiDataMock).not.toHaveBeenCalled();
    await user.click(expand);

    await waitFor(() => expect(getApiDataMock).toHaveBeenCalledTimes(1));
    expect(getApiDataMock).toHaveBeenCalledWith("/api/major-profiles/profile-1", summary);
    const panel = await screen.findByTestId("major-profile-detail-panel");
    for (const heading of ["职业面向", "培养定位", "能力要求", "课程与实训", "证书信息"]) {
      expect(within(panel).getByRole("heading", { level: 4, name: heading })).toBeInTheDocument();
    }
    expect(panel).toHaveStyle({ marginLeft: "24px" });
    expect(within(panel).getAllByTestId("major-profile-section-content")).toHaveLength(5);
    for (const content of within(panel).getAllByTestId("major-profile-section-content")) {
      expect(content).toHaveClass("max-h-56", "overflow-y-auto");
    }
    expect(within(panel).getByText("跨境电商运营专员")).toBeInTheDocument();
    expect(within(panel).getByText(/培养跨境电子商务运营/)).toBeInTheDocument();
    expect(within(panel).getByText("具备跨境平台运营与数据分析能力")).toBeInTheDocument();
    expect(within(panel).getByText("跨境电子商务实务")).toBeInTheDocument();
    expect(within(panel).getByText("跨境电商综合实训")).toBeInTheDocument();
    expect(within(panel).getByText("跨境电商运营职业技能等级证书")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Collapse row|收起行/ }));
    fireEvent.click(screen.getByRole("button", { name: /Expand row|展开行/ }));
    expect(getApiDataMock).toHaveBeenCalledTimes(1);
  });
});
