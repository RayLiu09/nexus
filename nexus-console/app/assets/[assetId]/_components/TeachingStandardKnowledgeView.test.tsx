import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("./ChunkListSection", () => ({
  ChunkListSection: () => <div>教学标准知识块</div>,
}));

vi.mock("./CapabilityGraphView", () => ({
  CapabilityGraphView: () => <div>课程知识图谱内容</div>,
}));

import { TeachingStandardKnowledgeView } from "./TeachingStandardKnowledgeView";

describe("TeachingStandardKnowledgeView", () => {
  it("renders professional teaching-standard chunks without a directory control", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <TeachingStandardKnowledgeView
        normalizedRefId="ref-teaching-standard"
        graphBuildType="teaching_standard"
      />,
    );

    expect(screen.getByText("教学标准知识块")).toBeInTheDocument();
    expect(screen.queryByText("目录")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("切换教学标准知识视图")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("retains the separate course-standard graph option", () => {
    render(
      <TeachingStandardKnowledgeView
        normalizedRefId="ref-course-standard"
        graphBuildType="course_standard"
      />,
    );

    expect(screen.getByLabelText("切换教学标准知识视图")).toBeInTheDocument();
    expect(screen.getByText("课程知识图谱")).toBeInTheDocument();
    expect(screen.queryByText("目录")).not.toBeInTheDocument();
  });
});
