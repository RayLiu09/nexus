import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TeachingStandardLibrary } from "@/lib/api";

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const { pushMock, replaceMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  replaceMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
  usePathname: () => "/asset-center/major/teaching-standards",
}));

vi.mock("@/app/assets/[assetId]/_components/CapabilityGraphView", () => ({
  CapabilityGraphView: ({
    normalizedRefId,
    buildType,
    embedded,
  }: {
    normalizedRefId: string;
    buildType: string;
    embedded?: boolean;
  }) => (
    <div data-embedded={embedded} data-testid="professional-graph">
      {`${normalizedRefId}:${buildType}`}
    </div>
  ),
}));

import { TeachingStandardsTable } from "./TeachingStandardsTable";

const row: TeachingStandardLibrary = {
  id: "library-1",
  normalized_ref_id: "ref-1",
  asset_version_id: "version-1",
  standard_title: "电子商务专业教学标准",
  major_code: "530701",
  major_name: "电子商务",
  major_category_code: "53",
  major_category_name: "财经商贸大类",
  major_class_code: "5307",
  major_class_name: "电子商务类",
  educational_level: "高等职业教育专科",
  basic_study_years: "三年",
  status: "review",
  course_count: 24,
  updated_at: "2026-09-07T00:00:00Z",
};

describe("TeachingStandardsTable", () => {
  beforeEach(() => {
    pushMock.mockReset();
    replaceMock.mockReset();
  });

  it("renders the professional identity fields and opens the migrated professional graph", () => {
    render(
      <TeachingStandardsTable
        rows={[row]}
        total={1}
        page={1}
        pageSize={20}
        filters={{}}
        ok
        error={null}
        traceId={null}
      />,
    );

    expect(screen.getByText("530701")).toBeInTheDocument();
    expect(screen.getByText("财经商贸大类 (53)")).toBeInTheDocument();
    expect(screen.getByText("电子商务类 (5307)")).toBeInTheDocument();
    expect(screen.getByText("高等职业教育专科")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /职业领域图谱/ }));
    expect(screen.getByTestId("professional-graph")).toHaveTextContent("ref-1:teaching_standard");
    expect(screen.getByTestId("professional-graph")).toHaveAttribute("data-embedded", "true");
  });

  it("opens the standard course library with a parent-library filter", () => {
    render(
      <TeachingStandardsTable
        rows={[row]}
        total={1}
        page={1}
        pageSize={20}
        filters={{}}
        ok
        error={null}
        traceId={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /课程库/ }));
    expect(pushMock).toHaveBeenCalledWith(
      "/asset-center/major/standard-course-library?libraryId=library-1",
    );
  });
});
