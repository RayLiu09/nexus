import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TeachingStandardCourse } from "@/lib/api";

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const { patchMock, postMock, replaceMock } = vi.hoisted(() => ({
  patchMock: vi.fn(),
  postMock: vi.fn(),
  replaceMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/asset-center/major/standard-course-library",
}));

vi.mock("@/lib/api", () => ({
  patchApiData: patchMock,
  postApiData: postMock,
}));

import { StandardCourseLibraryTable } from "./StandardCourseLibraryTable";

const course: TeachingStandardCourse = {
  id: "row-1",
  library_id: "library-1",
  course_id: "tsc-530701-core-01",
  course_name: "电子商务运营",
  major_code: "530701",
  major_name: "电子商务",
  educational_level: "高等职业教育专科",
  library_status: "review",
  course_type: "core",
  suggested_total_hours: 64,
  suggested_practice_hours: 32,
  suggested_hours_range: { min: 48, max: 72, unit: "学时" },
  hours_setting_basis: "依据典型工作任务复杂度设置",
  typical_work_task_description: "完成网店运营与推广",
  teaching_content_requirement: "掌握运营规划、实施和复盘方法",
  knowledge_tags: ["运营规划"],
  skill_tags: ["网店运营"],
  tool_tags: ["数据分析工具"],
  literacy_tags: ["质量意识"],
  match_keywords: "运营,实践",
  match_text: "运营实践课程建议安排64学时",
  source_standard: "电子商务专业教学标准",
  source_section: "专业核心课程",
  source_page: "12",
  source_order: 1,
  evidence_bindings: [
    {
      source_text: "完成网店运营与推广",
      evidence_block_ids: ["block-12"],
      locator: { page: 12, heading_path: ["专业核心课程"] },
    },
  ],
  updated_at: "2026-09-07T00:00:00Z",
};

function renderTable() {
  return render(
    <StandardCourseLibraryTable
      rows={[course]}
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

describe("StandardCourseLibraryTable", () => {
  beforeEach(() => {
    patchMock.mockReset();
    postMock.mockReset();
    replaceMock.mockReset();
  });

  it("expands all requested course details and exposes evidence provenance", () => {
    const { container } = renderTable();
    const expandButton = container.querySelector<HTMLButtonElement>(".ant-table-row-expand-icon");
    expect(expandButton).not.toBeNull();
    fireEvent.click(expandButton as HTMLButtonElement);

    expect(screen.getByText("完成网店运营与推广")).toBeInTheDocument();
    expect(screen.getByText("掌握运营规划、实施和复盘方法")).toBeInTheDocument();
    expect(screen.getByText("运营规划")).toBeInTheDocument();
    expect(screen.getByText("质量意识")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /血缘追溯/ }));
    expect(screen.getByText("依据典型工作任务复杂度设置")).toBeInTheDocument();
    expect(screen.getByText("运营实践课程建议安排64学时")).toBeInTheDocument();
    expect(screen.getByText(/block-12/)).toBeInTheDocument();
  });

  it("updates numeric hour suggestions and activates the whole parent standard", async () => {
    patchMock.mockResolvedValue({ data: { ...course, suggested_total_hours: 72 } });
    postMock.mockResolvedValue({ data: { id: "library-1", status: "active", changed: true } });
    renderTable();

    fireEvent.change(screen.getByRole("spinbutton", { name: "电子商务运营建议总学时" }), {
      target: { value: "72" },
    });
    fireEvent.click(screen.getByRole("button", { name: /更新/ }));
    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/teaching-standard-courses/row-1", {
        suggested_total_hours: 72,
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: /激活/ }));
    expect(screen.getByText(/专业教学标准及其全部课程记录/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认激活" }));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/api/teaching-standard-libraries/library-1/activate",
        {},
      ),
    );
  });
});
